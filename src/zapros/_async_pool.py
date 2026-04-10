from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from ._base_pool import AsyncIdlePoolConnection, AsyncPoolConnection, PoolKey
from ._compat import AnyLock, AnySemaphore


@dataclass
class _HostState:
    semaphore: AnySemaphore
    refs: int = 0
    idle: deque[AsyncIdlePoolConnection] | None = None


class AsyncConnPool:
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

        self._lock = AnyLock()
        self._states: dict[PoolKey, _HostState] = {}
        self._closed = False

    async def _get_state(self, key: PoolKey) -> _HostState:
        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _HostState(semaphore=AnySemaphore(self._max_connections_per_host))
                self._states[key] = state

            state.refs += 1
            return state

    async def _release_state_ref(self, key: PoolKey, state: _HostState) -> None:
        async with self._lock:
            if self._states.get(key) is not state:
                return

            if state.refs <= 1:
                state.refs = 0
            else:
                state.refs -= 1

            if state.refs == 0 and state.idle is None and state.semaphore._value >= self._max_connections_per_host:  # type: ignore[reportPrivateUsage]
                self._states.pop(key, None)

    async def _take_idle_connection(
        self,
        key: PoolKey,
        now: float,
    ) -> tuple[AsyncPoolConnection | None, list[AsyncPoolConnection]]:
        stale: list[AsyncPoolConnection] = []

        async with self._lock:
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

    async def _store_idle_connection(
        self,
        key: PoolKey,
        conn: AsyncPoolConnection,
    ) -> tuple[bool, list[AsyncPoolConnection]]:
        """
        Adds conn to the idle deque for key.

        Returns:
            kept:
                True when conn remained in the idle pool.
                False when it was rejected/evicted.
            to_close:
                Connections removed from the idle pool and needing close().
        """
        async with self._lock:
            if self._closed:
                return False, [conn]

            state = self._states.get(key)
            if state is None:
                state = _HostState(semaphore=AnySemaphore(self._max_connections_per_host))
                self._states[key] = state

            dq = state.idle
            if dq is None:
                dq = state.idle = deque()

            dq.append(AsyncIdlePoolConnection(conn=conn))

            to_close: list[AsyncPoolConnection] = []
            while len(dq) > self._max_idle_per_host:
                to_close.append(dq.popleft().conn)

            return conn not in to_close, to_close

    async def acquire(
        self,
        key: PoolKey,
    ) -> AsyncPoolConnection | None:
        """
        Acquires a connection from the pool for the given key.

        Tries to get a slot for the key, then returns an idle connection if available
        and valid, otherwise returns None.

        When None is returned the caller is expected to create a new connection and
        call release() with reuse=False when done.
        """
        state = await self._get_state(key)
        sem = state.semaphore
        await sem.acquire()
        release_sem = True

        try:
            conn, to_close = await self._take_idle_connection(
                key,
                time.monotonic(),
            )
            await _close_many_quietly(to_close)

            release_sem = False
            return conn

        except BaseException:
            if release_sem:
                sem.release()
            raise

        finally:
            await self._release_state_ref(key, state)

    async def release_reservation(self, key: PoolKey) -> None:
        state = await self._get_state(key)
        try:
            state.semaphore.release()
        finally:
            await self._release_state_ref(key, state)

    async def release(
        self,
        key: PoolKey,
        conn: AsyncPoolConnection,
        *,
        reuse: bool,
    ) -> None:
        """
        Releases a connection back to the pool for the given key.

        If reuse is False, the connection will be closed and not added back to the pool.
        """
        state = await self._get_state(key)

        try:
            if not reuse:
                await _close_quietly(conn)
                return

            _, to_close = await self._store_idle_connection(key, conn)
            await _close_many_quietly(to_close)

        finally:
            state.semaphore.release()
            await self._release_state_ref(key, state)

    async def close_all(self) -> None:
        """
        Closes all idle connections in the pool and prevents new connections
        from being added.
        """
        async with self._lock:
            if self._closed:
                return

            self._closed = True
            states, self._states = self._states, {}

        for state in states.values():
            for item in state.idle or ():
                await _close_quietly(item.conn)


async def _close_many_quietly(conns: list[AsyncPoolConnection]) -> None:
    for conn in conns:
        await _close_quietly(conn)


async def _close_quietly(conn: AsyncPoolConnection) -> None:
    try:
        await conn.close()
    except Exception:
        pass
