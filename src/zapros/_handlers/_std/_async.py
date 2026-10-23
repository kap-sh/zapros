from __future__ import annotations

import time
import warnings
from typing import TYPE_CHECKING, Literal, TypedDict, Union, cast, overload

import h11
from pywhatwgurl import URL

from zapros._constants import DEFAULT_READ_SIZE, default_ssl_context
from zapros._handlers._common import min_with_optionals, resolve_timeouts
from zapros._handlers._std._async_http1 import AsyncHttp1Connection
from zapros._handlers._std._async_http2 import AsyncHttp2Connection
from zapros._handlers._std._common import BrokenConnectionError, proxy_basic_auth_header, remaining_timeout_or_raise
from zapros._handlers._std._conn import AsyncHttpConnection
from zapros._io._asyncio import AsyncIOTransport
from zapros._io._base import AsyncBaseNetworkStream, AsyncBaseTransport
from zapros._io._trio import TrioTransport
from zapros._utils import get_authority_value, get_pool_key, get_port_or_default

if TYPE_CHECKING:
    import h2
else:
    try:
        import h2
    except ImportError:
        h2 = None

if TYPE_CHECKING:
    import ssl


if TYPE_CHECKING:
    from socksio import ProtocolError, socks5
else:
    try:
        from socksio import ProtocolError, socks5
    except ImportError:
        socks5 = None
        ProtocolError = None

if TYPE_CHECKING:
    import trio
else:
    try:
        import trio
    except ImportError:
        trio = None

from logging import getLogger

from typing_extensions import deprecated

from ..._async_pool import AsyncHttp1ConnectionPool, AsyncHttp2ConnectionPool
from ..._base_pool import PoolKey
from ..._errors import (
    ConnectionError,
)
from ..._models import (
    Request,
    Response,
)
from .._async_base import AsyncBaseHandler

logger = getLogger(__name__)


async def _send_connect_request(
    stream: AsyncBaseNetworkStream,
    request: Request,
    host: str,
    port: int,
    connect_timeout: float | None,
) -> None:
    """Send an HTTP CONNECT request and consume the response, raising on failure."""
    headers: list[tuple[str, str]] = [("Host", get_authority_value(host, str(port)))]
    proxy_auth = proxy_basic_auth_header(request)
    if proxy_auth is not None:
        headers.append(proxy_auth)

    h11_conn = h11.Connection(h11.CLIENT)
    req = h11.Request(
        method=b"CONNECT",
        target=f"{host}:{port}".encode("ascii"),
        headers=[(k.encode("ascii"), v.encode("latin-1")) for k, v in headers],
    )
    await stream.write_all(h11_conn.send(req), timeout=connect_timeout)

    # Pump bytes into h11 until we see a Response (or fail)
    while True:
        event = h11_conn.next_event()
        if event is h11.NEED_DATA:
            data = await stream.read(DEFAULT_READ_SIZE, timeout=connect_timeout)
            if not data:
                await stream.close()
                raise ConnectionError("Connection closed while reading CONNECT response")
            h11_conn.receive_data(data)
            continue
        if isinstance(event, h11.Response):
            if not (200 <= event.status_code <= 299):
                await stream.close()
                raise ConnectionError(f"Proxy CONNECT failed with status {event.status_code}")
            return
        await stream.close()
        raise ConnectionError(f"Unexpected HTTP event while reading CONNECT response: {event!r}")


async def _init_socks5_connection(
    stream: AsyncBaseNetworkStream,
    *,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    timeout: float | None = None,
) -> None:
    if socks5 is None:
        raise RuntimeError(
            "SOCKS5 proxy support requires the 'socksio' package. Install it with: pip install 'zapros[socks]'"
        )

    if (username is None) ^ (password is None):
        raise ValueError("username and password must be provided together")

    auth: tuple[bytes, bytes] | None = None
    if username is not None and password is not None:
        username_bytes = username.encode("utf-8")
        password_bytes = password.encode("utf-8")

        if not username_bytes or not password_bytes:
            raise ValueError(
                "username and password must be non-empty when using SOCKS5 username/password authentication"
            )
        if len(username_bytes) > 255 or len(password_bytes) > 255:
            raise ValueError("username and password must be at most 255 bytes when UTF-8 encoded")

        auth = (username_bytes, password_bytes)

    target_host = host

    conn = socks5.SOCKS5Connection()

    async def _read_exactly(num_bytes: int) -> bytes:
        buf = bytearray()
        while len(buf) < num_bytes:
            chunk = await stream.read(num_bytes - len(buf), timeout=timeout)
            if not chunk:
                raise ConnectionError("SOCKS5 proxy closed the connection during handshake")
            buf += chunk
        return bytes(buf)

    async def _read_socks5_reply_bytes() -> bytes:
        # VER, REP, RSV, ATYP
        header = await _read_exactly(4)
        atyp = header[3]

        if atyp == 0x01:  # IPv4
            addr_bytes = await _read_exactly(4)
        elif atyp == 0x03:  # DOMAINNAME
            name_len = await _read_exactly(1)
            addr_bytes = name_len + await _read_exactly(name_len[0])
        elif atyp == 0x04:  # IPv6
            addr_bytes = await _read_exactly(16)
        else:
            raise ConnectionError(f"Invalid SOCKS5 address type in reply: 0x{atyp:02x}")

        port_bytes = await _read_exactly(2)
        return header + addr_bytes + port_bytes

    auth_method = (
        socks5.SOCKS5AuthMethod.NO_AUTH_REQUIRED if auth is None else socks5.SOCKS5AuthMethod.USERNAME_PASSWORD
    )

    # Method negotiation
    conn.send(socks5.SOCKS5AuthMethodsRequest([auth_method]))  # type: ignore[reportUnknownMemberType]
    await stream.write_all(conn.data_to_send(), timeout=timeout)

    try:
        response = conn.receive_data(await _read_exactly(2))
    except ProtocolError as exc:
        raise ConnectionError("Invalid SOCKS5 auth response") from exc

    if not isinstance(response, socks5.SOCKS5AuthReply):
        raise ConnectionError("Invalid SOCKS5 auth response")

    if response.method == socks5.SOCKS5AuthMethod.NO_ACCEPTABLE_METHODS:
        raise ConnectionError("SOCKS5 proxy did not accept any offered authentication method")

    if response.method != auth_method:
        raise ConnectionError("SOCKS5 proxy rejected authentication method")

    # Username/password sub-negotiation
    if response.method == socks5.SOCKS5AuthMethod.USERNAME_PASSWORD:
        if auth is None:
            raise ConnectionError(
                "SOCKS5 proxy requested username/password authentication, but no credentials were provided"
            )

        username_bytes, password_bytes = auth
        conn.send(socks5.SOCKS5UsernamePasswordRequest(username_bytes, password_bytes))  # type: ignore[reportUnknownMemberType]
        await stream.write_all(conn.data_to_send(), timeout=timeout)

        try:
            response = conn.receive_data(await _read_exactly(2))
        except ProtocolError as exc:
            raise ConnectionError("Invalid SOCKS5 username/password response") from exc

        if not isinstance(response, socks5.SOCKS5UsernamePasswordReply):
            raise ConnectionError("Invalid SOCKS5 username/password response")
        if not response.success:
            raise ConnectionError("SOCKS5 username/password authentication failed")

    # CONNECT request
    conn.send(  # type: ignore[reportUnknownMemberType]
        socks5.SOCKS5CommandRequest.from_address(
            socks5.SOCKS5Command.CONNECT,
            (target_host, port),
        )
    )
    await stream.write_all(conn.data_to_send(), timeout=timeout)

    try:
        response = conn.receive_data(await _read_socks5_reply_bytes())
    except ProtocolError as exc:
        raise ConnectionError("Invalid SOCKS5 connect response") from exc

    if not isinstance(response, socks5.SOCKS5Reply):
        raise ConnectionError("Invalid SOCKS5 connect response")
    if response.reply_code != socks5.SOCKS5ReplyCode.SUCCEEDED:
        raise ConnectionError(f"SOCKS5 proxy connection failed with code: {response.reply_code}")


class Http1Config(TypedDict, total=False):
    max_connections_per_host: int | None
    max_idle_connections_per_host: int | None
    max_idle_seconds: float | None


class AsyncStdNetworkHandler(AsyncBaseHandler):
    @overload
    def __init__(
        self,
        *,
        transport: AsyncBaseTransport | None = None,
        ssl_context: Union[None, "ssl.SSLContext"] = None,
        total_timeout: float | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        http1: bool | Http1Config = True,
        http2: bool = False,
    ) -> None: ...
    @overload
    @deprecated(
        "max_connections_per_host, max_idle_connections_per_host, and max_idle_seconds"
        " should be set through the http1 config dict instead,"
        "e.g. AsyncStdNetworkHandler(http1={'max_connections_per_host': 20})"
    )
    def __init__(
        self,
        *,
        transport: AsyncBaseTransport | None = None,
        ssl_context: Union[None, "ssl.SSLContext"] = None,
        total_timeout: float | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        max_connections_per_host: int = 10,
        max_idle_connections_per_host: int | None = None,
        max_idle_seconds: float = 30.0,
        http1: bool | Http1Config = True,
        http2: bool = False,
    ) -> None: ...
    def __init__(
        self,
        *,
        transport: AsyncBaseTransport | None = None,
        ssl_context: Union[None, "ssl.SSLContext"] = None,
        total_timeout: float | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        max_connections_per_host: int = 10,
        max_idle_connections_per_host: int | None = None,
        max_idle_seconds: float = 30.0,
        http1: bool | Http1Config = True,
        http2: bool = False,
    ) -> None:
        if ssl_context is not None:
            warnings.warn(
                "The ssl_context argument is deprecated; set it through the transport argument instead",
                DeprecationWarning,
                stacklevel=2,
            )
        self.ssl_context = ssl_context or default_ssl_context()

        self._transport = transport

        # Total timeout means: start of ahandle() until response headers received.
        self.total_timeout = total_timeout

        # http
        self._http1 = http1
        self._http2 = http2

        if self._http2 and h2 is None:
            raise ImportError('HTTP/2 support requires the "h2" library; install with `pip install "zapros[http2]"`')

        # Per-phase timeouts remain independently configurable.
        self.connect_timeout = connect_timeout if connect_timeout is not None else None
        self.read_timeout = read_timeout if read_timeout is not None else None
        self.write_timeout = write_timeout if write_timeout is not None else None

        if not isinstance(http1, bool):
            self._http1_pool = AsyncHttp1ConnectionPool(
                max_connections_per_host=http1.get("max_connections_per_host"),
                max_idle_per_host=http1.get("max_idle_connections_per_host"),
                max_idle_seconds=http1.get("max_idle_seconds", 30.0),
            )
        else:
            self._http1_pool = AsyncHttp1ConnectionPool(
                max_connections_per_host=max_connections_per_host,
                max_idle_per_host=max_idle_connections_per_host,
                max_idle_seconds=max_idle_seconds,
            )

        self._http2_pool = AsyncHttp2ConnectionPool()

    @property
    def transport(self) -> AsyncBaseTransport:
        if self._transport is not None:
            return self._transport

        default_transport = (
            AsyncIOTransport(ssl_context=self.ssl_context)
            if not (trio and trio.lowlevel.in_trio_run())  # unasync: strip
            else TrioTransport(ssl_context=self.ssl_context)  # unasync: strip
        )
        self._transport = default_transport
        return self._transport

    async def _new_conn(
        self,
        request: Request,
        *,
        connect_timeout: float | None = None,
    ) -> AsyncHttpConnection:
        logger.debug(f"Establishing new connection for request {request.url.hostname}")
        # Target server we ultimately want to talk to
        host = request.url.hostname
        port = get_port_or_default(request.url)
        is_secure = request.url.protocol[:-1] in ("https", "wss")

        # Resolve proxy (if any) from request context
        proxy_context = request.context.get("network", {}).get("proxy")
        proxy_url = proxy_context.get("url") if proxy_context else None
        if isinstance(proxy_url, str):
            proxy_url = URL(proxy_url)

        is_socks5 = proxy_url is not None and proxy_url.protocol in ("socks5:", "socks5h:")

        # Decide the initial TCP target: either the proxy or the origin server
        if proxy_url is not None:
            connect_host = proxy_url.hostname
            connect_port = get_port_or_default(proxy_url)
            # SOCKS5 starts plaintext; HTTP proxy may itself be over TLS
            use_tls = not is_socks5 and proxy_url.protocol in ("https:", "wss:")
        else:
            connect_host = host
            connect_port = port
            use_tls = is_secure

        alpn_protocols: list[Literal["http/1.1", "h2"]] | None = None

        forward_or_tunnel = proxy_url is not None and not is_socks5
        upgrade = request.headers.get("upgrade")
        is_websocket_request = upgrade is not None and upgrade.lower() == "websocket"

        if forward_or_tunnel and not self._http1:
            raise ValueError(
                "Using an HTTP proxy requires HTTP/1.1 support in the client;"
                "enable HTTP/1.1 support or switch to a SOCKS5 proxy."
            )
        if is_websocket_request and not self._http1:
            raise ValueError("WebSocket requests require HTTP/1.1; enable HTTP/1.1 support in the client.")

        # ALPN advertises which HTTP versions we're willing to speak. Set it
        # explicitly even in single-protocol cases so a mismatched server fails
        # the handshake instead of silently falling back at the HTTP layer.
        if forward_or_tunnel or is_websocket_request:
            alpn_protocols = ["http/1.1"]
        elif self._http1 and self._http2:
            alpn_protocols = ["h2", "http/1.1"]  # h2 preferred
        elif self._http2:
            alpn_protocols = ["h2"]
        else:
            alpn_protocols = ["http/1.1"]

        logger.debug(
            f"Connecting to {connect_host}:{connect_port} with TLS={use_tls}, ALPN={alpn_protocols}, "
            f"proxy={'SOCKS5' if is_socks5 else 'HTTP' if proxy_url else 'None'}"
        )

        stream = await self.transport.aconnect(
            connect_host,
            connect_port,
            server_hostname=connect_host if use_tls else None,
            tls=use_tls,
            timeout=connect_timeout,
            alpn_protocols=alpn_protocols,
        )

        # No proxy: stream is already talking to the origin
        if proxy_url is None:
            return self._create_conn_from_stream(stream)

        # SOCKS5: negotiate then optionally wrap in TLS for the origin
        if is_socks5:
            logger.debug("Negotiating SOCKS5 proxy connection")
            await _init_socks5_connection(
                stream,
                host=host,
                port=port,
                username=proxy_url.username or None,
                password=proxy_url.password or None,
            )
            if is_secure:
                server_hostname = (proxy_context.get("server_hostname") if proxy_context else None) or host
                await stream.start_tls(server_hostname=server_hostname)
            return self._create_conn_from_stream(stream)

        # HTTP(S) proxy to plaintext origin: forward proxy, nothing more to do
        if not is_secure:
            logger.debug("Using HTTP proxy in forward mode (no CONNECT)")
            return self._create_conn_from_stream(stream)

        # HTTP(S) proxy to TLS origin: issue CONNECT, then start TLS to the origin
        logger.debug("Using HTTP proxy in tunnel mode (with CONNECT)")
        await _send_connect_request(stream, request, host, port, connect_timeout)
        server_hostname = (proxy_context.get("server_hostname") if proxy_context else None) or host
        await stream.start_tls(server_hostname=server_hostname)
        return self._create_conn_from_stream(stream)

    def _create_conn_from_stream(self, stream: AsyncBaseNetworkStream) -> AsyncHttp1Connection | AsyncHttp2Connection:
        selected_alpn = stream.selected_alpn_protocol()

        if selected_alpn == "h2":
            if not self._http2:
                raise ConnectionError("Server selected HTTP/2 via ALPN, but HTTP/2 support is disabled in the client")
            return AsyncHttp2Connection(stream)
        elif selected_alpn == "http/1.1":
            if not self._http1:
                raise ConnectionError(
                    "Server selected HTTP/1.1 via ALPN, but HTTP/1.1 support is disabled in the client"
                )
            return AsyncHttp1Connection(stream, pool=self._http1_pool)
        else:
            if self._http1:
                return AsyncHttp1Connection(stream, pool=self._http1_pool)
            elif self._http2:
                return AsyncHttp2Connection(stream)
            else:
                raise ValueError("At least one of http1 or http2 support must be enabled in the client")

    async def _acquire_conn_for_request(
        self,
        request: Request,
        key: PoolKey,
        *,
        connect_timeout: float | None = None,
    ) -> tuple[AsyncHttpConnection, bool, bool]:
        """
        Acquire a connection for the given request, either from the pool or by creating a new one.
        Returns a tuple of (connection, from_pool, is_http2).
        """

        logger.debug(f"Trying to acquire connection for {request.url.hostname} from http2 pool")
        # Fast path: existing usable HTTP/2 connection
        http2_conn = cast(AsyncHttp2Connection | None, await self._http2_pool.acquire(key))
        if http2_conn is not None:
            logger.debug(f"Acquired HTTP/2 connection for {request.url.hostname} from pool")
            return http2_conn, True, True

        # Try HTTP/1 pool
        logger.debug(f"Trying to acquire connection for {request.url.hostname} from http1 pool")
        conn = cast(AsyncHttpConnection | None, await self._http1_pool.acquire(key))
        if conn is not None:
            logger.debug(f"Acquired HTTP/1 connection for {request.url.hostname} from pool")
            return conn, True, False

        try:
            logger.debug(f"No pooled connection available for {request.url.hostname}; establishing new connection")
            conn = await self._new_conn(
                request,
                connect_timeout=connect_timeout,
            )

            is_http2 = isinstance(conn, AsyncHttp2Connection)

            if is_http2:
                logger.debug(f"Registering new HTTP/2 connection for {request.url.hostname} in pool")
                registered = cast(AsyncHttp2Connection, await self._http2_pool.register(key, conn))
                await self._http1_pool.release_reservation(key)
                if registered is not conn:
                    return registered, True, True

            return conn, False, is_http2

        except BaseException:
            await self._http1_pool.release_reservation(key)
            raise

    async def ahandle(self, request: Request) -> Response:
        total_timeout, connect_timeout, read_timeout, write_timeout = resolve_timeouts(
            request,
            total_timeout=self.total_timeout,
            connect_timeout=self.connect_timeout,
            read_timeout=self.read_timeout,
            write_timeout=self.write_timeout,
        )
        deadline = None if total_timeout is None else (time.monotonic() + total_timeout)

        key, use_full_url = get_pool_key(request)

        conn, from_pool, is_http2 = await self._acquire_conn_for_request(
            request,
            key,
            connect_timeout=min_with_optionals(connect_timeout, remaining_timeout_or_raise(deadline)),
        )

        if use_full_url:
            proxy_auth = proxy_basic_auth_header(request)
            if proxy_auth is not None:
                request.headers[proxy_auth[0]] = proxy_auth[1]

        try:
            # When using a pooled connection, we might notice that it was closed by the server when it was idle.
            # In that case, we need to create a new connection and retry the request once.
            try:
                response = await conn.send_request(
                    request,
                    read_timeout=read_timeout,
                    write_timeout=write_timeout,
                    deadline=deadline,
                )
            except BrokenConnectionError:
                if not from_pool:
                    raise

                if is_http2:
                    # discard evicts (if still installed) and closes the conn.
                    await self._http2_pool.discard(key, cast(AsyncHttp2Connection, conn))
                else:
                    await conn.aclose()

                conn = await self._new_conn(
                    request,
                    connect_timeout=min_with_optionals(connect_timeout, remaining_timeout_or_raise(deadline)),
                )

                old_is_http2 = is_http2
                is_http2 = isinstance(conn, AsyncHttp2Connection)
                if is_http2:
                    conn = cast(
                        AsyncHttp2Connection,
                        await self._http2_pool.register(key, cast(AsyncHttp2Connection, conn)),
                    )

                    if not old_is_http2:
                        # if we reserved a slot for an HTTP/1 connection but ended up with an HTTP/2 connection, release
                        # the reservation since HTTP/2 connections aren't pooled in the same way
                        await self._http1_pool.release_reservation(key)
                elif old_is_http2:
                    # if we originally haven't reserved a slot for an HTTP/1
                    # connection but ended up with one, reserve one
                    await self._http1_pool.acquire_reservation(key)

                response = await conn.send_request(
                    request,
                    read_timeout=read_timeout,
                    write_timeout=write_timeout,
                    deadline=deadline,
                )

            if response.status == 101 and not is_http2:
                # We won't be able to reuse this connection, so we can release the pool reservation now.
                await self._http1_pool.release_reservation(key)
            return response

        except BaseException:
            if not is_http2:
                await self._http1_pool.release(key, conn, reuse=False)
            else:
                await self._http2_pool.discard(key, cast(AsyncHttp2Connection, conn))
            raise

    async def aclose(self) -> None:
        await self._http1_pool.close_all()
        await self._http2_pool.close_all()
