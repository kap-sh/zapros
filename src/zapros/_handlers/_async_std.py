from __future__ import annotations

import asyncio
import ssl
import time
from collections import deque
from collections.abc import (
    Awaitable,
    Iterator as ABCIterator,
)
from dataclasses import dataclass, field
from typing import Protocol, TypeVar, cast

import h11
from typing_extensions import override

from .._errors import (
    ConnectionError,
    TotalTimeoutError,
)
from .._models import (
    AsyncClosableStream,
    Request,
    Response,
)
from ._async_base import AsyncBaseHandler
from ._exc_map import map_connect_exceptions, map_read_exceptions, map_write_exceptions

PoolKey = tuple[str, str, int]  # (scheme, host, port)
_T = TypeVar("_T")


class PoolConnection(Protocol):
    def close(self) -> None: ...

    @property
    def is_closed(self) -> bool: ...

    def can_reuse(self) -> bool: ...


def _encode_target(path: str, query: str) -> bytes:
    """Encode an already-prepared request target without rewriting semantics.

    The request object is expected to contain a fully prepared / already-encoded
    path and query. We only join them and convert to ASCII bytes for h11.
    """
    prepared_path = path or "/"
    if query:
        return f"{prepared_path}?{query}".encode("ascii")
    return prepared_path.encode("ascii")


def _header_has_token(
    headers: list[tuple[str, str]],
    name: str,
    token: str,
) -> bool:
    name = name.lower()
    token = token.lower()
    for k, v in headers:
        if k.lower() != name:
            continue
        for part in v.split(","):
            if part.strip().lower() == token:
                return True
    return False


def _min_timeout(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


class AsyncConn:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.h11 = h11.Connection(h11.CLIENT)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.writer.close()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed or self.writer.is_closing()

    def can_reuse(self) -> bool:
        return not self.is_closed and self.h11.our_state is h11.IDLE and self.h11.their_state is h11.IDLE


@dataclass
class IdlePoolConnection:
    conn: PoolConnection
    last_used: float = field(default_factory=time.monotonic)


class ConnPool:
    """Async connection pool keyed by (scheme, host, port).

    Limits total checked-out + idle connections per host and keeps a bounded
    LIFO idle cache for reuse.
    """

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

        self._lock = asyncio.Lock()
        self._idle: dict[PoolKey, deque[IdlePoolConnection]] = {}
        self._semaphores: dict[PoolKey, asyncio.Semaphore] = {}
        self._closed = False

    async def _get_semaphore(self, key: PoolKey) -> asyncio.Semaphore:
        async with self._lock:
            sem = self._semaphores.get(key)
            if sem is None:
                sem = asyncio.Semaphore(self._max_connections_per_host)
                self._semaphores[key] = sem
            return sem

    async def acquire(self, key: PoolKey) -> PoolConnection | None:
        """Reserve a slot and return the freshest usable idle connection, if any."""
        sem = await self._get_semaphore(key)
        await sem.acquire()

        now = time.monotonic()
        async with self._lock:
            if self._closed:
                sem.release()
                raise RuntimeError("Pool is closed")

            dq = self._idle.get(key)
            if not dq:
                return None

            while dq:
                item = dq.pop()  # LIFO – reuse the freshest
                if (now - item.last_used) <= self._max_age and item.conn.can_reuse():
                    return item.conn
                _close_quietly(item.conn)

        return None

    async def release_reservation(self, key: PoolKey) -> None:
        """Release a previously acquired slot when no connection will be returned."""
        sem = await self._get_semaphore(key)
        sem.release()

    async def release(
        self,
        key: PoolKey,
        conn: PoolConnection,
        *,
        reuse: bool,
    ) -> None:
        """Return a connection and release its reserved slot."""
        sem = await self._get_semaphore(key)

        try:
            if not reuse:
                _close_quietly(conn)
                return

            async with self._lock:
                if self._closed:
                    _close_quietly(conn)
                    return

                dq = self._idle.setdefault(key, deque())
                dq.append(IdlePoolConnection(conn=conn))

                while len(dq) > self._max_idle_per_host:
                    _close_quietly(dq.popleft().conn)
        finally:
            sem.release()

    async def close_all(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            idle, self._idle = self._idle, {}

        for dq in idle.values():
            for item in dq:
                _close_quietly(item.conn)


def _close_quietly(conn: PoolConnection) -> None:
    try:
        conn.close()
    except Exception:
        pass


class AsyncStdStream(AsyncClosableStream):
    """Wrap an h11 response stream and return the connection to the pool on close."""

    def __init__(
        self,
        conn: AsyncConn,
        pool: ConnPool,
        key: PoolKey,
        *,
        read_timeout: float | None = None,
        no_body_response: bool = False,
        must_close: bool = False,
    ) -> None:
        self._conn = conn
        self._pool = pool
        self._key = key
        self._read_timeout = read_timeout
        self._closed = False
        self._eof = False
        self._ok = True
        self._no_body_response = no_body_response
        self._must_close = must_close

    def __aiter__(self) -> AsyncStdStream:
        return self

    async def _read(self, n: int) -> bytes:
        with map_read_exceptions():
            if self._read_timeout is None:
                return await self._conn.reader.read(n)
            return await asyncio.wait_for(
                self._conn.reader.read(n),
                timeout=self._read_timeout,
            )

    def _drain_no_body_end_of_message(self) -> None:
        """Advance h11 to IDLE for responses that are known to have no body."""
        if self._eof or not self._no_body_response:
            return

        while True:
            event = self._conn.h11.next_event()
            if isinstance(event, h11.EndOfMessage):
                self._eof = True
                self._conn.h11.start_next_cycle()
                return
            if event is h11.NEED_DATA:
                # For true no-body responses, h11 should not need socket reads here.
                self._ok = False
                return
            if isinstance(event, h11.Data):
                self._ok = False
                return

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration

        try:
            with map_read_exceptions():
                while True:
                    event = self._conn.h11.next_event()

                    if event is h11.NEED_DATA:
                        data = await self._read(8192)
                        if not data:
                            self._conn.h11.receive_data(b"")
                            continue
                        self._conn.h11.receive_data(data)
                        continue

                    if isinstance(event, h11.Data):
                        return bytes(event.data)

                    if isinstance(event, h11.EndOfMessage):
                        self._eof = True
                        try:
                            self._conn.h11.start_next_cycle()
                        except Exception:
                            self._ok = False
                        await self.aclose()
                        raise StopAsyncIteration

        except BaseException:
            self._ok = False
            await self.aclose()
            raise

    @override
    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._no_body_response and not self._eof and self._ok:
            try:
                self._drain_no_body_end_of_message()
            except Exception:
                self._ok = False

        reuse = self._eof and self._ok and not self._must_close and self._conn.can_reuse()

        await self._pool.release(
            self._key,
            self._conn,
            reuse=reuse,
        )


class AsyncStdNetworkHandler(AsyncBaseHandler):
    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        total_timeout: float | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        max_connections_per_host: int = 10,
        max_idle_connections_per_host: int | None = None,
        max_idle_seconds: float = 30.0,
    ) -> None:
        self.ssl_context = ssl_context or ssl.create_default_context()

        # Total timeout means: start of ahandle() until response headers received.
        self.total_timeout = total_timeout

        # Per-phase timeouts remain independently configurable.
        self.connect_timeout = connect_timeout if connect_timeout is not None else None
        self.read_timeout = read_timeout if read_timeout is not None else None
        self.write_timeout = write_timeout if write_timeout is not None else None

        self._pool = ConnPool(
            max_connections_per_host=max_connections_per_host,
            max_idle_per_host=(
                max_connections_per_host if max_idle_connections_per_host is None else max_idle_connections_per_host
            ),
            max_idle_seconds=max_idle_seconds,
        )

    @staticmethod
    async def _await_with_timeout(
        awaitable: Awaitable[_T],
        timeout: float | None,
    ) -> _T:
        if timeout is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout=timeout)

    @staticmethod
    def _remaining_timeout(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TotalTimeoutError("Operation timed out")
        return remaining

    async def _new_conn(
        self,
        scheme: str,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
    ) -> AsyncConn:
        ssl_ctx = self.ssl_context if scheme == "https" else None
        reader: asyncio.StreamReader
        writer: asyncio.StreamWriter
        with map_connect_exceptions():
            reader, writer = await self._await_with_timeout(
                asyncio.open_connection(
                    host,
                    port,
                    ssl=ssl_ctx,
                    server_hostname=host if ssl_ctx else None,
                    happy_eyeballs_delay=0.25,
                    interleave=1,
                    ssl_handshake_timeout=connect_timeout,
                ),
                connect_timeout,
            )
        return AsyncConn(reader, writer)

    @staticmethod
    def _prepare_body(
        request: Request,
    ) -> bytes | ABCIterator[bytes] | None:
        if request.body is None:
            return None
        if isinstance(request.body, (bytes, ABCIterator)):
            return request.body
        raise NotImplementedError("Async request bodies are not supported by AsyncStdNetworkHandler")

    @staticmethod
    def _response_has_no_body(
        method: str,
        status: int,
        headers: list[tuple[str, str]],
    ) -> bool:
        del headers  # framing is handled by h11; this only covers semantic no-body cases
        if method.upper() == "HEAD":
            return True
        if 100 <= status < 200:
            return True
        if status in (204, 304):
            return True
        return False

    async def _drain_writer(
        self,
        writer: asyncio.StreamWriter,
        *,
        write_timeout: float | None = None,
    ) -> None:
        with map_write_exceptions():
            await self._await_with_timeout(
                writer.drain(),
                write_timeout,
            )

    async def _read(
        self,
        reader: asyncio.StreamReader,
        n: int,
        *,
        read_timeout: float | None = None,
    ) -> bytes:
        with map_read_exceptions():
            return await self._await_with_timeout(
                reader.read(n),
                read_timeout,
            )

    def _resolve_timeouts(
        self,
        request: Request,
    ) -> tuple[
        float | None,
        float | None,
        float | None,
        float | None,
    ]:
        """Return (total_timeout, connect_timeout, read_timeout, write_timeout).

        Per-request values from request.context["timeouts"] take priority over
        handler defaults.
        """
        timeouts_context = request.context.get("timeouts", {})

        req_total = timeouts_context.get("total")
        req_connect = timeouts_context.get("connect")
        req_read = timeouts_context.get("read")
        req_write = timeouts_context.get("write")

        total_timeout = req_total if req_total is not None else self.total_timeout
        connect_timeout = req_connect if req_connect is not None else self.connect_timeout
        read_timeout = req_read if req_read is not None else self.read_timeout
        write_timeout = req_write if req_write is not None else self.write_timeout

        return (
            total_timeout,
            connect_timeout,
            read_timeout,
            write_timeout,
        )

    async def ahandle(self, request: Request) -> Response:
        (
            total_timeout,
            connect_timeout,
            read_timeout,
            write_timeout,
        ) = self._resolve_timeouts(request)
        deadline = None if total_timeout is None else (time.monotonic() + total_timeout)

        port = int(request.url.port) if request.url.port != "" else (443 if request.url.protocol == "https:" else 80)
        key: PoolKey = (
            request.url.protocol[:-1],
            request.url.hostname,
            port,
        )

        conn: AsyncConn | None = cast(
            AsyncConn | None,
            await self._await_with_timeout(
                self._pool.acquire(key),
                self._remaining_timeout(deadline),
            ),
        )
        if conn is None:
            try:
                conn = await self._new_conn(
                    request.url.protocol[:-1],
                    request.url.hostname,
                    port,
                    connect_timeout=_min_timeout(
                        connect_timeout,
                        self._remaining_timeout(deadline),
                    ),
                )
            except BaseException:
                await self._pool.release_reservation(key)
                raise

        target = _encode_target(
            request.url.pathname,
            request.url.search[1:],
        )

        body = self._prepare_body(request)

        headers = list(request.headers.list())
        request_wants_close = _header_has_token(
            headers,
            "connection",
            "close",
        )

        try:
            with map_read_exceptions():
                event = h11.Request(
                    method=request.method.encode("ascii"),
                    target=target,
                    headers=[
                        (
                            k.encode("ascii"),
                            v.encode("latin-1"),
                        )
                        for k, v in headers
                    ],
                )
                conn.writer.write(conn.h11.send(event))
                await self._drain_writer(
                    conn.writer,
                    write_timeout=_min_timeout(
                        write_timeout,
                        self._remaining_timeout(deadline),
                    ),
                )

                if isinstance(body, bytes):
                    if body:
                        conn.writer.write(conn.h11.send(h11.Data(data=body)))
                        await self._drain_writer(
                            conn.writer,
                            write_timeout=_min_timeout(
                                write_timeout,
                                self._remaining_timeout(deadline),
                            ),
                        )
                elif isinstance(body, ABCIterator):
                    for chunk in body:
                        if chunk:
                            conn.writer.write(conn.h11.send(h11.Data(data=chunk)))
                            await self._drain_writer(
                                conn.writer,
                                write_timeout=_min_timeout(
                                    write_timeout,
                                    self._remaining_timeout(deadline),
                                ),
                            )

                conn.writer.write(conn.h11.send(h11.EndOfMessage()))
                await self._drain_writer(
                    conn.writer,
                    write_timeout=_min_timeout(
                        write_timeout,
                        self._remaining_timeout(deadline),
                    ),
                )

                while True:
                    event = conn.h11.next_event()

                    if event is h11.NEED_DATA:
                        data = await self._read(
                            conn.reader,
                            8192,
                            read_timeout=_min_timeout(
                                read_timeout,
                                self._remaining_timeout(deadline),
                            ),
                        )
                        if not data:
                            raise ConnectionError("Connection closed while reading response headers")
                        conn.h11.receive_data(data)
                        continue

                    if isinstance(event, h11.InformationalResponse):
                        continue

                    if isinstance(event, h11.Response):
                        status = event.status_code
                        resp_headers = [
                            (
                                k.decode("ascii"),
                                v.decode("latin-1"),
                            )
                            for k, v in event.headers
                        ]
                        break

                    raise ConnectionError(f"Unexpected HTTP event while reading headers: {event!r}")

            no_body_response = self._response_has_no_body(
                request.method,
                status,
                resp_headers,
            )
            response_wants_close = _header_has_token(
                resp_headers,
                "connection",
                "close",
            )

            return Response(
                status=status,
                headers=resp_headers,
                content=AsyncStdStream(
                    conn,
                    self._pool,
                    key,
                    read_timeout=read_timeout,
                    no_body_response=no_body_response,
                    must_close=(request_wants_close or response_wants_close),
                ),
            )

        except BaseException:
            await self._pool.release(key, conn, reuse=False)
            raise

    async def aclose(self) -> None:
        await self._pool.close_all()
