from __future__ import annotations

import time
import warnings
from typing import TYPE_CHECKING, Union, cast

import h11
from pywhatwgurl import URL

from zapros._constants import DEFAULT_READ_SIZE, default_ssl_context
from zapros._handlers._common import min_with_optionals, resolve_timeouts
from zapros._handlers._std._async_http1 import AsyncHttp1Connection
from zapros._handlers._std._common import BrokenConnectionError, proxy_basic_auth_header, remaining_timeout_or_raise
from zapros._handlers._std._conn import AsyncHttpConnection
from zapros._io._asyncio import AsyncIOTransport
from zapros._io._base import AsyncBaseNetworkStream, AsyncBaseTransport
from zapros._io._trio import TrioTransport
from zapros._utils import get_authority_value, get_pool_key, get_port_or_default

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

from ..._async_pool import AsyncConnPool
from ..._base_pool import PoolKey
from ..._errors import (
    ConnectionError,
)
from ..._models import (
    Request,
    Response,
)
from .._async_base import AsyncBaseHandler


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


class AsyncStdNetworkHandler(AsyncBaseHandler):
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
        scheme = request.url.protocol[:-1]
        host = request.url.hostname
        port = get_port_or_default(request.url)
        is_secure = scheme in ("https", "wss")

        proxy_context = request.context.get("network", {}).get("proxy")
        proxy_url = proxy_context.get("url") if proxy_context is not None else None

        if proxy_url is not None:
            proxy_url = URL(proxy_url) if isinstance(proxy_url, str) else proxy_url
            is_socks5 = proxy_url.protocol in ("socks5:", "socks5h:")

            connect_host = proxy_url.hostname
            connect_port = get_port_or_default(proxy_url)
            use_tls = False if is_socks5 else proxy_url.protocol in ("https:", "wss:")
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

        if proxy_url is not None and proxy_url.protocol in ("socks5:", "socks5h:"):
            await _init_socks5_connection(
                stream,
                host=host,
                port=port,
                username=proxy_url.username or None,
                password=proxy_url.password or None,
            )

            if is_secure:
                server_hostname = proxy_context.get("server_hostname") if proxy_context else None
                server_hostname = server_hostname or host
                await stream.start_tls(server_hostname=server_hostname)

        if proxy_url is None:
            return AsyncHttp1Connection(stream)

        assert proxy_context is not None

        if proxy_url.protocol in ("socks5:", "socks5h:"):
            return AsyncHttp1Connection(stream)

        if is_secure:
            target = f"{host}:{port}".encode("ascii")
            connect_headers: list[tuple[str, str]] = [("Host", get_authority_value(host, str(port)))]

            proxy_auth = proxy_basic_auth_header(request)
            if proxy_auth is not None:
                connect_headers.append(proxy_auth)

            h11_conn = h11.Connection(h11.CLIENT)
            request_event = h11.Request(
                method=b"CONNECT",
                target=target,
                headers=[(k.encode("ascii"), v.encode("latin-1")) for k, v in connect_headers],
            )
            await stream.write_all(h11_conn.send(request_event), timeout=connect_timeout)

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
                    status = event.status_code
                    break
                await stream.close()
                raise ConnectionError(f"Unexpected HTTP event while reading CONNECT response: {event!r}")

            if status < 200 or status > 299:
                await stream.close()
                raise ConnectionError(f"Proxy CONNECT failed with status {status}")

            server_hostname = proxy_context.get("server_hostname") or host
            await stream.start_tls(server_hostname=server_hostname)

        return AsyncHttp1Connection(stream)

    async def _acquire_conn_for_request(
        self,
        request: Request,
        key: PoolKey,
        *,
        connect_timeout: float | None = None,
    ) -> tuple[AsyncHttpConnection, bool]:
        conn = cast(AsyncHttpConnection | None, await self._pool.acquire(key))
        if conn is not None:
            return conn, True

        try:
            return (
                await self._new_conn(
                    request,
                    connect_timeout=connect_timeout,
                ),
                False,
            )
        except BaseException:
            await self._pool.release_reservation(key)
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

        conn, from_pool = await self._acquire_conn_for_request(
            request,
            key,
            connect_timeout=min_with_optionals(connect_timeout, remaining_timeout_or_raise(deadline)),
        )

        if use_full_url:
            proxy_auth = proxy_basic_auth_header(request)
            if proxy_auth is not None:
                request.headers[proxy_auth[0]] = proxy_auth[1]

        try:
            # When using a pooled connection, we might noticed that it was closed by the server when it was idle.
            # In that case, we need to create a new connection and retry the request once.
            try:
                response = await conn.send_request(
                    request,
                    read_timeout=read_timeout,
                    write_timeout=write_timeout,
                    deadline=deadline,
                    conn_pool=self._pool,
                )
            except BrokenConnectionError:
                if not from_pool:
                    raise

                await conn.close()
                conn = await self._new_conn(
                    request,
                    connect_timeout=min_with_optionals(connect_timeout, remaining_timeout_or_raise(deadline)),
                )
                response = await conn.send_request(
                    request,
                    read_timeout=read_timeout,
                    write_timeout=write_timeout,
                    deadline=deadline,
                    conn_pool=self._pool,
                )

            if response.status == 101:
                # We won't be able to reuse this connection, so we can release the pool reservation now.
                await self._pool.release_reservation(key)
            return response

        except BaseException:
            await self._pool.release(key, conn, reuse=False)
            raise

    async def aclose(self) -> None:
        await self._pool.close_all()
