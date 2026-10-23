from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Literal

import anyio
import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.settings
import hpack
import hyperframe.frame
import pytest
from pywhatwgurl import URL

from tests.dual_stream import DualStream
from zapros import AsyncClient, AsyncStdNetworkHandler
from zapros._errors import (
    ConnectionError as ZaprosConnectionError,
    ReadTimeoutError,
    TotalTimeoutError,
    WriteTimeoutError,
)
from zapros._handlers._std._async_http2_bidirectional import (
    _SEND_BATCH,
    _STREAM_RECEIVE_WINDOW,
    AsyncBidirectionalHttp2Connection,
)
from zapros._io._base import AsyncBaseNetworkStream
from zapros._models import Headers, Request
from zapros._utils import get_pool_key


class AsyncMockStream(AsyncBaseNetworkStream):
    """Serves `buffer`, then whatever `feed` adds, as the server's frames; otherwise idles like an open connection.

    Reads wait for the client's first write: a real server can't answer a
    request it hasn't seen, and h2 rejects frames for streams not opened yet.
    """

    def __init__(self, buffer: list[bytes]) -> None:
        self._buffer = list(buffer)
        self._request_sent = anyio.Event()
        self._fed = anyio.Event()
        self.closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        await self._request_sent.wait()
        while not self._buffer:
            self._fed = anyio.Event()
            await self._fed.wait()
        return self._buffer.pop(0)

    def feed(self, data: bytes) -> None:
        self._buffer.append(data)
        self._fed.set()

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        self._request_sent.set()
        return len(data)

    async def close(self) -> None:
        self.closed = True


@asynccontextmanager
async def _connection(stream: AsyncBaseNetworkStream) -> AsyncIterator[AsyncBidirectionalHttp2Connection]:
    conn = AsyncBidirectionalHttp2Connection(stream)
    try:
        yield conn
    finally:
        await conn.aclose()


def _encode_headers(headers: list[tuple[bytes, bytes]]) -> bytes:
    return hpack.Encoder().encode(headers)


def _headers_frame(stream_id: int) -> bytes:
    return hyperframe.frame.HeadersFrame(
        stream_id=stream_id,
        data=_encode_headers([(b":status", b"200")]),
        flags=["END_HEADERS"],
    ).serialize()


def _data_frame(stream_id: int, data: bytes, *, end_stream: bool = False) -> bytes:
    flags = ["END_STREAM"] if end_stream else []
    return hyperframe.frame.DataFrame(stream_id=stream_id, data=data, flags=flags).serialize()


def _ok_response_frames(
    stream_id: int = 1,
    body: bytes = b"Hello, world!",
) -> list[bytes]:
    return [
        hyperframe.frame.SettingsFrame().serialize(),
        hyperframe.frame.HeadersFrame(
            stream_id=stream_id,
            data=_encode_headers([(b":status", b"200"), (b"content-type", b"text/plain")]),
            flags=["END_HEADERS"],
        ).serialize(),
        hyperframe.frame.DataFrame(stream_id=stream_id, data=body, flags=["END_STREAM"]).serialize(),
    ]


async def test_http2_get_returns_status_and_body() -> None:
    stream = AsyncMockStream(_ok_response_frames())
    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://example.com/"), "GET"))

        assert response.status == 200
        assert dict(response.headers.list())["content-type"] == "text/plain"
        assert await response.aread() == b"Hello, world!"


async def test_http2_post_with_body_completes() -> None:
    stream = AsyncMockStream(_ok_response_frames())
    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=b'{"data":"upload"}'))

        assert response.status == 200
        assert await response.aread() == b"Hello, world!"


async def test_http2_post_with_dual_iterator_body_completes() -> None:
    stream = AsyncMockStream(_ok_response_frames())
    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=DualStream(b"upload")))

        assert response.status == 200
        assert await response.aread() == b"Hello, world!"


async def test_http2_stream_reset_raises_before_headers() -> None:
    stream = AsyncMockStream(
        [
            hyperframe.frame.SettingsFrame().serialize(),
            hyperframe.frame.RstStreamFrame(stream_id=1, error_code=8).serialize(),
        ]
    )
    async with _connection(stream) as conn:
        with pytest.raises(ZaprosConnectionError, match="stream 1 reset"):
            await conn.send_request(Request(URL("https://example.com/"), "GET"))


async def test_http2_goaway_marks_connection_unusable() -> None:
    stream = AsyncMockStream(
        _ok_response_frames()
        + [
            hyperframe.frame.GoAwayFrame(stream_id=0, error_code=0, last_stream_id=1).serialize(),
        ]
    )
    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://example.com/"), "GET"))
        assert await response.aread() == b"Hello, world!"

        await anyio.wait_all_tasks_blocked()
        assert not conn.can_handle_request()

        with pytest.raises(ZaprosConnectionError, match="terminated by peer"):
            await conn.send_request(Request(URL("https://example.com/"), "GET"))


class AsyncRecordingStream(AsyncMockStream):
    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self.written = bytearray()
        self.writes = 0

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        self.written.extend(data)
        self.writes += 1
        return await super().write_all(data, timeout)


def _server_events(written: bytes) -> list[h2.events.Event]:
    server = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False))
    # Windows large enough for any request body the tests send.
    server.local_settings = h2.settings.Settings(
        client=False, initial_values={h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 2**24}
    )
    server.initiate_connection()
    server.increment_flow_control_window(2**24)
    return server.receive_data(written)


async def test_http2_bytes_body_with_trailers() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    async with _connection(stream) as conn:
        request = Request(URL("https://example.com/"), "POST", body=b"hello", trailers={"X-Checksum": "abc"})
        response = await conn.send_request(request)
        assert response.status == 200
        await response.aread()

        # Let the body pump finish writing.
        await anyio.wait_all_tasks_blocked()
        events = _server_events(bytes(stream.written))
        trailers = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
        assert len(trailers) == 1
        assert trailers[0].headers == [(b"x-checksum", b"abc")]
        assert trailers[0].stream_ended is not None
        request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
        assert request_received.stream_ended is None
        assert (b"content-length", b"5") in request_received.headers
        assert (b"trailer", b"X-Checksum") in request_received.headers


async def test_http2_streaming_body_populates_trailers() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    async with _connection(stream) as conn:
        trailers = Headers()

        async def body():
            total = 0
            for chunk in (b"ab", b"cde"):
                total += len(chunk)
                yield chunk
            trailers["X-Total"] = str(total)

        request = Request(URL("https://example.com/"), "POST", body=body(), trailers=trailers)
        response = await conn.send_request(request)
        assert response.status == 200
        await response.aread()

        # Let the body pump finish writing.
        await anyio.wait_all_tasks_blocked()
        events = _server_events(bytes(stream.written))
        data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
        assert data == b"abcde"
        (trailer_event,) = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
        assert trailer_event.headers == [(b"x-total", b"5")]
        request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
        assert not any(k == b"trailer" for k, _ in request_received.headers)


async def test_http2_no_body_with_trailers_keeps_stream_open_until_trailers() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    async with _connection(stream) as conn:
        request = Request(URL("https://example.com/"), "POST", trailers={"X-Checksum": "abc"})
        response = await conn.send_request(request)
        assert response.status == 200
        await response.aread()

        # Let the body pump finish writing.
        await anyio.wait_all_tasks_blocked()
        events = _server_events(bytes(stream.written))
        request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
        assert request_received.stream_ended is None
        (trailer_event,) = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
        assert trailer_event.headers == [(b"x-checksum", b"abc")]
        assert trailer_event.stream_ended is not None


async def test_http2_empty_trailers_end_stream_without_trailer_frame() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    async with _connection(stream) as conn:
        request = Request(URL("https://example.com/"), "POST", body=b"hello", trailers={})
        response = await conn.send_request(request)
        assert response.status == 200
        await response.aread()

        # Let the body pump finish writing.
        await anyio.wait_all_tasks_blocked()
        events = _server_events(bytes(stream.written))
        assert not any(isinstance(e, h2.events.TrailersReceived) for e in events)
        assert any(isinstance(e, h2.events.StreamEnded) for e in events)
        data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
        assert data == b"hello"


async def test_http2_request_body_is_written_a_batch_at_a_time() -> None:
    # The server grants a large window, so flow control doesn't split up the body.
    grant = (
        hyperframe.frame.SettingsFrame(settings={hyperframe.frame.SettingsFrame.INITIAL_WINDOW_SIZE: 2**24}).serialize()
        + hyperframe.frame.WindowUpdateFrame(stream_id=0, window_increment=2**24).serialize()
    )
    stream = AsyncRecordingStream([grant + _headers_frame(1) + _data_frame(1, b"", end_stream=True)])
    body = b"x" * 2**20
    async with _connection(stream) as conn:
        await (await conn.send_request(Request(URL("https://example.com/"), "POST", body=body))).aread()
        # Let the body pump finish writing.
        await anyio.wait_all_tasks_blocked()

    data = b"".join(e.data for e in _server_events(bytes(stream.written)) if isinstance(e, h2.events.DataReceived))
    assert data == body
    # The body takes 64 DATA frames, but far fewer writes.
    assert stream.writes < 2 * len(body) // _SEND_BATCH


async def test_http2_response_arrives_while_request_body_is_still_streaming() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    resume = anyio.Event()

    async def body():
        yield b"first"
        await resume.wait()
        yield b"second"

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=body()))
            assert response.status == 200

            resume.set()
            assert await response.aread() == b"Hello, world!"
            await anyio.wait_all_tasks_blocked()
            assert conn.streams == {}

            events = _server_events(bytes(stream.written))
            data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
            assert data == b"firstsecond"
            assert any(isinstance(e, h2.events.StreamEnded) for e in events)


async def test_http2_complete_response_with_no_error_reset_stops_request_body() -> None:
    stream = AsyncRecordingStream(
        _ok_response_frames() + [hyperframe.frame.RstStreamFrame(stream_id=1, error_code=0).serialize()]
    )
    body_closed = False

    async def body():
        nonlocal body_closed
        try:
            yield b"first"
            await anyio.sleep_forever()
            yield b"never sent"
        finally:
            body_closed = True

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=body()))
            assert response.status == 200
            assert await response.aread() == b"Hello, world!"

            await anyio.wait_all_tasks_blocked()
            assert body_closed
            assert conn.streams == {}
            assert conn.can_handle_request()


async def test_http2_closing_response_early_resets_stream_and_stops_request_body() -> None:
    stream = AsyncRecordingStream(
        [
            hyperframe.frame.SettingsFrame().serialize(),
            hyperframe.frame.HeadersFrame(
                stream_id=1,
                data=_encode_headers([(b":status", b"200")]),
                flags=["END_HEADERS"],
            ).serialize(),
        ]
    )
    body_closed = False

    async def body():
        nonlocal body_closed
        try:
            yield b"first"
            await anyio.sleep_forever()
            yield b"never sent"
        finally:
            body_closed = True

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=body()))
            assert response.status == 200
            await response.aclose()

            await anyio.wait_all_tasks_blocked()
            assert body_closed
            assert conn.streams == {}
            assert conn.can_handle_request()

            events = _server_events(bytes(stream.written))
            (reset,) = [e for e in events if isinstance(e, h2.events.StreamReset)]
            assert reset.error_code == h2.errors.ErrorCodes.CANCEL


class AsyncBlockingWriteStream(AsyncRecordingStream):
    """Blocks the write carrying `marker` until `release` is set; reads wait until that write starts."""

    def __init__(self, buffer: list[bytes], marker: bytes) -> None:
        super().__init__(buffer)
        self._marker = marker
        self.write_blocked = anyio.Event()
        self.release = anyio.Event()

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        await self.write_blocked.wait()
        return await super().read(max_bytes, timeout)

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        if self._marker in data:
            self.write_blocked.set()
            await self.release.wait()
        return await super().write_all(data, timeout)


async def test_http2_closing_response_while_request_body_write_is_in_flight_stops_request_body() -> None:
    stream = AsyncBlockingWriteStream(
        [
            hyperframe.frame.SettingsFrame().serialize()
            + hyperframe.frame.HeadersFrame(
                stream_id=1,
                data=_encode_headers([(b":status", b"200")]),
                flags=["END_HEADERS"],
            ).serialize(),
        ],
        marker=b"first",
    )
    body_closed = False

    async def body():
        nonlocal body_closed
        try:
            yield b"first"
            await anyio.sleep_forever()
            yield b"never sent"
        finally:
            body_closed = True

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=body()))
            assert response.status == 200

            # Close the response while the body's DATA frame is still being written.
            async with anyio.create_task_group() as tg:
                tg.start_soon(response.aclose)
                await anyio.wait_all_tasks_blocked()
                stream.release.set()

            await anyio.wait_all_tasks_blocked()
            assert body_closed
            assert conn.streams == {}
            assert conn.can_handle_request()


class AsyncMockTransport:
    """Opens every connection on `make_stream()` and records the ALPN protocols and connect timeouts."""

    def __init__(self, make_stream: Callable[[], AsyncBaseNetworkStream]) -> None:
        self._make_stream = make_stream
        self.alpn_offers: list[list[Literal["http/1.1", "h2"]] | None] = []
        self.connect_timeouts: list[float | None] = []

    async def aconnect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        alpn_protocols: list[Literal["http/1.1", "h2"]] | None = None,
        timeout: float | None = None,
    ) -> AsyncBaseNetworkStream:
        self.alpn_offers.append(alpn_protocols)
        self.connect_timeouts.append(timeout)
        return self._make_stream()


async def test_http2_acknowledges_response_data_only_as_it_is_read() -> None:
    # Enough data that reading it makes h2 grant the stream more window (it does so at half the window).
    chunk = b"x" * 16384
    count = _STREAM_RECEIVE_WINDOW // 2 // len(chunk) + 1
    # The response stays open, like a large download in progress.
    stream = AsyncRecordingStream(
        [
            hyperframe.frame.SettingsFrame().serialize()
            + _headers_frame(1)
            + b"".join(_data_frame(1, chunk) for _ in range(count))
        ]
    )

    def stream_window_updates() -> list[h2.events.WindowUpdated]:
        events = _server_events(bytes(stream.written))
        return [e for e in events if isinstance(e, h2.events.WindowUpdated) and e.stream_id == 1]

    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://example.com/"), "GET"))
        await anyio.wait_all_tasks_blocked()
        # Received but not read yet, so the server must not be allowed to send more.
        assert stream_window_updates() == []

        received = 0
        async for data in response.async_iter_bytes():
            received += len(data)
            if received == count * len(chunk):
                break
        await anyio.wait_all_tasks_blocked()
        assert stream_window_updates()


async def test_http2_unread_response_does_not_stall_other_streams() -> None:
    def full_window(stream_id: int) -> bytes:
        return b"".join(_data_frame(stream_id, b"x" * 16384) for _ in range(_STREAM_RECEIVE_WINDOW // 16384))

    # The server fills the first response's window, and nobody reads it.
    stream = AsyncMockStream([hyperframe.frame.SettingsFrame().serialize() + _headers_frame(1) + full_window(1)])

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            await conn.send_request(Request(URL("https://example.com/a"), "GET"))

            async def answer_second_request() -> None:
                await anyio.wait_all_tasks_blocked()
                stream.feed(_headers_frame(3) + full_window(3) + _data_frame(3, b"", end_stream=True))

            async with anyio.create_task_group() as tg:
                tg.start_soon(answer_second_request)
                second = await conn.send_request(Request(URL("https://example.com/b"), "GET"))
                assert len(await second.aread()) == _STREAM_RECEIVE_WINDOW


class AsyncPausableStream(AsyncRecordingStream):
    """After `pause_next_write()`, the next write waits until `resume` is set."""

    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self._pause = False
        self.write_paused = anyio.Event()
        self.resume = anyio.Event()

    def pause_next_write(self) -> None:
        self._pause = True

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        if self._pause:
            self._pause = False
            self.write_paused.set()
            await self.resume.wait()
        return await super().write_all(data, timeout)


async def test_http2_cancelling_a_request_mid_write_keeps_the_connection() -> None:
    stream = AsyncPausableStream([hyperframe.frame.SettingsFrame().serialize() + _headers_frame(1)])

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            first = await conn.send_request(Request(URL("https://example.com/a"), "GET"))
            await anyio.wait_all_tasks_blocked()

            returned = False

            async def second_request(scope: anyio.CancelScope) -> None:
                nonlocal returned
                with scope:
                    await conn.send_request(Request(URL("https://example.com/b"), "GET"))
                returned = True

            # Cancel the second request while its HEADERS are being written.
            stream.pause_next_write()
            scope = anyio.CancelScope()
            async with anyio.create_task_group() as tg:
                tg.start_soon(second_request, scope)
                await stream.write_paused.wait()
                scope.cancel()
                try:
                    # It returns at once, even though the write is stuck (e.g. the peer stopped reading).
                    await anyio.wait_all_tasks_blocked()
                    assert returned
                finally:
                    stream.resume.set()

            assert conn.can_handle_request()
            stream.feed(_data_frame(1, b"still here", end_stream=True))
            assert await first.aread() == b"still here"


async def test_http2_cancelled_read_does_not_drop_data() -> None:
    stream = AsyncPausableStream([hyperframe.frame.SettingsFrame().serialize() + _headers_frame(1)])

    with anyio.fail_after(5):
        async with _connection(stream) as conn, anyio.create_task_group() as tg:
            response = await conn.send_request(Request(URL("https://example.com/a"), "GET"))
            await anyio.wait_all_tasks_blocked()

            # Another request's write gets stuck.
            stream.pause_next_write()
            tg.start_soon(conn.send_request, Request(URL("https://example.com/b"), "GET"))
            await stream.write_paused.wait()

            stream.feed(_data_frame(1, b"first") + _data_frame(1, b"second", end_stream=True))
            chunks = response.async_iter_bytes()
            first = None
            with anyio.move_on_after(0.1):
                first = await chunks.__anext__()
            stream.resume.set()
            assert [first, *[chunk async for chunk in chunks]] == [b"first", b"second"]
            tg.cancel_scope.cancel()


async def test_http2_failed_request_does_not_close_the_shared_connection() -> None:
    stream = AsyncMockStream([hyperframe.frame.SettingsFrame().serialize() + _headers_frame(1)])
    handler = AsyncStdNetworkHandler(
        http1=False,
        http2=True,
        http2_bidirectional_experimental=True,
        read_timeout=0.1,
        transport=AsyncMockTransport(lambda: stream),
    )

    with anyio.fail_after(5):
        try:
            first = await handler.ahandle(Request(URL("https://example.com/a"), "GET"))
            # The server never answers the second request.
            with pytest.raises(ReadTimeoutError):
                await handler.ahandle(Request(URL("https://example.com/b"), "GET"))

            stream.feed(_data_frame(1, b"still here", end_stream=True))
            assert await first.aread() == b"still here"
        finally:
            await handler.aclose()


async def test_http2_waiting_for_a_free_stream_respects_the_deadline() -> None:
    settings = hyperframe.frame.SettingsFrame(settings={hyperframe.frame.SettingsFrame.MAX_CONCURRENT_STREAMS: 1})
    stream = AsyncMockStream([settings.serialize() + _headers_frame(1)])

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            # This response stays open, holding the server's only stream.
            await conn.send_request(Request(URL("https://example.com/a"), "GET"))
            with pytest.raises(TotalTimeoutError):
                await conn.send_request(Request(URL("https://example.com/b"), "GET"), deadline=time.monotonic() + 0.05)


async def test_http2_stalled_request_body_times_out_as_a_write() -> None:
    # The server grants new streams no send window, so a request body can't make progress.
    settings = hyperframe.frame.SettingsFrame(settings={hyperframe.frame.SettingsFrame.INITIAL_WINDOW_SIZE: 0})
    stream = AsyncMockStream([settings.serialize() + _headers_frame(1) + _data_frame(1, b"", end_stream=True)])

    with anyio.fail_after(5):
        async with _connection(stream) as conn:
            # A first request makes sure the server's SETTINGS are in before the body is sent.
            await (await conn.send_request(Request(URL("https://example.com/a"), "GET"))).aread()
            with pytest.raises(WriteTimeoutError):
                await conn.send_request(Request(URL("https://example.com/b"), "POST", body=b"data"), write_timeout=0.05)


async def test_http2_sends_a_caller_set_host_as_authority() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://10.0.0.1/"), "GET", headers={"Host": "example.com"}))
        await response.aread()

    events = _server_events(bytes(stream.written))
    request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
    assert (b":authority", b"example.com") in request_received.headers
    assert not any(name == b"host" for name, _ in request_received.headers)


async def test_http2_preface_leaves_out_enable_connect_protocol() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    async with _connection(stream) as conn:
        await (await conn.send_request(Request(URL("https://example.com/"), "GET"))).aread()

    # Some servers reject the preface if it carries this setting.
    (settings,) = [e for e in _server_events(bytes(stream.written)) if isinstance(e, h2.events.RemoteSettingsChanged)]
    assert h2.settings.SettingCodes.ENABLE_CONNECT_PROTOCOL not in settings.changed_settings


async def test_http2_closes_the_socket_once_the_connection_dies() -> None:
    stream = AsyncMockStream(_ok_response_frames() + [b""])  # then the server closes the connection
    async with _connection(stream) as conn:
        response = await conn.send_request(Request(URL("https://example.com/"), "GET"))
        assert await response.aread() == b"Hello, world!"

        await anyio.wait_all_tasks_blocked()
        assert not conn.can_handle_request()
        assert stream.closed


def _bidirectional_handler(stream: AsyncBaseNetworkStream) -> AsyncStdNetworkHandler:
    return AsyncStdNetworkHandler(
        http1=False,
        http2=True,
        http2_bidirectional_experimental=True,
        transport=AsyncMockTransport(lambda: stream),
    )


async def _pooled_connection(handler: AsyncStdNetworkHandler) -> object:
    key, _ = get_pool_key(Request(URL("https://example.com/"), "GET"))
    return await handler._http2_pool.acquire(key)


async def test_bidirectional_handler_works_without_async_context_manager() -> None:
    stream = AsyncMockStream(_ok_response_frames())
    handler = _bidirectional_handler(stream)

    with anyio.fail_after(5):
        response = await handler.ahandle(Request(URL("https://example.com/"), "GET"))
        assert await response.aread() == b"Hello, world!"
        conn = await _pooled_connection(handler)
        assert isinstance(conn, AsyncBidirectionalHttp2Connection)

        await handler.aclose()
        assert stream.closed
        assert not conn.can_handle_request()


async def test_client_can_be_entered_and_exited_in_different_tasks() -> None:
    stream = AsyncMockStream(_ok_response_frames())
    client = AsyncClient(handler=_bidirectional_handler(stream))

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(client.__aenter__)
        response = await client.get("https://example.com/")
        assert await response.aread() == b"Hello, world!"
        async with anyio.create_task_group() as tg:
            tg.start_soon(client.__aexit__, None, None, None)

    assert stream.closed
