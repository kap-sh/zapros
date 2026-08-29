from __future__ import annotations

import h2.config
import h2.connection
import h2.events
import hpack
import hyperframe.frame
import pytest

from zapros import URL
from zapros._errors import ConnectionError as ZaprosConnectionError
from zapros._handlers._std._async_http2 import AsyncHttp2Connection
from zapros._io._base import AsyncBaseNetworkStream
from zapros._models import Headers, Request


class AsyncMockStream(AsyncBaseNetworkStream):
    def __init__(self, buffer: list[bytes]) -> None:
        self._buffer = list(buffer)

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._buffer:
            return b""
        return self._buffer.pop(0)

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        return len(data)

    async def close(self) -> None:
        pass


def _encode_headers(headers: list[tuple[bytes, bytes]]) -> bytes:
    return hpack.Encoder().encode(headers)


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
    conn = AsyncHttp2Connection(stream)

    response = await conn.send_request(Request(URL("https://example.com/"), "GET"))

    assert response.status == 200
    assert dict(response.headers.list())["content-type"] == "text/plain"
    assert await response.aread() == b"Hello, world!"


async def test_http2_post_with_body_completes() -> None:
    stream = AsyncMockStream(_ok_response_frames())
    conn = AsyncHttp2Connection(stream)

    response = await conn.send_request(Request(URL("https://example.com/"), "POST", body=b'{"data":"upload"}'))

    assert response.status == 200
    assert await response.aread() == b"Hello, world!"


async def test_http2_stream_reset_raises_before_headers() -> None:
    stream = AsyncMockStream(
        [
            hyperframe.frame.SettingsFrame().serialize(),
            hyperframe.frame.RstStreamFrame(stream_id=1, error_code=8).serialize(),
        ]
    )
    conn = AsyncHttp2Connection(stream)

    with pytest.raises(ZaprosConnectionError, match="stream 1 reset"):
        await conn.send_request(Request(URL("https://example.com/"), "GET"))


async def test_http2_goaway_marks_connection_unusable() -> None:
    stream = AsyncMockStream(
        _ok_response_frames()
        + [
            hyperframe.frame.GoAwayFrame(stream_id=0, error_code=0, last_stream_id=1).serialize(),
        ]
    )
    conn = AsyncHttp2Connection(stream)

    response = await conn.send_request(Request(URL("https://example.com/"), "GET"))
    assert await response.aread() == b"Hello, world!"

    assert conn.can_handle_request()
    await conn._receive_events()
    assert not conn.can_handle_request()

    with pytest.raises(ZaprosConnectionError, match="terminated by peer"):
        await conn.send_request(Request(URL("https://example.com/"), "GET"))


class AsyncRecordingStream(AsyncMockStream):
    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self.written = bytearray()

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        self.written.extend(data)
        return len(data)


def _server_events(written: bytes) -> list[h2.events.Event]:
    server = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False))
    server.initiate_connection()
    return server.receive_data(written)


async def test_http2_bytes_body_with_trailers() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    conn = AsyncHttp2Connection(stream)

    request = Request(URL("https://example.com/"), "POST", body=b"hello", trailers={"X-Checksum": "abc"})
    response = await conn.send_request(request)
    assert response.status == 200
    await response.aread()

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
    conn = AsyncHttp2Connection(stream)

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

    events = _server_events(bytes(stream.written))
    data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
    assert data == b"abcde"
    (trailer_event,) = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
    assert trailer_event.headers == [(b"x-total", b"5")]
    request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
    assert not any(k == b"trailer" for k, _ in request_received.headers)


async def test_http2_no_body_with_trailers_keeps_stream_open_until_trailers() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    conn = AsyncHttp2Connection(stream)

    request = Request(URL("https://example.com/"), "POST", trailers={"X-Checksum": "abc"})
    response = await conn.send_request(request)
    assert response.status == 200
    await response.aread()

    events = _server_events(bytes(stream.written))
    request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
    assert request_received.stream_ended is None
    (trailer_event,) = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
    assert trailer_event.headers == [(b"x-checksum", b"abc")]
    assert trailer_event.stream_ended is not None


async def test_http2_empty_trailers_end_stream_without_trailer_frame() -> None:
    stream = AsyncRecordingStream(_ok_response_frames())
    conn = AsyncHttp2Connection(stream)

    request = Request(URL("https://example.com/"), "POST", body=b"hello", trailers={})
    response = await conn.send_request(request)
    assert response.status == 200
    await response.aread()

    events = _server_events(bytes(stream.written))
    assert not any(isinstance(e, h2.events.TrailersReceived) for e in events)
    assert any(isinstance(e, h2.events.StreamEnded) for e in events)
    data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
    assert data == b"hello"
