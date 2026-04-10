from __future__ import annotations

import base64
import ssl
import time
import warnings
from collections.abc import (
    Iterator,
)
from typing import TYPE_CHECKING, cast

import h11
from pywhatwgurl import URL
from typing_extensions import override

from zapros._constants import DEFAULT_READ_SIZE, DEFAULT_SSL_CONTEXT
from zapros._io._sync import SyncTransport
from zapros._io._base import BaseNetworkStream, BaseTransport
from zapros._io._trio import TrioTransport
from zapros._utils import get_authority_value, get_pool_key

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

from .._sync_pool import ConnPool
from .._base_pool import PoolKey
from .._errors import (
    ConnectionError,
    TotalTimeoutError,
)
from .._models import (
    ClosableStream,
    Request,
    Response,
    ResponseHandoffContext,
)
from ._sync_base import BaseHandler


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


def _init_socks5_connection(
    stream: BaseNetworkStream,
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

    def _read_exactly(num_bytes: int) -> bytes:
        buf = bytearray()
        while len(buf) < num_bytes:
            chunk = stream.read(num_bytes - len(buf), timeout=timeout)
            if not chunk:
                raise ConnectionError("SOCKS5 proxy closed the connection during handshake")
            buf += chunk
        return bytes(buf)

    def _read_socks5_reply_bytes() -> bytes:
        # VER, REP, RSV, ATYP
        header = _read_exactly(4)
        atyp = header[3]

        if atyp == 0x01:  # IPv4
            addr_bytes = _read_exactly(4)
        elif atyp == 0x03:  # DOMAINNAME
            name_len = _read_exactly(1)
            addr_bytes = name_len + _read_exactly(name_len[0])
        elif atyp == 0x04:  # IPv6
            addr_bytes = _read_exactly(16)
        else:
            raise ConnectionError(f"Invalid SOCKS5 address type in reply: 0x{atyp:02x}")

        port_bytes = _read_exactly(2)
        return header + addr_bytes + port_bytes

    auth_method = (
        socks5.SOCKS5AuthMethod.NO_AUTH_REQUIRED if auth is None else socks5.SOCKS5AuthMethod.USERNAME_PASSWORD
    )

    # Method negotiation
    conn.send(socks5.SOCKS5AuthMethodsRequest([auth_method]))  # type: ignore[reportUnknownMemberType]
    stream.write_all(conn.data_to_send(), timeout=timeout)

    try:
        response = conn.receive_data(_read_exactly(2))
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
        stream.write_all(conn.data_to_send(), timeout=timeout)

        try:
            response = conn.receive_data(_read_exactly(2))
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
    stream.write_all(conn.data_to_send(), timeout=timeout)

    try:
        response = conn.receive_data(_read_socks5_reply_bytes())
    except ProtocolError as exc:
        raise ConnectionError("Invalid SOCKS5 connect response") from exc

    if not isinstance(response, socks5.SOCKS5Reply):
        raise ConnectionError("Invalid SOCKS5 connect response")
    if response.reply_code != socks5.SOCKS5ReplyCode.SUCCEEDED:
        raise ConnectionError(f"SOCKS5 proxy connection failed with code: {response.reply_code}")


class Conn:
    def __init__(
        self,
        stream: BaseNetworkStream,
    ) -> None:
        self.stream = stream
        self.h11 = h11.Connection(h11.CLIENT)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.stream.close()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def can_reuse(self) -> bool:
        return not self.is_closed and self.h11.our_state is h11.IDLE and self.h11.their_state is h11.IDLE


class StdStream(ClosableStream):
    """Wrap an h11 response stream and return the connection to the pool on close."""

    def __init__(
        self,
        conn: Conn,
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

    def __iter__(self) -> StdStream:
        return self

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

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration

        try:
            while True:
                event = self._conn.h11.next_event()

                if event is h11.NEED_DATA:
                    data = self._conn.stream.read(DEFAULT_READ_SIZE, timeout=self._read_timeout)
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
                    self.close()
                    raise StopIteration

        except BaseException:
            self._ok = False
            self.close()
            raise

    @override
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._no_body_response and not self._eof and self._ok:
            try:
                self._drain_no_body_end_of_message()
            except Exception:
                self._ok = False

        reuse = self._eof and self._ok and not self._must_close and self._conn.can_reuse()
        self._pool.release(self._key, self._conn, reuse=reuse)


class StdNetworkHandler(BaseHandler):
    def __init__(
        self,
        *,
        transport: BaseTransport | None = None,
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

        self._transport = transport

        # Total timeout means: start of handle() until response headers received.
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
    def _remaining_timeout(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TotalTimeoutError("Operation timed out")
        return remaining

    @property
    def transport(self) -> BaseTransport:
        if self._transport is not None:
            return self._transport

        default_transport = (
            SyncTransport(ssl_context=self.ssl_context)
        )
        self._transport = default_transport
        return self._transport

    def _new_conn(
        self,
        request: Request,
        scheme: str,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
    ) -> Conn:
        is_secure = scheme in ("https", "wss")
        proxy_context = request.context.get("network", {}).get("proxy")
        proxy_url = proxy_context.get("url") if proxy_context is not None else None

        if proxy_url is not None:
            proxy_url = URL(proxy_url) if isinstance(proxy_url, str) else proxy_url
            is_socks5 = proxy_url.protocol in ("socks5:", "socks5h:")

            if is_socks5:
                connect_host = proxy_url.hostname
                connect_port = int(proxy_url.port) if proxy_url.port != "" else 1080
                use_tls = False
            else:
                connect_host = proxy_url.hostname
                connect_port = int(proxy_url.port) if proxy_url.port != "" else 80
                use_tls = proxy_url.protocol in ("https:", "wss:")
        else:
            connect_host = host
            connect_port = port
            use_tls = is_secure

        stream = self.transport.connect(
            connect_host,
            connect_port,
            server_hostname=connect_host if use_tls else None,
            tls=use_tls,
            timeout=connect_timeout,
        )

        if proxy_url is not None and proxy_url.protocol in ("socks5:", "socks5h:"):
            _init_socks5_connection(
                stream,
                host=host,
                port=port,
                username=proxy_url.username or None,
                password=proxy_url.password or None,
            )

            if is_secure:
                server_hostname = proxy_context.get("server_hostname") if proxy_context else None
                server_hostname = server_hostname or host
                stream.start_tls(server_hostname=server_hostname)

        conn = Conn(stream)

        if proxy_url is None:
            return conn

        assert proxy_context is not None

        if proxy_url.protocol in ("socks5:", "socks5h:"):
            return conn

        if is_secure:
            target = f"{host}:{port}".encode("ascii")
            connect_headers = [("Host", get_authority_value(host, str(port)))]

            if proxy_url.username or proxy_url.password:
                username = proxy_url.username or ""
                password = proxy_url.password or ""
                credentials = f"{username}:{password}".encode("utf-8")
                auth_value = base64.b64encode(credentials).decode("ascii")
                connect_headers.append(("Proxy-Authorization", f"Basic {auth_value}"))

            self._send_request_headers(
                conn,
                "CONNECT",
                target,
                connect_headers,
            )

            status, _ = self._receive_response_headers(conn, read_timeout=connect_timeout)

            if status < 200 or status > 299:
                conn.close()
                raise ConnectionError(f"Proxy CONNECT failed with status {status}")

            conn.h11 = h11.Connection(h11.CLIENT)

            server_hostname = proxy_context.get("server_hostname") or host
            conn.stream.start_tls(server_hostname=server_hostname)

        return conn

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

    def _send_request_headers(
        self,
        conn: Conn,
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
        conn.stream.write_all(
            conn.h11.send(event),
            timeout=write_timeout,
        )

    def _send_request_body(
        self,
        conn: Conn,
        body: bytes | Iterator[bytes] | None,
        *,
        write_timeout: float | None = None,
    ) -> None:
        if isinstance(body, bytes):
            if body:
                conn.stream.write_all(
                    conn.h11.send(h11.Data(data=body)),
                    timeout=write_timeout,
                )
        elif isinstance(body, Iterator):
            for chunk in body:
                if chunk:
                    conn.stream.write_all(
                        conn.h11.send(h11.Data(data=chunk)),
                        timeout=write_timeout,
                    )
        elif body is None:
            pass
        else:
            raise TypeError(f"Unsupported body type: {body.__class__.__name__}")
        conn.stream.write_all(
            conn.h11.send(h11.EndOfMessage()),
            timeout=write_timeout,
        )

    def _receive_response_headers(
        self,
        conn: Conn,
        *,
        read_timeout: float | None = None,
    ) -> tuple[int, list[tuple[str, str]]]:
        while True:
            event = conn.h11.next_event()

            if event is h11.NEED_DATA:
                data = conn.stream.read(DEFAULT_READ_SIZE, timeout=read_timeout)
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

    def _acquire_conn_for_request(
        self,
        request: Request,
        key: PoolKey,
        scheme: str,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
    ) -> tuple[Conn, bool]:
        conn = cast(Conn | None, self._pool.acquire(key))
        if conn is not None:
            return conn, True

        try:
            return (
                self._new_conn(
                    request,
                    scheme,
                    host,
                    port,
                    connect_timeout=connect_timeout,
                ),
                False,
            )
        except BaseException:
            self._pool.release_reservation(key)
            raise

    def handle(self, request: Request) -> Response:
        total_timeout, connect_timeout, read_timeout, write_timeout = self._resolve_timeouts(request)
        deadline = None if total_timeout is None else (time.monotonic() + total_timeout)

        scheme = request.url.protocol[:-1]
        host = request.url.hostname
        port = int(request.url.port) if request.url.port != "" else (443 if scheme == "https" else 80)

        key, use_full_url = get_pool_key(request, scheme, host, port)

        def phase_timeout(value: float | None) -> float | None:
            return _min_timeout(value, self._remaining_timeout(deadline))

        conn, from_pool = self._acquire_conn_for_request(
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
        headers = list(request.headers.list())

        proxy_context = request.context.get("network", {}).get("proxy")
        if use_full_url and proxy_context is not None:
            proxy_url_value = proxy_context.get("url")
            if proxy_url_value is not None:
                proxy_url = URL(proxy_url_value) if isinstance(proxy_url_value, str) else proxy_url_value
                if proxy_url.username or proxy_url.password:
                    import base64

                    username = proxy_url.username or ""
                    password = proxy_url.password or ""
                    credentials = f"{username}:{password}".encode("utf-8")
                    auth_value = base64.b64encode(credentials).decode("ascii")
                    headers.append(("Proxy-Authorization", f"Basic {auth_value}"))

        request_wants_close = _header_has_token(headers, "connection", "close")

        try:
            # When using a pooled connection, we might noticed that it was closed by the server when it was idle.
            # In that case, we need to create a new connection and retry the request once.
            try:
                self._send_request_headers(
                    conn,
                    request.method,
                    target,
                    headers,
                    write_timeout=phase_timeout(write_timeout),
                )
            except ConnectionError:
                if not from_pool:
                    raise

                conn.close()
                conn = self._new_conn(
                    request,
                    scheme,
                    host,
                    port,
                    connect_timeout=phase_timeout(connect_timeout),
                )
                self._send_request_headers(
                    conn,
                    request.method,
                    target,
                    headers,
                    write_timeout=phase_timeout(write_timeout),
                )

            if not isinstance(request.body, (bytes, Iterator)) and request.body is not None:
                raise TypeError(f"Unsupported body type: {request.body.__class__.__name__}")

            self._send_request_body(
                conn,
                request.body,
                write_timeout=phase_timeout(write_timeout),
            )

            status, resp_headers = self._receive_response_headers(
                conn,
                read_timeout=phase_timeout(read_timeout),
            )

            if status == 101:
                # We won't be able to reuse this connection, so we can release the pool reservation now.
                self._pool.release_reservation(key)
                return Response(
                    status=status,
                    headers=resp_headers,
                    content=None,
                    context={"handoff": ResponseHandoffContext(network_stream=conn.stream)},
                )

        except BaseException:
            self._pool.release(key, conn, reuse=False)
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
            content=StdStream(
                conn,
                self._pool,
                key,
                read_timeout=read_timeout,
                no_body_response=no_body_response,
                must_close=(request_wants_close or response_wants_close),
            ),
        )

    def close(self) -> None:
        self._pool.close_all()
