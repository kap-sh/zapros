from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from ._base_pool import IdlePoolConnection, PoolConnection, PoolKey
from threading import Lock, Semaphore


@dataclass
class HostState:
    semaphore: Semaphore
    """
    Semaphore controlling the maximum number of concurrent connections for this host.
    """

    refs: int = 0
    """
    Number of callers currently holding a pointer to this HostState -- that
    is, callers between _get_state and _release_state_ref. Should be mutated only under
    the lock.

    Needed because callers do real work (awaiting the semaphore, using a
    connection) *outside* the lock while still relying on this state. Without
    a refcount, a concurrent _release_state_ref could observe an empty idle
    deque and a fully-replenished semaphore and evict the entry from _states;
    the next _get_state for the same key would then create a fresh state with
    a fresh semaphore, silently breaking the per-host concurrency limit.

    While refs > 0, the eviction check in _release_state_ref leaves the entry
    in place, guaranteeing that every concurrent caller for the same key
    shares the same semaphore and idle deque.
    """

    idle: deque[IdlePoolConnection] | None = None
    """
    Deque of idle connections for this host, ordered from least recently used (left) to most recently used (right).
    None when no idle connections are currently stored.
    """


class Http1ConnectionPool:
    def __init__(
        self,
        *,
        max_connections_per_host: int | None = None,
        max_idle_per_host: int | None = None,
        max_idle_seconds: float | None = None,
    ) -> None:
        self._max_connections_per_host = max_connections_per_host if max_connections_per_host is not None else 10
        self._max_idle_per_host = max_idle_per_host if max_idle_per_host is not None else 10
        self._max_age = max_idle_seconds if max_idle_seconds is not None else 30.0

        self._lock = Lock()
        self._states: dict[PoolKey, HostState] = {}
        self._closed = False

    def _get_state(self, key: PoolKey) -> HostState:
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = HostState(semaphore=Semaphore(self._max_connections_per_host))
                self._states[key] = state

            state.refs += 1
            return state

    def _release_state_ref(self, key: PoolKey, state: HostState) -> None:
        with self._lock:
            if self._states.get(key) is not state:
                return

            if state.refs <= 1:
                state.refs = 0
            else:
                state.refs -= 1

            if state.refs == 0 and state.idle is None and state.semaphore._value >= self._max_connections_per_host:  # type: ignore[reportPrivateUsage]
                self._states.pop(key, None)

    def _take_idle_connection(
        self,
        key: PoolKey,
        now: float,
    ) -> tuple[PoolConnection | None, list[PoolConnection]]:
        stale: list[PoolConnection] = []

        with self._lock:
            if self._closed:
                raise RuntimeError("Pool is closed")

            state = self._states.get(key)
            dq = None if state is None else state.idle

            if not dq:
                return None, stale

            while dq:
                item = dq.pop()
                if (now - item.last_used) <= self._max_age and item.conn.can_handle_request():
                    if not dq:
                        state.idle = None  # type: ignore[reportOptionalMemberAccess]
                    return item.conn, stale

                stale.append(item.conn)

            state.idle = None  # type: ignore[reportOptionalMemberAccess]
            return None, stale

    def _store_idle_connection(
        self,
        key: PoolKey,
        conn: PoolConnection,
    ) -> tuple[bool, list[PoolConnection]]:
        """
        Adds conn to the idle deque for key.

        Returns:
            kept:
                True when conn remained in the idle pool.
                False when it was rejected/evicted.
            to_close:
                Connections removed from the idle pool and needing close().
        """
        with self._lock:
            if self._closed:
                return False, [conn]

            state = self._states.get(key)
            if state is None:
                state = HostState(semaphore=Semaphore(self._max_connections_per_host))
                self._states[key] = state

            dq = state.idle
            if dq is None:
                dq = state.idle = deque()

            dq.append(IdlePoolConnection(conn=conn))

            to_close: list[PoolConnection] = []
            while len(dq) > self._max_idle_per_host:
                to_close.append(dq.popleft().conn)

            return conn not in to_close, to_close

    def acquire(
        self,
        key: PoolKey,
    ) -> PoolConnection | None:
        """
        Acquires a connection from the pool for the given key.

        Tries to get a slot for the key, then returns an idle connection if available
        and valid, otherwise returns None.

        When None is returned the caller is expected to create a new connection and
        call release() with reuse=False when done.
        """
        state = self._get_state(key)
        sem = state.semaphore
        sem.acquire()
        release_sem = True

        try:
            conn, to_close = self._take_idle_connection(
                key,
                time.monotonic(),
            )
            _close_many_quietly(to_close)

            release_sem = False
            return conn

        except BaseException:
            if release_sem:
                sem.release()
            raise

        finally:
            self._release_state_ref(key, state)

    def release_reservation(self, key: PoolKey) -> None:
        state = self._get_state(key)
        try:
            state.semaphore.release()
        finally:
            self._release_state_ref(key, state)

    def acquire_reservation(self, key: PoolKey) -> None:
        state = self._get_state(key)
        try:
            state.semaphore.acquire()
        finally:
            self._release_state_ref(key, state)

    def release(
        self,
        key: PoolKey,
        conn: PoolConnection,
        *,
        reuse: bool,
    ) -> None:
        """
        Releases a connection back to the pool for the given key.

        If reuse is False, the connection will be closed and not added back to the pool.
        """
        state = self._get_state(key)

        try:
            if not reuse:
                _close_quietly(conn)
                return

            _, to_close = self._store_idle_connection(key, conn)
            _close_many_quietly(to_close)

        finally:
            state.semaphore.release()
            self._release_state_ref(key, state)

    def close_all(self) -> None:
        """
        Closes all idle connections in the pool and prevents new connections
        from being added.
        """
        with self._lock:
            if self._closed:
                return

            self._closed = True
            states, self._states = self._states, {}

        for state in states.values():
            for item in state.idle or ():
                _close_quietly(item.conn)


class Http2ConnectionPool:
    """
    Single-connection-per-key pool for multiplexing connections (HTTP/2).

    HTTP/2 connections serve many concurrent requests over a single socket,
    so this pool stores at most one connection per host key. Stale
    connections (closed by peer, terminated, or stream-id exhausted) are
    filtered at acquire time and replaced at register time. All operations
    are coroutine-safe; callers do not need any additional locking.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._conns: dict[PoolKey, PoolConnection] = {}
        self._closed = False

    def acquire(self, key: PoolKey) -> PoolConnection | None:
        """
        Return a usable connection for the key, or None.

        If the stored connection is no longer usable it is evicted and
        closed before returning None — the next caller will create a fresh
        one.
        """
        stale: PoolConnection | None = None
        with self._lock:
            conn = self._conns.get(key)
            if conn is None:
                return None
            if conn.can_handle_request():
                return conn
            del self._conns[key]
            stale = conn

        _close_quietly(stale)
        return None

    def register(
        self,
        key: PoolKey,
        conn: PoolConnection,
    ) -> PoolConnection:
        """
        Install conn at key and return the canonical connection for that key.

        Races are resolved by the pool: if another coroutine already
        installed a usable connection for the same key, the caller's conn
        is closed and the existing one is returned. If the existing entry
        is stale, it is replaced and closed. If the pool has been closed,
        the caller's conn is closed and the pool raises.
        """
        to_close: PoolConnection | None = None
        winner: PoolConnection | None = None
        with self._lock:
            if self._closed:
                to_close = conn
            else:
                existing = self._conns.get(key)
                if existing is not None and existing.can_handle_request():
                    to_close = conn
                    winner = existing
                else:
                    if existing is not None:
                        to_close = existing
                    self._conns[key] = conn
                    winner = conn

        if to_close is not None:
            _close_quietly(to_close)

        if winner is None:
            raise RuntimeError("Pool is closed")
        return winner

    def discard(self, key: PoolKey, conn: PoolConnection) -> None:
        """
        Evict conn from the pool (if still installed at key) and close it.

        If another connection has already replaced conn at this key, the
        replacement is left alone. The given conn is always closed.
        """
        with self._lock:
            if self._conns.get(key) is conn:
                del self._conns[key]
        _close_quietly(conn)

    def close_all(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            conns, self._conns = list(self._conns.values()), {}

        for conn in conns:
            _close_quietly(conn)


def _close_many_quietly(conns: list[PoolConnection]) -> None:
    for conn in conns:
        _close_quietly(conn)


def _close_quietly(conn: PoolConnection) -> None:
    try:
        conn.close()
    except Exception:
        pass
