from __future__ import annotations

import ssl
import time
import warnings
from collections.abc import (
    Iterator as ABCIterator,
)
from typing import cast

import h11
from pywhatwgurl import URL
from typing_extensions import override

from zapros._constants import DEFAULT_READ_SIZE, DEFAULT_SSL_CONTEXT
from zapros._io._asyncio import AsyncIOTransport
from zapros._io._base import AsyncBaseNetworkStream, AsyncBaseTransport
from zapros._utils import get_authority_value, get_pool_key

from .._async_pool import AsyncConnPool
from .._base_pool import PoolKey
from .._errors import (
    ConnectionError,
    TotalTimeoutError,
)
from .._models import (
    AsyncClosableStream,
    Request,
    Response,
    ResponseHandoffContext,
)
from ._async_base import AsyncBaseHandler
from ._exc_map import map_read_exceptions, map_write_exceptions


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
        stream: AsyncBaseNetworkStream,
    ) -> None:
        self.stream = stream
        self.h11 = h11.Connection(h11.CLIENT)
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.stream.close()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def can_reuse(self) -> bool:
        return not self.is_closed and self.h11.our_state is h11.IDLE and self.h11.their_state is h11.IDLE


class AsyncStdStream(AsyncClosableStream):
    """Wrap an h11 response stream and return the connection to the pool on close."""

    def __init__(
        self,
        conn: AsyncConn,
        pool: AsyncConnPool,
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
            return await self._conn.stream.read(n, timeout=self._read_timeout)

    def _drain_no_body_end_of_message(self) -> None:
        if self._eof or not self._no_body_response:
            return

        while True:
            event = self._conn.h11.next_event()
            if isinstance(event, h11.EndOfMessage):
                self._eof = True
                self._conn.h11.start_next_cycle()
                return
            if event is h11.NEED_DATA:
                self._ok = False
                return
            if isinstance(event, h11.Data):
                self._ok = False
                return

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration

        try:
            while True:
                event = self._conn.h11.next_event()

                if event is h11.NEED_DATA:
                    data = await self._read(DEFAULT_READ_SIZE)
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
        await self._pool.release(self._key, self._conn, reuse=reuse)


class AsyncStdNetworkHandler(AsyncBaseHandler):
    def __init__(
        self,
        *,
        transport: AsyncBaseTransport | None = None,
        ssl_context: ssl.SSLContext | None = None,
        total_timeout: float | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        max_connections_per_host: int = 10,
        max_idle_connections_per_host: int | None = None,
        max_idle_seconds: float = 30.0,
    ) -> None:
        if ssl_context is not None:
            warnings.warn(
                "The ssl_context argument is deprecated; set it through the transport argument instead",
                DeprecationWarning,
                stacklevel=2,
            )
        self.ssl_context = ssl_context or DEFAULT_SSL_CONTEXT

        self.transport = transport or AsyncIOTransport(
            ssl_context=self.ssl_context, tunnel_ssl_context=self.ssl_context
        )

        # Total timeout means: start of ahandle() until response headers received.
        self.total_timeout = total_timeout

        # Per-phase timeouts remain independently configurable.
        self.connect_timeout = connect_timeout if connect_timeout is not None else None
        self.read_timeout = read_timeout if read_timeout is not None else None
        self.write_timeout = write_timeout if write_timeout is not None else None

        self._pool = AsyncConnPool(
            max_connections_per_host=max_connections_per_host,
            max_idle_per_host=(
                max_connections_per_host if max_idle_connections_per_host is None else max_idle_connections_per_host
            ),
            max_idle_seconds=max_idle_seconds,
        )

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
        request: Request,
        scheme: str,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
    ) -> AsyncConn:
        is_secure = scheme in ("https", "wss")
        proxy_context = request.context.get("network", {}).get("proxy")
        proxy_url = proxy_context.get("url") if proxy_context is not None else None

        if proxy_url is not None:
            proxy_url = URL(proxy_url) if isinstance(proxy_url, str) else proxy_url
            connect_host = proxy_url.hostname
            connect_port = int(proxy_url.port) if proxy_url.port != "" else 80
            use_tls = proxy_url.protocol in ("https:", "wss:")
        else:
            connect_host = host
            connect_port = port
            use_tls = is_secure

        stream = await self.transport.aconnect(
            connect_host,
            connect_port,
            server_hostname=connect_host if use_tls else None,
            tls=use_tls,
            timeout=connect_timeout,
        )

        conn = AsyncConn(stream)

        if proxy_url is None:
            return conn

        assert proxy_context is not None
        if is_secure:
            target = f"{host}:{port}".encode("ascii")
            await self._send_request_headers(
                conn,
                "CONNECT",
                target,
                [("Host", get_authority_value(host, str(port)))],
            )

            status, _ = await self._receive_response_headers(conn, read_timeout=connect_timeout)

            if status < 200 or status > 299:
                await conn.close()
                raise ConnectionError(f"Proxy CONNECT failed with status {status}")

            conn.h11 = h11.Connection(h11.CLIENT)

            server_hostname = proxy_context.get("server_hostname") or host
            await conn.stream.start_tls(server_hostname=server_hostname)

        return conn

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

    async def _write_all(
        self,
        conn: AsyncConn,
        data: bytes,
        *,
        write_timeout: float | None = None,
    ) -> None:
        with map_write_exceptions():
            await conn.stream.write_all(data, timeout=write_timeout)

    async def _read(
        self,
        conn: AsyncConn,
        n: int,
        *,
        read_timeout: float | None = None,
    ) -> bytes:
        with map_read_exceptions():
            return await conn.stream.read(n, timeout=read_timeout)

    async def _send_request_headers(
        self,
        conn: AsyncConn,
        method: str,
        target: bytes,
        headers: list[tuple[str, str]],
        *,
        write_timeout: float | None = None,
    ) -> None:
        event = h11.Request(
            method=method.encode("ascii"),
            target=target,
            headers=[
                (
                    k.encode("ascii"),
                    v.encode("latin-1"),
                )
                for k, v in headers
            ],
        )
        await self._write_all(
            conn,
            conn.h11.send(event),
            write_timeout=write_timeout,
        )

    async def _send_request_body(
        self,
        conn: AsyncConn,
        body: bytes | ABCIterator[bytes] | None,
        *,
        write_timeout: float | None = None,
    ) -> None:
        if isinstance(body, bytes):
            if body:
                await self._write_all(
                    conn,
                    conn.h11.send(h11.Data(data=body)),
                    write_timeout=write_timeout,
                )
        elif isinstance(body, ABCIterator):
            for chunk in body:
                if chunk:
                    await self._write_all(
                        conn,
                        conn.h11.send(h11.Data(data=chunk)),
                        write_timeout=write_timeout,
                    )

        await self._write_all(
            conn,
            conn.h11.send(h11.EndOfMessage()),
            write_timeout=write_timeout,
        )

    async def _receive_response_headers(
        self,
        conn: AsyncConn,
        *,
        read_timeout: float | None = None,
    ) -> tuple[int, list[tuple[str, str]]]:
        while True:
            event = conn.h11.next_event()

            if event is h11.NEED_DATA:
                data = await self._read(
                    conn,
                    DEFAULT_READ_SIZE,
                    read_timeout=read_timeout,
                )
                if not data:
                    raise ConnectionError("Connection closed while reading response headers")
                conn.h11.receive_data(data)
                continue

            if isinstance(event, h11.InformationalResponse):
                if event.status_code == 101:
                    return event.status_code, [(k.decode("ascii"), v.decode("latin-1")) for k, v in event.headers]

            if isinstance(event, h11.Response):
                status = event.status_code
                resp_headers = [
                    (
                        k.decode("ascii"),
                        v.decode("latin-1"),
                    )
                    for k, v in event.headers
                ]
                return status, resp_headers

            raise ConnectionError(f"Unexpected HTTP event while reading headers: {event!r}")

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

    async def _acquire_conn_for_request(
        self,
        request: Request,
        key: PoolKey,
        scheme: str,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
    ) -> tuple[AsyncConn, bool]:
        conn = cast(AsyncConn | None, await self._pool.acquire(key))
        if conn is not None:
            return conn, True

        try:
            return (
                await self._new_conn(
                    request,
                    scheme,
                    host,
                    port,
                    connect_timeout=connect_timeout,
                ),
                False,
            )
        except BaseException:
            await self._pool.release_reservation(key)
            raise

    async def ahandle(self, request: Request) -> Response:
        total_timeout, connect_timeout, read_timeout, write_timeout = self._resolve_timeouts(request)
        deadline = None if total_timeout is None else (time.monotonic() + total_timeout)

        scheme = request.url.protocol[:-1]
        host = request.url.hostname
        port = int(request.url.port) if request.url.port != "" else (443 if scheme == "https" else 80)

        key, use_full_url = get_pool_key(request, scheme, host, port)

        def phase_timeout(value: float | None) -> float | None:
            return _min_timeout(value, self._remaining_timeout(deadline))

        conn, from_pool = await self._acquire_conn_for_request(
            request,
            key,
            scheme,
            host,
            port,
            connect_timeout=phase_timeout(connect_timeout),
        )

        if use_full_url:
            target = str(request.url).encode("ascii")
        else:
            target = _encode_target(request.url.pathname, request.url.search[1:])
        body = self._prepare_body(request)
        headers = list(request.headers.list())
        request_wants_close = _header_has_token(headers, "connection", "close")

        try:
            # When using a pooled connection, we might noticed that it was closed by the server when it was idle.
            # In that case, we need to create a new connection and retry the request once.
            try:
                await self._send_request_headers(
                    conn,
                    request.method,
                    target,
                    headers,
                    write_timeout=phase_timeout(write_timeout),
                )
            except ConnectionError:
                if not from_pool:
                    raise

                await conn.close()
                conn = await self._new_conn(
                    request,
                    scheme,
                    host,
                    port,
                    connect_timeout=phase_timeout(connect_timeout),
                )
                await self._send_request_headers(
                    conn,
                    request.method,
                    target,
                    headers,
                    write_timeout=phase_timeout(write_timeout),
                )

            await self._send_request_body(
                conn,
                body,
                write_timeout=phase_timeout(write_timeout),
            )

            status, resp_headers = await self._receive_response_headers(
                conn,
                read_timeout=phase_timeout(read_timeout),
            )

            if status == 101:
                # We won't be able to reuse this connection, so we can release the pool reservation now.
                await self._pool.release_reservation(key)
                return Response(
                    status=status,
                    headers=resp_headers,
                    content=None,
                    context={"handoff": ResponseHandoffContext(transport=conn.stream)},
                )

        except BaseException:
            await self._pool.release(key, conn, reuse=False)
            raise

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

    async def aclose(self) -> None:
        await self._pool.close_all()
