from __future__ import annotations

import asyncio
import contextvars
import math
from typing import TYPE_CHECKING, Any, AsyncGenerator, AsyncIterator, Callable, Coroutine, Union

if TYPE_CHECKING:
    import anyio
    import h2
    import h2.config
    import h2.connection
    import h2.errors
    import h2.events
    import h2.exceptions
    from h2.events import (
        ConnectionTerminated,
        DataReceived,
        InformationalResponseReceived,
        ResponseReceived,
        StreamEnded,
        StreamReset,
    )
    from h2.settings import SettingCodes, Settings
else:
    try:
        import anyio
        import h2
        import h2.config
        import h2.connection
        import h2.errors
        import h2.events
        import h2.exceptions
        from h2.events import (
            ConnectionTerminated,
            DataReceived,
            InformationalResponseReceived,
            ResponseReceived,
            StreamEnded,
            StreamReset,
        )
        from h2.settings import SettingCodes, Settings
    except ImportError:
        h2 = None

if TYPE_CHECKING:
    import trio
else:
    try:
        import trio
    except ImportError:
        trio = None

from typing_extensions import override

from zapros._constants import DEFAULT_READ_SIZE
from zapros._errors import ConnectionError, ReadTimeoutError, TotalTimeoutError, WriteTimeoutError
from zapros._handlers._common import min_with_optionals
from zapros._handlers._std._common import BrokenConnectionError, remaining_timeout_or_raise
from zapros._io._base import AsyncBaseNetworkStream
from zapros._models import AsyncClosableStream, Headers, Request, Response
from zapros._utils import get_host_header_value

from ._conn import AsyncHttpConnection

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

# Receive windows. Response data is acknowledged only as the reader consumes it, so a
# stream's window caps how much unread data it buffers, and how much the peer can send
# on it per round trip. The connection window holds several stream windows, so one
# response nobody reads can't stall the others.
_STREAM_RECEIVE_WINDOW = 2**22
_CONNECTION_RECEIVE_WINDOW = 2**24

# Request body data a pump queues before waiting for it to be written: enough to
# save writes, little enough not to hold up other streams' frames for long.
_SEND_BATCH = 2**16

# The events a response reader acts on; the worker drops all others.
H2StreamEvent = Union[
    "ResponseReceived",
    "InformationalResponseReceived",
    "DataReceived",
    "StreamEnded",
    "StreamReset",
]


# The event loop holds tasks only weakly; keep detached ones alive until they finish.
_background_tasks: set[asyncio.Task[None]] = set()


def _spawn(func: Callable[..., Coroutine[Any, Any, None]], *args: object) -> None:
    """
    Run `func(*args)` in a task outside any task group, so a connection can be
    opened and closed from any task. `func` must not raise; it is stopped through
    its own cancel scope.
    """
    if trio is not None and trio.lowlevel.in_trio_run():
        # Like asyncio tasks, run in a copy of the caller's context.
        trio.lowlevel.spawn_system_task(func, *args, context=contextvars.copy_context())
    else:
        task = asyncio.get_running_loop().create_task(func(*args))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def _aiter_single(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _build_h2_headers(request: Request) -> list[tuple[bytes, bytes]]:
    scheme = request.url.protocol[:-1]
    path = f"{request.url.pathname}{request.url.search}" or "/"
    # Honor a caller-set Host (e.g. when connecting by IP), as HTTP/1.1 does.
    authority = request.headers.get("host") or get_host_header_value(request.url)

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

    # Announce the trailer fields known at this point; a streaming body may add more later.
    if request.trailers and "trailer" not in request.headers:
        user.append((b"trailer", ", ".join(request.trailers).encode("ascii")))

    return pseudo + user


class H2Stream:
    """State of one stream, shared by the worker, the body pump and the response reader."""

    def __init__(self, stream_id: int) -> None:
        self.id = stream_id
        self.send_events, self.receive_events = anyio.create_memory_object_stream[H2StreamEvent](math.inf)
        # Raised to the response reader once it has drained the events received before the failure.
        self.error: Exception | None = None
        # Flow-controlled bytes queued for the reader and not yet acknowledged to the peer.
        self.unacked = 0
        # Nothing more may be sent: the stream was reset by either side, or the connection died.
        self.stopped = False
        self.pump_scope = anyio.CancelScope()
        # The connection releases the stream once both are done.
        self.pump_running = False
        self.response_done = False

    def stop(self) -> None:
        self.stopped = True
        self.pump_scope.cancel()

    def fail(self, error: Exception) -> None:
        self.stop()
        if self.error is None:
            self.error = error
        self.send_events.close()

    async def receive(self, timeout: float | None) -> H2StreamEvent:
        try:
            with anyio.fail_after(timeout):
                return await self.receive_events.receive()
        except anyio.EndOfStream:
            assert self.error is not None
            raise self.error
        except TimeoutError as e:
            raise ReadTimeoutError("Timed out waiting for HTTP/2 response data") from e


class AsyncBidirectionalHttp2Connection(AsyncHttpConnection):
    """
    Experimental full-duplex HTTP/2 connection, used with `http2_bidirectional_experimental=True`.

    Concurrency model
    -----------------
    Two tasks, started with the connection, own the socket. The worker is the
    only reader: it feeds received bytes to `self.h2` and dispatches stream
    events into each stream's channel. The writer is the only writer: it sends
    whatever `self.h2` has queued, in order. Request bodies are sent by a pump
    task per stream, so a response can be read while its request body is
    still being sent.

    `self.h2` calls never await, so they are atomic with respect to other
    tasks and need no lock. Other tasks only queue frames in `self.h2` and
    wake the writer; those that need backpressure then wait for the write
    (see `_flush`). Cancelling them never cuts a write short.

    Tasks waiting for a write, a flow-control window or a free stream slot
    sleep on `_changed`, which fires after every write, after every batch of
    received frames, when a stream is released, and when the connection
    terminates.
    """

    def __init__(
        self,
        stream: AsyncBaseNetworkStream,
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
        # Must be set before the preface, which carries them.
        self.h2.local_settings = Settings(
            client=True,
            initial_values={
                SettingCodes.ENABLE_PUSH: 0,
                SettingCodes.INITIAL_WINDOW_SIZE: _STREAM_RECEIVE_WINDOW,
                SettingCodes.MAX_HEADER_LIST_SIZE: self.h2.DEFAULT_MAX_HEADER_LIST_SIZE,
            },
        )
        # h2 includes it by default, and some servers reject the preface because of it.
        del self.h2.local_settings[SettingCodes.ENABLE_CONNECT_PROTOCOL]
        # The preface stays queued in h2 until the first flush, usually the first request's HEADERS.
        self.h2.initiate_connection()
        self.h2.increment_flow_control_window(_CONNECTION_RECEIVE_WINDOW)

        self._changed = anyio.Event()
        self._worker_scope = anyio.CancelScope()
        self._writer_scope = anyio.CancelScope()
        # Set when there are frames for the writer to send.
        self._send_pending = anyio.Event()
        # Batches of queued frames the writer has taken from h2, and finished writing.
        self._batches_taken = 0
        self._batches_sent = 0

        self._closed = False
        self._no_stream_ids = False
        # Set once the connection is unusable; every pending and future stream fails with it.
        self._error: str | None = None

        self.streams: dict[int, H2Stream] = {}

        _spawn(self._run_worker)
        _spawn(self._run_writer)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def can_handle_request(self) -> bool:
        return self._error is None and not self._no_stream_ids

    async def send_request(
        self,
        request: Request,
        *,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> Response:
        headers = _build_h2_headers(request)
        body = b"" if request.body is None else request.body
        assert isinstance(body, (bytes, AsyncIterator))
        # Trailers are sent in a final HEADERS frame, so they need the pump even without a body.
        needs_pump = body != b"" or request.trailers is not None

        try:
            with anyio.fail_after(remaining_timeout_or_raise(deadline)):
                while self._error is None and len(self.streams) >= self._max_concurrent_streams():
                    await self._changed.wait()
        except TimeoutError as e:
            raise TotalTimeoutError("Timed out waiting for a free HTTP/2 stream") from e
        if self._error is not None:
            raise ConnectionError(self._error)

        # Computed before queueing HEADERS, so a deadline error can't leave them queued.
        timeout = min_with_optionals(write_timeout, remaining_timeout_or_raise(deadline))

        try:
            stream_id = self.h2.get_next_available_stream_id()
        except h2.exceptions.NoAvailableStreamIDError as e:
            # Stream IDs exhausted; the connection is unusable for new requests.
            self._no_stream_ids = True
            raise ConnectionError("HTTP/2 connection has no available stream ids") from e
        stream = H2Stream(stream_id)
        self.streams[stream_id] = stream

        try:
            self.h2.send_headers(stream_id, headers, end_stream=not needs_pump)
            try:
                await self._flush(timeout)
            except Exception as e:
                raise BrokenConnectionError("Failed to send HTTP/2 request headers") from e

            if needs_pump:
                stream.pump_running = True
                _spawn(
                    self._pump_request_body,
                    stream,
                    body,
                    request.trailers,
                    write_timeout,
                )

            status, resp_headers = await self._receive_response_headers(
                stream,
                read_timeout=read_timeout,
                deadline=deadline,
            )
        except BaseException:
            # Reset the stream on abandonment so the peer stops sending and our
            # flow-control window is reclaimed.
            self.reset_stream(stream)
            raise

        return Response(
            status=status,
            headers=resp_headers,
            content=AsyncBidirectionalHttp2ResponseStream(self, stream, read_timeout=read_timeout),
            context={
                "network": {
                    "http_protocol": "HTTP/2",
                }
            },
            request=request,
        )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._terminate("HTTP/2 connection closed")
        try:
            await self._stream.close()
        except Exception:
            pass

    def _max_concurrent_streams(self) -> int:
        # Until the peer's SETTINGS say otherwise, assume the common server default of 100.
        return self.h2.remote_settings.get(SettingCodes.MAX_CONCURRENT_STREAMS, 100)

    async def _pump_request_body(
        self,
        stream: H2Stream,
        body: bytes | AsyncIterator[bytes],
        trailers: Headers | None,
        write_timeout: float | None,
    ) -> None:
        chunks: AsyncIterator[bytes] = _aiter_single(body) if isinstance(body, bytes) else body
        try:
            with stream.pump_scope:
                async for chunk in chunks:
                    # `chunk` may be arbitrarily large; we slice it out in
                    # window/frame-sized pieces, waiting for WINDOW_UPDATE
                    # frames as needed.
                    offset = 0
                    while offset < len(chunk):
                        if stream.stopped:
                            return
                        window = self.h2.local_flow_control_window(stream.id)
                        if window <= 0:
                            await self._wait_for_change(write_timeout)
                            continue
                        # Queue up to a batch of frames, then wait for the writer to send them together.
                        end = offset + min(window, _SEND_BATCH, len(chunk) - offset)
                        while offset < end:
                            take = min(self.h2.max_outbound_frame_size, end - offset)
                            self.h2.send_data(stream.id, chunk[offset : offset + take])
                            offset += take
                        await self._flush(write_timeout)

                self._send_end_stream(stream.id, trailers)
                await self._flush(write_timeout)
        except Exception as exc:
            # Once stopped, errors (e.g. StreamClosedError after a peer reset) are expected.
            if not stream.stopped:
                stream.fail(exc)
                self._send_reset(stream)
        finally:
            stream.pump_running = False
            self._maybe_release(stream)
            # Let a body abandoned midway clean up; a no-op once it has been sent in full.
            if isinstance(chunks, AsyncGenerator):
                try:
                    await chunks.aclose()
                except Exception:
                    pass

    def _send_end_stream(self, stream_id: int, trailers: Headers | None) -> None:
        # Read trailers only now: a streaming body may have populated them.
        if trailers:
            self.h2.send_headers(
                stream_id,
                [(k.lower().encode("ascii"), v.encode("latin-1")) for k, v in trailers.list()],
                end_stream=True,
            )
        else:
            self.h2.end_stream(stream_id)

    def _wake_writer(self) -> None:
        self._send_pending.set()

    async def _flush(self, timeout: float | None = None) -> None:
        """Wake the writer and wait until it has sent the frames queued so far."""
        # They go out with the next batch the writer takes.
        batch = self._batches_taken + 1
        self._wake_writer()
        try:
            with anyio.fail_after(timeout):
                while self._batches_sent < batch:
                    if self._error is not None:
                        raise ConnectionError(self._error)
                    await self._changed.wait()
        except TimeoutError as e:
            # The socket is stuck for every stream, not just this one.
            self._terminate("HTTP/2 connection write timed out")
            raise WriteTimeoutError("Timed out writing to the HTTP/2 connection") from e

    async def _wait_for_change(self, timeout: float | None) -> None:
        try:
            with anyio.fail_after(timeout):
                await self._changed.wait()
        except TimeoutError as e:
            raise WriteTimeoutError("Timed out waiting for HTTP/2 flow-control window") from e

    def _notify(self) -> None:
        self._changed.set()
        self._changed = anyio.Event()

    def _terminate(self, message: str) -> None:
        if self._error is not None:
            return
        self._error = message
        for stream in self.streams.values():
            stream.fail(ConnectionError(message))
        self._worker_scope.cancel()
        self._writer_scope.cancel()
        self._notify()

    def _send_reset(self, stream: H2Stream) -> None:
        # Best-effort: the stream may already be closed, or the connection dead.
        try:
            self.h2.reset_stream(stream.id, error_code=h2.errors.ErrorCodes.CANCEL)
            self._wake_writer()
        except Exception:
            pass

    def _maybe_release(self, stream: H2Stream) -> None:
        if stream.pump_running or not stream.response_done:
            return
        if self.streams.pop(stream.id, None) is not None:
            stream.send_events.close()
            stream.receive_events.close()
            self._notify()

    async def _run_worker(self) -> None:
        with self._worker_scope:
            try:
                while True:
                    data = await self._stream.read(DEFAULT_READ_SIZE)
                    if not data:
                        self._terminate("HTTP/2 connection closed by peer")
                        break
                    self._dispatch_events(self.h2.receive_data(data))
                    self._notify()
                    # Send what h2 queued in reply, e.g. acknowledgements of SETTINGS and PING.
                    self._wake_writer()
            except Exception as exc:
                # Must not raise: nothing awaits this task, and under trio an error would crash the whole run.
                self._terminate(f"HTTP/2 connection failed: {exc}")
        # The connection is dead: free the socket now rather than when the pool next looks at it.
        await self.aclose()

    async def _run_writer(self) -> None:
        with self._writer_scope:
            try:
                while True:
                    await self._send_pending.wait()
                    self._send_pending = anyio.Event()
                    self._batches_taken += 1
                    data = self.h2.data_to_send()
                    if data:
                        await self._stream.write_all(data)
                    self._batches_sent += 1
                    self._notify()
            except Exception as exc:
                # Must not raise, for the same reason as the worker.
                self._terminate(f"HTTP/2 connection write failed: {exc}")

    def _dispatch_events(self, events: list[h2.events.Event]) -> None:
        for event in events:
            # TODO: handle other connection-level events
            if isinstance(event, ConnectionTerminated):
                self._terminate("HTTP/2 connection terminated by peer")
                return
            if not isinstance(
                event, (ResponseReceived, InformationalResponseReceived, DataReceived, StreamEnded, StreamReset)
            ):
                continue

            stream = self.streams.get(event.stream_id)
            if stream is not None and isinstance(event, StreamReset):
                # The peer accepts no more data on this stream. A reset with
                # NO_ERROR after a complete response still leaves the response
                # readable from the queue.
                stream.stop()

            if stream is None or stream.error is not None or stream.response_done:
                # No reader will consume this event, so give back the window its data took.
                if isinstance(event, DataReceived):
                    self._ack(event.stream_id, event.flow_controlled_length)
                continue
            if isinstance(event, DataReceived):
                stream.unacked += event.flow_controlled_length
            stream.send_events.send_nowait(event)

    def _ack(self, stream_id: int, length: int) -> None:
        if length and self._error is None:
            self.h2.acknowledge_received_data(length, stream_id)

    def consume(self, stream: H2Stream, length: int) -> None:
        """Acknowledge response data the reader has taken, letting the peer send more."""
        if not length:
            return
        # Doesn't wait for the write: a reader cancelled after taking the data would lose it.
        stream.unacked -= length
        self._ack(stream.id, length)
        self._wake_writer()

    def reset_stream(self, stream: H2Stream) -> None:
        stream.response_done = True
        stream.stop()
        self._maybe_release(stream)
        # The reader is gone: give back the window held by data it never read.
        self._ack(stream.id, stream.unacked)
        stream.unacked = 0
        self._send_reset(stream)

    def finish_response(self, stream: H2Stream) -> None:
        stream.response_done = True
        self._maybe_release(stream)

    async def _receive_response_headers(
        self,
        stream: H2Stream,
        *,
        read_timeout: float | None = None,
        deadline: float | None = None,
    ) -> tuple[int, list[tuple[str, str]]]:
        while True:
            event = await stream.receive(min_with_optionals(read_timeout, remaining_timeout_or_raise(deadline)))
            if isinstance(event, ResponseReceived):
                break
            if isinstance(event, InformationalResponseReceived):
                # 1xx (e.g. 103 Early Hints) — keep waiting for the final response.
                continue
            if isinstance(event, StreamReset):
                raise ConnectionError(f"HTTP/2 stream {stream.id} reset: {event.error_code}")
            if isinstance(event, StreamEnded):
                raise ConnectionError(f"HTTP/2 stream {stream.id} ended before response headers")

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


class AsyncBidirectionalHttp2ResponseStream(AsyncClosableStream):
    def __init__(
        self,
        conn: AsyncBidirectionalHttp2Connection,
        stream: H2Stream,
        *,
        read_timeout: float | None = None,
    ) -> None:
        self._conn = conn
        self._stream = stream
        self._read_timeout = read_timeout
        self._closed = False
        self._stream_ended = False

    def __aiter__(self) -> AsyncBidirectionalHttp2ResponseStream:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        while True:
            event = await self._stream.receive(self._read_timeout)
            if isinstance(event, DataReceived):
                self._conn.consume(self._stream, event.flow_controlled_length)
                if event.data:
                    return bytes(event.data)
                continue
            if isinstance(event, StreamEnded):
                self._stream_ended = True
                await self.aclose()
                raise StopAsyncIteration
            if isinstance(event, StreamReset):
                await self.aclose()
                raise ConnectionError(f"HTTP/2 stream {self._stream.id} reset: {event.error_code}")

    @override
    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stream_ended:
            # The response finished cleanly; the stream is released once the
            # request body (if still being sent) is done too.
            self._conn.finish_response(self._stream)
        else:
            # Caller is abandoning a still-open stream — send RST_STREAM.
            self._conn.reset_stream(self._stream)
