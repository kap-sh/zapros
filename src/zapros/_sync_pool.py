from __future__ import annotations

import threading
import time
from threading import Semaphore
from collections import deque
from dataclasses import dataclass

from ._base_pool import IdlePoolConnection, PoolConnection, PoolKey


@dataclass
class _HostState:
    semaphore: Semaphore
    refs: int = 0
    idle: deque[IdlePoolConnection] | None = None


class ConnPool:
    def __init__(
        self,
        *,
        max_connections_per_host: int = 10,
        max_idle_per_host: int = 10,
        max_idle_seconds: float = 30.0,
    ) -> None:
        self._max_connections_per_host = max_connections_per_host
        self._max_idle_per_host = max_idle_per_host
        self._max_age = max_idle_seconds

        self._lock = threading.Lock()
        self._states: dict[PoolKey, _HostState] = {}
        self._closed = False

    def _get_state(self, key: PoolKey) -> _HostState:
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _HostState(semaphore=Semaphore(self._max_connections_per_host))
                self._states[key] = state

            state.refs += 1
            return state

    def _release_state_ref(self, key: PoolKey, state: _HostState) -> None:
        with self._lock:
            if self._states.get(key) is not state:
                return

            if state.refs <= 1:
                state.refs = 0
            else:
                state.refs -= 1

            if state.refs == 0 and state.idle is None and state.semaphore._value >= self._max_connections_per_host:
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
                if (now - item.last_used) <= self._max_age and item.conn.can_reuse():
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
                state = _HostState(semaphore=Semaphore(self._max_connections_per_host))
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

    def adopt(
        self,
        key: PoolKey,
        conn: PoolConnection,
    ) -> bool:
        """
        Adopts a connection into the pool for the given key without acquiring a slot first.

        This is used when a connection is created outside the pool but should be
        added to the pool for reuse.

        Returns True if the connection was successfully adopted, False otherwise.
        """
        state = self._get_state(key)
        sem = state.semaphore
        sem.acquire()
        slot_transferred = False
        to_close: list[PoolConnection] = []

        try:
            kept, to_close = self._store_idle_connection(key, conn)
            _close_many_quietly(to_close)

            if not kept:
                return False

            slot_transferred = True
            return True

        finally:
            if not slot_transferred:
                sem.release()
                if self._closed and conn not in to_close:
                    _close_quietly(conn)

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


def _close_many_quietly(conns: list[PoolConnection]) -> None:
    for conn in conns:
        _close_quietly(conn)


def _close_quietly(conn: PoolConnection) -> None:
    try:
        conn.close()
    except Exception:
        pass
