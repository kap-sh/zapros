from __future__ import annotations

import socket
import ssl
import threading
import time
from collections import deque
from collections.abc import (
    Iterator as ABCIterator,
)
from dataclasses import dataclass, field
from typing import TypeVar

import h11
from typing_extensions import override

from .._errors import (
    ConnectionError,
    PoolTimeoutError,
    TotalTimeoutError,
)
from .._models import (
    ClosableStream,
    Request,
    Response,
)
from ._exc_map import map_connect_exceptions, map_read_exceptions, map_write_exceptions
from ._sync_base import BaseHandler

PoolKey = tuple[str, str, int]  # (scheme, host, port)
_T = TypeVar("_T")


def _encode_target(path: str, query: str) -> bytes:
    """Encode an already-prepared request target without rewriting semantics."""
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


class SyncConn:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.h11 = h11.Connection(h11.CLIENT)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def set_timeout(self, timeout: float | None) -> None:
        self.sock.settimeout(timeout)

    def recv(
        self,
        n: int,
        *,
        timeout: float | None = None,
    ) -> bytes:
        self.set_timeout(timeout)
        return self.sock.recv(n)

    def sendall(
        self,
        data: bytes,
        *,
        timeout: float | None = None,
    ) -> None:
        self.set_timeout(timeout)
        self.sock.sendall(data)


@dataclass
class IdleConn:
    conn: SyncConn
    last_used: float = field(default_factory=time.monotonic)


class ConnPool:
    """Sync connection pool keyed by (scheme, host, port).

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

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._idle: dict[PoolKey, deque[IdleConn]] = {}
        self._acquired: dict[PoolKey, int] = {}
        self._closed = False

    def acquire(
        self,
        key: PoolKey,
        *,
        timeout: float | None = None,
    ) -> SyncConn | None:
        """Reserve a slot and return the freshest usable idle connection, if any."""
        deadline = None if timeout is None else (time.monotonic() + timeout)

        with self._cond:
            while True:
                if self._closed:
                    raise RuntimeError("Pool is closed")

                acquired = self._acquired.get(key, 0)
                if acquired < self._max_connections_per_host:
                    self._acquired[key] = acquired + 1
                    break

                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PoolTimeoutError("Timed out waiting for connection pool slot")
                    self._cond.wait(remaining)

            now = time.monotonic()
            dq = self._idle.get(key)
            if not dq:
                return None

            while dq:
                item = dq.pop()  # LIFO – reuse the freshest
                if (now - item.last_used) <= self._max_age and not item.conn.is_closed:
                    return item.conn
                _close_quietly(item.conn)

            return None

    def release(
        self,
        key: PoolKey,
        conn: SyncConn,
        *,
        reuse: bool,
    ) -> None:
        """Return a connection and release its reserved slot."""
        with self._cond:
            try:
                if not reuse or self._closed:
                    _close_quietly(conn)
                else:
                    dq = self._idle.setdefault(key, deque())
                    dq.append(IdleConn(conn=conn))

                    while len(dq) > self._max_idle_per_host:
                        _close_quietly(dq.popleft().conn)
            finally:
                self._acquired[key] = max(
                    0,
                    self._acquired.get(key, 1) - 1,
                )
                self._cond.notify()

    def close_all(self) -> None:
        with self._cond:
            if self._closed:
                return
            self._closed = True
            idle, self._idle = (
                self._idle,
                {},
            )
            self._cond.notify_all()

        for dq in idle.values():
            for item in dq:
                _close_quietly(item.conn)


def _close_quietly(
    conn: SyncConn,
) -> None:
    try:
        conn.close()
    except Exception:
        pass


class StdStream(ClosableStream):
    """Wrap an h11 response stream and return the connection to the pool on close."""

    def __init__(
        self,
        conn: SyncConn,
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

    def __iter__(
        self,
    ) -> ABCIterator[bytes]:
        return self

    def _read(self, n: int) -> bytes:
        with map_read_exceptions():
            return self._conn.recv(
                n,
                timeout=self._read_timeout,
            )

    def _drain_no_body_end_of_message(
        self,
    ) -> None:
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
            if isinstance(event, (h11.Data, h11.ConnectionClosed)):
                self._ok = False
                return

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration

        try:
            with map_read_exceptions():
                while True:
                    event = self._conn.h11.next_event()

                    if event is h11.NEED_DATA:
                        data = self._read(8192)
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

                    if isinstance(event, h11.ConnectionClosed):
                        self._ok = False
                        self.close()
                        raise ConnectionError("Connection closed before response body completed")

        except Exception:
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

        reuse = (
            self._eof
            and self._ok
            and not self._must_close
            and not self._conn.is_closed
            and self._conn.h11.our_state is h11.IDLE
            and self._conn.h11.their_state is h11.IDLE
        )

        self._pool.release(
            self._key,
            self._conn,
            reuse=reuse,
        )


class StdNetworkHandler(BaseHandler):
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
    def _remaining_timeout(
        deadline: float | None,
    ) -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TotalTimeoutError("Operation timed out")
        return remaining

    def _new_conn(
        self,
        scheme: str,
        host: str,
        port: int,
        *,
        connect_timeout: float | None = None,
    ) -> SyncConn:
        with map_connect_exceptions():
            raw_sock = socket.create_connection(
                (host, port),
                timeout=connect_timeout,
            )
        try:
            if scheme == "https":
                raw_sock = self.ssl_context.wrap_socket(
                    raw_sock,
                    server_hostname=host,
                )
            raw_sock.settimeout(None)
            return SyncConn(raw_sock)
        except Exception:
            raw_sock.close()
            raise

    @staticmethod
    def _prepare_body(
        request: Request,
    ) -> bytes | ABCIterator[bytes] | None:
        if request.body is None:
            return None
        if isinstance(
            request.body,
            (bytes, ABCIterator),
        ):
            return request.body
        raise NotImplementedError("Streaming request bodies must be synchronous iterators")

    @staticmethod
    def _response_has_no_body(
        method: str,
        status: int,
        headers: list[tuple[str, str]],
    ) -> bool:
        if method.upper() == "HEAD":
            return True
        if status in (204, 304):
            return True
        for k, v in headers:
            if k.lower() == "content-length" and v.strip() == "0":
                return True
        return False

    @staticmethod
    def _release_drained_no_body_response(
        conn: SyncConn,
        pool: ConnPool,
        key: PoolKey,
        *,
        must_close: bool,
    ) -> None:
        ok = True
        eof = False

        try:
            while True:
                event = conn.h11.next_event()

                if isinstance(event, h11.EndOfMessage):
                    eof = True
                    conn.h11.start_next_cycle()
                    break

                if event is h11.NEED_DATA or isinstance(event, (h11.Data, h11.ConnectionClosed)):
                    ok = False
                    break
        except Exception:
            ok = False

        reuse = (
            eof
            and ok
            and not must_close
            and not conn.is_closed
            and conn.h11.our_state is h11.IDLE
            and conn.h11.their_state is h11.IDLE
        )
        pool.release(key, conn, reuse=reuse)
        return None

    def _write_all(
        self,
        conn: SyncConn,
        data: bytes,
        *,
        write_timeout: float | None = None,
    ) -> None:
        with map_write_exceptions():
            conn.sendall(
                data,
                timeout=write_timeout,
            )

    def _read(
        self,
        conn: SyncConn,
        n: int,
        *,
        read_timeout: float | None = None,
    ) -> bytes:
        with map_read_exceptions():
            return conn.recv(n, timeout=read_timeout)

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

    def handle(self, request: Request) -> Response:
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

        conn = self._pool.acquire(
            key,
            timeout=self._remaining_timeout(deadline),
        )
        if conn is None:
            conn = self._new_conn(
                request.url.protocol[:-1],
                request.url.hostname,
                port,
                connect_timeout=_min_timeout(
                    connect_timeout,
                    self._remaining_timeout(deadline),
                ),
            )

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
                self._write_all(
                    conn,
                    conn.h11.send(event),
                    write_timeout=_min_timeout(
                        write_timeout,
                        self._remaining_timeout(deadline),
                    ),
                )

                if isinstance(body, bytes):
                    if body:
                        self._write_all(
                            conn,
                            conn.h11.send(h11.Data(data=body)),
                            write_timeout=_min_timeout(
                                write_timeout,
                                self._remaining_timeout(deadline),
                            ),
                        )
                elif isinstance(body, ABCIterator):
                    for chunk in body:
                        if chunk:
                            self._write_all(
                                conn,
                                conn.h11.send(h11.Data(data=chunk)),
                                write_timeout=_min_timeout(
                                    write_timeout,
                                    self._remaining_timeout(deadline),
                                ),
                            )

                self._write_all(
                    conn,
                    conn.h11.send(h11.EndOfMessage()),
                    write_timeout=_min_timeout(
                        write_timeout,
                        self._remaining_timeout(deadline),
                    ),
                )

                while True:
                    event = conn.h11.next_event()

                    if event is h11.NEED_DATA:
                        data = self._read(
                            conn,
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
            must_close = request_wants_close or response_wants_close

            if no_body_response:
                content = self._release_drained_no_body_response(
                    conn,
                    self._pool,
                    key,
                    must_close=must_close,
                )
            else:
                content = StdStream(
                    conn,
                    self._pool,
                    key,
                    read_timeout=read_timeout,
                    no_body_response=False,
                    must_close=must_close,
                )

            return Response(
                status=status,
                headers=resp_headers,
                content=content,
            )

        except Exception:
            self._pool.release(key, conn, reuse=False)
            raise

    def close(self) -> None:
        self._pool.close_all()
