from __future__ import annotations

import h2.config
import h2.connection
import h2.events
import hpack
import hyperframe.frame
import pytest
from pywhatwgurl import URL

from zapros._errors import ConnectionError as ZaprosConnectionError
from zapros._handlers._std._sync_http2 import Http2Connection
from zapros._io._base import BaseNetworkStream
from zapros._models import Headers, Request


class MockStream(BaseNetworkStream):
    def __init__(self, buffer: list[bytes]) -> None:
        self._buffer = list(buffer)

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._buffer:
            return b""
        return self._buffer.pop(0)

    def write_all(self, data: bytes, timeout: float | None = None) -> int:
        return len(data)

    def close(self) -> None:
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


def test_http2_get_returns_status_and_body() -> None:
    stream = MockStream(_ok_response_frames())
    conn = Http2Connection(stream)

    response = conn.send_request(Request(URL("https://example.com/"), "GET"))

    assert response.status == 200
    assert dict(response.headers.list())["content-type"] == "text/plain"
    assert response.read() == b"Hello, world!"


def test_http2_post_with_body_completes() -> None:
    stream = MockStream(_ok_response_frames())
    conn = Http2Connection(stream)

    response = conn.send_request(Request(URL("https://example.com/"), "POST", body=b'{"data":"upload"}'))

    assert response.status == 200
    assert response.read() == b"Hello, world!"


def test_http2_stream_reset_raises_before_headers() -> None:
    stream = MockStream(
        [
            hyperframe.frame.SettingsFrame().serialize(),
            hyperframe.frame.RstStreamFrame(stream_id=1, error_code=8).serialize(),
        ]
    )
    conn = Http2Connection(stream)

    with pytest.raises(ZaprosConnectionError, match="stream 1 reset"):
        conn.send_request(Request(URL("https://example.com/"), "GET"))


def test_http2_goaway_marks_connection_unusable() -> None:
    stream = MockStream(
        _ok_response_frames()
        + [
            hyperframe.frame.GoAwayFrame(stream_id=0, error_code=0, last_stream_id=1).serialize(),
        ]
    )
    conn = Http2Connection(stream)

    response = conn.send_request(Request(URL("https://example.com/"), "GET"))
    assert response.read() == b"Hello, world!"

    assert conn.can_handle_request()
    conn._receive_events()
    assert not conn.can_handle_request()

    with pytest.raises(ZaprosConnectionError, match="terminated by peer"):
        conn.send_request(Request(URL("https://example.com/"), "GET"))


class RecordingStream(MockStream):
    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self.written = bytearray()

    def write_all(self, data: bytes, timeout: float | None = None) -> int:
        self.written.extend(data)
        return len(data)


def _server_events(written: bytes) -> list[h2.events.Event]:
    server = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False))
    server.initiate_connection()
    return server.receive_data(written)


def test_http2_bytes_body_with_trailers() -> None:
    stream = RecordingStream(_ok_response_frames())
    conn = Http2Connection(stream)

    request = Request(URL("https://example.com/"), "POST", body=b"hello", trailers={"X-Checksum": "abc"})
    response = conn.send_request(request)
    assert response.status == 200
    response.read()

    events = _server_events(bytes(stream.written))
    trailers = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
    assert len(trailers) == 1
    assert trailers[0].headers == [(b"x-checksum", b"abc")]
    assert trailers[0].stream_ended is not None
    request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
    assert request_received.stream_ended is None
    assert (b"content-length", b"5") in request_received.headers
    assert (b"trailer", b"X-Checksum") in request_received.headers


def test_http2_streaming_body_populates_trailers() -> None:
    stream = RecordingStream(_ok_response_frames())
    conn = Http2Connection(stream)

    trailers = Headers()

    def body():
        total = 0
        for chunk in (b"ab", b"cde"):
            total += len(chunk)
            yield chunk
        trailers["X-Total"] = str(total)

    request = Request(URL("https://example.com/"), "POST", body=body(), trailers=trailers)
    response = conn.send_request(request)
    assert response.status == 200
    response.read()

    events = _server_events(bytes(stream.written))
    data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
    assert data == b"abcde"
    (trailer_event,) = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
    assert trailer_event.headers == [(b"x-total", b"5")]
    request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
    assert not any(k == b"trailer" for k, _ in request_received.headers)


def test_http2_no_body_with_trailers_keeps_stream_open_until_trailers() -> None:
    stream = RecordingStream(_ok_response_frames())
    conn = Http2Connection(stream)

    request = Request(URL("https://example.com/"), "POST", trailers={"X-Checksum": "abc"})
    response = conn.send_request(request)
    assert response.status == 200
    response.read()

    events = _server_events(bytes(stream.written))
    request_received = next(e for e in events if isinstance(e, h2.events.RequestReceived))
    assert request_received.stream_ended is None
    (trailer_event,) = [e for e in events if isinstance(e, h2.events.TrailersReceived)]
    assert trailer_event.headers == [(b"x-checksum", b"abc")]
    assert trailer_event.stream_ended is not None


def test_http2_empty_trailers_end_stream_without_trailer_frame() -> None:
    stream = RecordingStream(_ok_response_frames())
    conn = Http2Connection(stream)

    request = Request(URL("https://example.com/"), "POST", body=b"hello", trailers={})
    response = conn.send_request(request)
    assert response.status == 200
    response.read()

    events = _server_events(bytes(stream.written))
    assert not any(isinstance(e, h2.events.TrailersReceived) for e in events)
    assert any(isinstance(e, h2.events.StreamEnded) for e in events)
    data = b"".join(e.data for e in events if isinstance(e, h2.events.DataReceived))
    assert data == b"hello"
