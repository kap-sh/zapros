from __future__ import annotations

from typing import Iterator

import h11
from typing_extensions import override

from zapros._sync_pool import ConnPool
from zapros._base_pool import PoolKey
from zapros._constants import DEFAULT_READ_SIZE
from zapros._errors import ConnectionError, WriteError
from zapros._handlers._common import min_with_optionals
from zapros._handlers._std._common import connection_wants_close, remaining_timeout_or_raise, response_has_no_body
from zapros._handlers._std._conn import HttpConnection, BrokenConnectionError
from zapros._io._base import BaseNetworkStream
from zapros._models import ClosableStream, Request, Response, ResponseHandoffContext
from zapros._utils import get_pool_key


class Http1ResponseStream(ClosableStream):
    """
    Byte stream over an h11 response body, with pooled connection lifecycle.

    Wraps an :class:`Http1Connection` whose h11 state machine is positioned just after
    the response headers have been read. Iterating the stream pulls ``h11.Data``
    events, transparently reading more bytes from the underlying transport when
    h11 signals ``NEED_DATA``. Iteration ends when h11 emits ``EndOfMessage``,
    at which point the stream closes itself and releases the connection back to
    the pool.

    Connection reuse is conditional. The connection is only returned to the
    pool in a reusable state when **all** of the following hold:

    * the response body was fully consumed (``EndOfMessage`` was reached),
    * no exception interrupted iteration,
    * the caller did not request ``must_close`` (e.g. ``Connection: close``),
    * h11 successfully transitioned to the next request/response cycle, and
    * the connection itself reports it can be reused.

    Otherwise the connection is released as non-reusable and the pool will
    discard it. Any exception during iteration marks the connection unusable before being re-raised, so a cancelled or
    failed read never leaves a half-read response in the pool.

    The ``no_body_response`` flag handles responses that are semantically
    bodyless (e.g. ``HEAD`` requests, ``204``/``304`` status codes) but where
    h11 still needs to see ``EndOfMessage`` to advance its state machine. When
    set, ``close()`` will drain any pending end-of-message event so the
    connection can be reused without the caller having to iterate.

    Args:
        conn: The pooled connection wrapping both the transport stream and the
            h11 state machine.
        pool: The pool to release ``conn`` back to on close.
        key: Pool key for releasing the connection.
        read_timeout: Per-read timeout in seconds passed to the underlying
            transport. ``None`` disables the timeout.
        no_body_response: Set when the response is known to have no body. See
            the class docstring for details on how this affects ``close()``.
        must_close: If ``True``, the connection will not be reused even on a
            clean read. Use this when the response or request semantics require
            closing (e.g. ``Connection: close``, HTTP/1.0 without keep-alive).
    """

    def __init__(
        self,
        conn: Http1Connection,
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

    def __iter__(self) -> Http1ResponseStream:
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
            # We want to catch CancelledError and other exceptions to ensure the
            # connection is properly closed and not returned to the pool in a bad state.
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

        reuse = self._eof and self._ok and not self._must_close and self._conn.can_handle_request()
        self._pool.release(self._key, self._conn, reuse=reuse)


class Http1Connection(HttpConnection):
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

    def can_handle_request(self) -> bool:
        return not self.is_closed and self.h11.our_state is h11.IDLE and self.h11.their_state is h11.IDLE

    def send_request(
        self,
        request: Request,
        *,
        conn_pool: ConnPool,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> Response:

        key, use_full_url = get_pool_key(request)

        target = str(request.url) if use_full_url else f"{request.url.pathname}{request.url.search}"

        request_headers_list = request.headers.list()

        try:
            self._send_request_headers(
                method=request.method,
                target=target.encode("ascii"),
                headers=request_headers_list,
                write_timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
            )
        except WriteError as e:
            raise BrokenConnectionError() from e

        if request.body is not None and not isinstance(request.body, (bytes, Iterator)):
            raise TypeError(f"Unsupported body type: {request.body.__class__.__name__}")

        self._send_request_body(
            body=request.body,
            write_timeout=write_timeout,
            deadline=deadline,
        )

        status, resp_headers = self._receive_response_headers(
            read_timeout=min_with_optionals(read_timeout, remaining_timeout_or_raise(deadline)),
        )

        if status == 101:
            # h11 reads in DEFAULT_READ_SIZE chunks, so any bytes the peer sent
            # immediately after the 101 (e.g. WebSocket frames) are sitting in
            # h11's buffer rather than on the socket. Hand them to the caller
            # so it can re-inject them into the upgraded protocol parser.
            trailing_data, _ = self.h11.trailing_data
            return Response(
                status=status,
                headers=resp_headers,
                content=None,
                context={
                    "handoff": ResponseHandoffContext(
                        network_stream=self.stream,
                        trailing_data=bytes(trailing_data),
                    )
                },
            )
        return Response(
            status=status,
            headers=resp_headers,
            content=Http1ResponseStream(
                self,
                pool=conn_pool,
                key=key,
                read_timeout=read_timeout,
                no_body_response=response_has_no_body(request.method, status),
                must_close=connection_wants_close(request_headers_list) or connection_wants_close(resp_headers),
            ),
        )

    def _send_request_headers(
        self,
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
        self.stream.write_all(
            self.h11.send(event),
            timeout=write_timeout,
        )

    def _send_request_body(
        self,
        body: bytes | Iterator[bytes] | None,
        *,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> None:
        if isinstance(body, bytes):
            if body:
                self.stream.write_all(
                    self.h11.send(h11.Data(data=body)),
                    timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                )
        elif isinstance(body, Iterator):
            for chunk in body:
                if chunk:
                    self.stream.write_all(
                        self.h11.send(h11.Data(data=chunk)),
                        timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                    )
        elif body is None:
            pass
        else:
            raise TypeError(f"Unsupported body type: {body.__class__.__name__}")
        self.stream.write_all(
            self.h11.send(h11.EndOfMessage()),
            timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
        )

    def _receive_response_headers(
        self,
        *,
        read_timeout: float | None = None,
    ) -> tuple[int, list[tuple[str, str]]]:
        while True:
            event = self.h11.next_event()

            if event is h11.NEED_DATA:
                data = self.stream.read(DEFAULT_READ_SIZE, timeout=read_timeout)
                if not data:
                    raise ConnectionError("Connection closed while reading response headers")
                self.h11.receive_data(data)
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
