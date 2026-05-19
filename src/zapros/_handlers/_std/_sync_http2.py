from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, Iterator, Callable, Union, cast

if TYPE_CHECKING:
    import h2
    import h2.config
    import h2.connection
    import h2.errors
    import h2.events
    import h2.exceptions
    from h2.events import (
        AlternativeServiceAvailable,
        ConnectionTerminated,
        DataReceived,
        InformationalResponseReceived,
        PingAckReceived,
        PingReceived,
        PushedStreamReceived,
        RemoteSettingsChanged,
        ResponseReceived,
        SettingsAcknowledged,
        StreamEnded,
        StreamReset,
        TrailersReceived,
        UnknownFrameReceived,
        WindowUpdated,
    )
    from h2.settings import SettingCodes
else:
    try:
        import h2
        import h2.config
        import h2.connection
        import h2.errors
        import h2.events
        import h2.exceptions
        from h2.events import (
            AlternativeServiceAvailable,
            ConnectionTerminated,
            DataReceived,
            InformationalResponseReceived,
            PingAckReceived,
            PingReceived,
            PushedStreamReceived,
            RemoteSettingsChanged,
            ResponseReceived,
            SettingsAcknowledged,
            StreamEnded,
            StreamReset,
            TrailersReceived,
            UnknownFrameReceived,
            WindowUpdated,
        )
        from h2.settings import SettingCodes
    except ImportError:
        h2 = None
from typing_extensions import TypeIs, override

from threading import Lock
from zapros._constants import DEFAULT_READ_SIZE
from zapros._errors import ConnectionError
from zapros._handlers._common import min_with_optionals
from zapros._handlers._std._common import StreamLimiter, BrokenConnectionError, remaining_timeout_or_raise
from zapros._io._base import BaseNetworkStream
from zapros._models import ClosableStream, Request, Response
from zapros._typing import is_async_iterator
from zapros._utils import get_host_header_value

from ._conn import HttpConnection

_FORBIDDEN_H2_HEADERS = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-connection",
        "transfer-encoding",
        "upgrade",
    }
)


H2StreamEvent = Union[
    "ResponseReceived",
    "InformationalResponseReceived",
    "TrailersReceived",
    "DataReceived",
    "StreamEnded",
    "StreamReset",
    "WindowUpdated",
]

H2ConnectionEvent = Union[
    "RemoteSettingsChanged",
    "SettingsAcknowledged",
    "PingReceived",
    "PingAckReceived",
    "ConnectionTerminated",
    "PushedStreamReceived",
    "AlternativeServiceAvailable",
    "UnknownFrameReceived",
    "WindowUpdated",
]

logger = getLogger(__name__)


def is_h2_connection_event(event: "h2.events.Event") -> TypeIs["H2ConnectionEvent"]:
    # WindowUpdated with stream_id == 0 is connection-level; otherwise stream-level.
    if isinstance(event, WindowUpdated):
        return event.stream_id == 0
    return isinstance(
        event,
        (
            RemoteSettingsChanged,
            SettingsAcknowledged,
            PingReceived,
            PingAckReceived,
            ConnectionTerminated,
            PushedStreamReceived,
            AlternativeServiceAvailable,
            UnknownFrameReceived,
        ),
    )


H2Event = H2StreamEvent | H2ConnectionEvent


def _iter_single(data: bytes) -> Iterator[bytes]:
    yield data


def _build_h2_headers(request: Request) -> list[tuple[bytes, bytes]]:
    scheme = request.url.protocol[:-1]
    path = f"{request.url.pathname}{request.url.search}" or "/"
    authority = get_host_header_value(request.url)

    pseudo: list[tuple[bytes, bytes]] = [
        (b":method", request.method.encode("ascii")),
        (b":scheme", scheme.encode("ascii")),
        (b":authority", authority.encode("ascii")),
        (b":path", path.encode("ascii")),
    ]
    user: list[tuple[bytes, bytes]] = []
    for k, v in request.headers.list():
        lk = k.lower()
        if lk in _FORBIDDEN_H2_HEADERS:
            continue
        if lk == "te" and v.lower() != "trailers":
            continue
        user.append((lk.encode("ascii"), v.encode("latin-1")))

    return pseudo + user


class Http2Connection(HttpConnection):
    """
    Locking discipline
    ------------------
    Three locks, strictly ordered: _read_lock -> _state_lock -> _write_lock.
    A coroutine may acquire later locks while holding earlier ones, but never
    the reverse. Locks are released as early as possible.

      * _state_lock protects ALL access to the `self.h2` object and to
        `self._events`. Every h2 call (send_*, receive_data, get_next_available_stream_id,
        acknowledge_received_data, reset_stream, end_stream, data_to_send, ...) MUST
        be made while holding this lock.
      * _write_lock serializes socket writes. It does NOT protect h2 state; we
        always drain `data_to_send()` into a local bytes object under _state_lock,
        release _state_lock, then take _write_lock to push the bytes out.
      * _read_lock ensures only one coroutine reads from the socket at a time.
        Other coroutines block on _read_lock until the current reader returns.
        Callers waiting on a specific stream pass `stream_id` to _receive_events;
        after acquiring _read_lock the helper re-checks that stream's queue under
        _state_lock and returns without reading if the previous reader already
        demuxed events into it.
      * _init_lock guards one-shot initiate_connection().
    """

    def __init__(
        self,
        stream: BaseNetworkStream,
    ) -> None:

        if h2 is None:
            raise ImportError('h2 library is required for HTTP/2 support; install with `pip install "zapros[http2]"`')

        self._stream = stream

        self.h2 = h2.connection.H2Connection(
            config=h2.config.H2Configuration(
                client_side=True,
                header_encoding=None,
            )
        )

        self._init_lock = Lock()
        self._read_lock = Lock()
        self.state_lock = Lock()
        self._write_lock = Lock()

        self._is_initialized = False
        self._closed = False
        self._connection_terminated = False

        self.events: dict[int, list[H2StreamEvent]] = {}

        # Caps in-flight streams to the peer's SETTINGS_MAX_CONCURRENT_STREAMS.
        # Refreshed from RemoteSettingsChanged; 100 matches the common server
        # default while we wait for the peer's first SETTINGS frame.
        self.stream_limiter = StreamLimiter(limit=100)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def can_handle_request(self) -> bool:
        return not self._closed and not self._connection_terminated

    def send_request(
        self,
        request: Request,
        *,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> Response:
        self._ensure_initialized(write_timeout=write_timeout, deadline=deadline)

        has_body = request.body is not None and request.body != b""

        stream_id = self._allocate_stream_and_send_headers(
            request,
            has_body=has_body,
            write_timeout=write_timeout,
            deadline=deadline,
        )

        try:
            if has_body:
                assert not is_async_iterator(request.body) and request.body is not None
                self._send_request_body(
                    request.body,
                    stream_id,
                    read_timeout=read_timeout,
                    write_timeout=write_timeout,
                    deadline=deadline,
                )

            status, resp_headers = self._receive_response_headers(
                stream_id,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                deadline=deadline,
            )
        except BaseException:
            # Reset the stream on abandonment so the peer stops sending and our
            # flow-control window is reclaimed.
            self.reset_stream(stream_id, write_timeout=write_timeout, deadline=deadline)
            raise

        return Response(
            status=status,
            headers=resp_headers,
            content=Http2ResponseStream(self, stream_id, read_timeout=read_timeout),
            context={
                "network": {
                    "http_protocol": "HTTP/2",
                }
            },
            request=request,
        )

    def close(self) -> None:
        with self.state_lock:
            if self._closed:
                return
            self._closed = True
            self._connection_terminated = True
        self.stream_limiter.fail_all()
        try:
            self._stream.close()
        except Exception:
            pass

    def _ensure_initialized(
        self,
        *,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> None:
        logger.debug("Ensuring HTTP/2 connection is initialized")

        if self._connection_terminated:
            raise ConnectionError("HTTP/2 connection terminated by peer")
        if self._is_initialized:
            return
        with self._init_lock:
            if self._is_initialized:
                return
            if self._connection_terminated:
                raise ConnectionError("HTTP/2 connection terminated by peer")

            logger.debug("Waiting to acquire h2 connection lock for initialization")
            with self.state_lock:
                self.h2.initiate_connection()
                data = self.h2.data_to_send()
            if data:
                logger.debug("Waiting to acquire socket write lock to send initial SETTINGS frame")
                with self._write_lock:
                    try:
                        self._stream.write_all(
                            data,
                            timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                        )
                        logger.debug("Initial SETTINGS frame sent, HTTP/2 connection is initialized")
                    except BaseException:
                        self._connection_terminated = True
                        raise
            self._is_initialized = True

    def _allocate_stream_and_send_headers(
        self,
        request: Request,
        *,
        has_body: bool,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> int:
        headers = _build_h2_headers(request)
        stream_id: int | None = None
        self.stream_limiter.acquire()
        try:
            with self.state_lock:
                try:
                    stream_id = self.h2.get_next_available_stream_id()
                except h2.exceptions.NoAvailableStreamIDError as e:
                    # Stream IDs exhausted; the connection is unusable for new requests.
                    self._connection_terminated = True
                    raise ConnectionError("HTTP/2 connection has no available stream ids") from e
                self.events[stream_id] = []
                self.h2.send_headers(stream_id, headers, end_stream=not has_body)
                data = self.h2.data_to_send()
            if data:
                with self._write_lock:
                    self._stream.write_all(
                        data,
                        timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                    )
        except BaseException as err:
            # If we raise after creating the event queue, the caller never sees
            # `stream_id`, so we must drop the queue and release the permit
            # here. Otherwise just release the permit.
            if stream_id is not None:
                with self.state_lock:
                    self.events.pop(stream_id, None)
            self.stream_limiter.release()
            raise BrokenConnectionError("Failed to send HTTP/2 request headers") from err

        return stream_id

    def _try_send_data_chunk(
        self,
        stream_id: int,
        chunk: bytes,
        offset: int,
    ) -> tuple[int, bytes]:
        """Atomically (under _state_lock): observe the current flow-control
        window for `stream_id`, and if positive, hand as much of
        `chunk[offset:]` as fits to h2.send_data. Returns the new offset and
        any bytes h2 wants written to the socket.

        Returns (offset, b"") with offset unchanged if the window is currently
        zero — caller should then drive _receive_events and retry. Raises
        ConnectionError if the stream is closed (locally or by peer RST) or
        the connection terminates.

        Lock discipline: takes _state_lock only.
        """
        with self.state_lock:
            if self._connection_terminated:
                raise ConnectionError("HTTP/2 connection terminated by peer")

            try:
                window = self.h2.local_flow_control_window(stream_id)
                if window <= 0:
                    return offset, b""

                take = min(window, self.h2.max_outbound_frame_size, len(chunk) - offset)
                piece = chunk[offset : offset + take]
                self.h2.send_data(stream_id, piece)
                return offset + take, self.h2.data_to_send()
            except h2.exceptions.StreamClosedError as e:
                raise ConnectionError(f"HTTP/2 stream {stream_id} is closed") from e

    def _send_request_body(
        self,
        body: bytes | Iterator[bytes],
        stream_id: int,
        *,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> None:
        chunks: Iterator[bytes] = _iter_single(body) if isinstance(body, bytes) else body

        for chunk in chunks:
            # Each iteration of _try_send_data_chunk observes the current
            # flow-control window AND max_outbound_frame_size under the state
            # lock and sends at most that much. `chunk` may be arbitrarily
            # large; we slice it out in window/frame-sized pieces, waiting
            # for WINDOW_UPDATE frames as needed.
            offset = 0
            while offset < len(chunk):
                new_offset, data = self._try_send_data_chunk(stream_id, chunk, offset)
                if new_offset == offset:
                    self._receive_events(
                        read_timeout=read_timeout,
                        write_timeout=write_timeout,
                        deadline=deadline,
                        is_satisfied=lambda: self.h2.local_flow_control_window(stream_id) > 0,
                    )
                    continue
                offset = new_offset
                if data:
                    with self._write_lock:
                        self._stream.write_all(
                            data,
                            timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                        )

        with self.state_lock:
            self.h2.end_stream(stream_id)
            data = self.h2.data_to_send()
        if data:
            with self._write_lock:
                self._stream.write_all(
                    data,
                    timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                )

    def reset_stream(
        self,
        stream_id: int,
        *,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> None:
        data: bytes = b""
        with self.state_lock:
            # A non-None pop means we are the call that finalises this stream
            # and must release its concurrency permit.
            had_events = self.events.pop(stream_id, None) is not None
            if not self._connection_terminated:
                try:
                    self.h2.reset_stream(stream_id, error_code=h2.errors.ErrorCodes.CANCEL)
                    data = self.h2.data_to_send()
                except (h2.exceptions.StreamClosedError, h2.exceptions.ProtocolError):
                    pass
        if had_events:
            self.stream_limiter.release()
        if data:
            try:
                with self._write_lock:
                    self._stream.write_all(
                        data,
                        timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                    )
            except Exception:
                # Best-effort: if writing RST_STREAM fails, swallow — the caller's
                # original exception (if any) is more important.
                pass

    def _receive_events(
        self,
        *,
        is_satisfied: Callable[[], bool] | None = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> None:
        """
        Read one chunk from the socket and dispatch events. Caller must NOT hold
        any of our locks. At most one coroutine runs the read at a time
        (guarded by _read_lock).

        If `is_satisfied` is given, it is invoked under _state_lock after
        _read_lock is acquired; returning True skips the read — the previous
        reader already did the work this caller was waiting for.
        """
        with self._read_lock:
            with self.state_lock:
                if self._connection_terminated:
                    raise ConnectionError("HTTP/2 connection terminated by peer")
                if is_satisfied is not None and is_satisfied():
                    return

            data = self._stream.read(
                DEFAULT_READ_SIZE,
                timeout=min_with_optionals(read_timeout, remaining_timeout_or_raise(deadline)),
            )

            outgoing: bytes = b""
            new_max_concurrent_streams: int | None = None
            terminated_now = False
            with self.state_lock:
                if not data:
                    if not self._connection_terminated:
                        self._connection_terminated = True
                        terminated_now = True
                else:
                    events = cast(list[H2Event], self.h2.receive_data(data))
                    for event in events:
                        if is_h2_connection_event(event):
                            # TODO: handle other connection-level events
                            match event:
                                case ConnectionTerminated():
                                    if not self._connection_terminated:
                                        self._connection_terminated = True
                                        terminated_now = True
                                case RemoteSettingsChanged():
                                    changed = event.changed_settings.get(SettingCodes.MAX_CONCURRENT_STREAMS)
                                    if changed is not None:
                                        new_max_concurrent_streams = changed.new_value
                                case _:
                                    pass
                            continue

                        sid = event.stream_id
                        queue = self.events.get(sid)
                        if queue is not None:
                            queue.append(event)

                        if isinstance(event, DataReceived):
                            amount = event.flow_controlled_length
                            if amount:
                                self.h2.acknowledge_received_data(amount, sid)

                    outgoing = self.h2.data_to_send()

            if terminated_now:
                self.stream_limiter.fail_all()

            if new_max_concurrent_streams is not None:
                self.stream_limiter.update_limit(new_max_concurrent_streams)

            if outgoing:
                with self._write_lock:
                    self._stream.write_all(
                        outgoing,
                        timeout=min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline)),
                    )

            if not data:
                raise ConnectionError("HTTP/2 connection closed by peer")

    def receive_stream_event(
        self,
        stream_id: int,
        *,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> h2.events.Event:
        while True:
            with self.state_lock:
                queue = self.events.get(stream_id)
                if queue:
                    return queue.pop(0)
                if queue is None:
                    # Our queue was removed (stream reset/closed locally).
                    raise ConnectionError(f"HTTP/2 stream {stream_id} is closed")
                if self._connection_terminated:
                    raise ConnectionError("HTTP/2 connection terminated by peer")
            self._receive_events(
                is_satisfied=lambda: bool(self.events.get(stream_id)),
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                deadline=deadline,
            )

    def _receive_response_headers(
        self,
        stream_id: int,
        *,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> tuple[int, list[tuple[str, str]]]:
        while True:
            event = self.receive_stream_event(
                stream_id,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                deadline=deadline,
            )
            if isinstance(event, h2.events.ResponseReceived):
                break
            if isinstance(event, h2.events.InformationalResponseReceived):
                # 1xx (e.g. 103 Early Hints) — keep waiting for the final response.
                continue
            if isinstance(event, h2.events.StreamReset):
                raise ConnectionError(f"HTTP/2 stream {stream_id} reset: {event.error_code}")
            if isinstance(event, h2.events.StreamEnded):
                raise ConnectionError(f"HTTP/2 stream {stream_id} ended before response headers")
            # WindowUpdated or other stream events before headers — ignore.

        status = 0
        headers: list[tuple[str, str]] = []
        assert event.headers is not None
        for k, v in event.headers:
            if k == b":status":
                status = int(v.decode("ascii"))
            elif not k.startswith(b":"):
                headers.append((k.decode("ascii"), v.decode("latin-1")))

        if status == 0:
            raise ConnectionError("HTTP/2 response missing :status pseudo-header")

        return status, headers


class Http2ResponseStream(ClosableStream):
    def __init__(
        self,
        conn: Http2Connection,
        stream_id: int,
        *,
        read_timeout: float | None = None,
    ) -> None:
        self._conn = conn
        self._stream_id = stream_id
        self._read_timeout = read_timeout
        self._closed = False
        self._stream_ended = False

    def __iter__(self) -> Http2ResponseStream:
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        while True:
            event = self._conn.receive_stream_event(
                self._stream_id,
                read_timeout=self._read_timeout,
            )
            if isinstance(event, h2.events.DataReceived):
                if event.data:
                    return bytes(event.data)
                continue
            if isinstance(event, h2.events.StreamEnded):
                self._stream_ended = True
                self.close()
                raise StopIteration
            if isinstance(event, h2.events.StreamReset):
                self.close()
                raise ConnectionError(f"HTTP/2 stream {self._stream_id} reset: {event.error_code}")
            # Ignore trailers, window updates, etc. and loop for more data.

    @override
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stream_ended:
            # Stream already finished cleanly; drop our queue and release the
            # concurrency permit if we are the call that actually removed it.
            with self._conn.state_lock:
                had_events = self._conn.events.pop(self._stream_id, None) is not None
            if had_events:
                self._conn.stream_limiter.release()
        else:
            # Caller is abandoning a still-open stream — send RST_STREAM
            # (reset_stream releases the permit on our behalf).
            self._conn.reset_stream(self._stream_id)
