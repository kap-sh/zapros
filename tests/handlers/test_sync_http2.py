from __future__ import annotations

from typing import Callable, Literal

import h2.config
import h2.connection
import h2.events
import hpack
import hyperframe.frame
import pytest
from pywhatwgurl import URL

from tests.dual_stream import DualStream
from zapros import StdNetworkHandler
from zapros._errors import ConnectionError as ZaprosConnectionError
from zapros._handlers._std._sync_http2 import Http2Connection
from zapros._io._base import BaseNetworkStream
from zapros._models import Headers, Request, RequestContext


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


def test_http2_post_with_dual_iterator_body_completes() -> None:
    stream = MockStream(_ok_response_frames())
    conn = Http2Connection(stream)

    response = conn.send_request(Request(URL("https://example.com/"), "POST", body=DualStream(b"upload")))

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


class Http1OnceStream(BaseNetworkStream):
    """Answers one request with an empty 200 over HTTP/1.1, then asks to close unless `keep_alive`."""

    def __init__(self, *, keep_alive: bool = False) -> None:
        connection = b"" if keep_alive else b"connection: close\r\n"
        self._response = b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n" + connection + b"\r\n"

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        response, self._response = self._response, b""
        return response

    def write_all(self, data: bytes, timeout: float | None = None) -> int:
        return len(data)

    def close(self) -> None:
        pass

    def selected_alpn_protocol(self) -> Literal["http/1.1", "h2"] | None:
        return "http/1.1"


class H2Stream(MockStream):
    def selected_alpn_protocol(self) -> Literal["http/1.1", "h2"] | None:
        return "h2"


class MockTransport:
    """Opens every connection on `make_stream()` and records the ALPN protocols and connect timeouts."""

    def __init__(self, make_stream: Callable[[], BaseNetworkStream]) -> None:
        self._make_stream = make_stream
        self.alpn_offers: list[list[Literal["http/1.1", "h2"]] | None] = []
        self.connect_timeouts: list[float | None] = []

    def connect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        alpn_protocols: list[Literal["http/1.1", "h2"]] | None = None,
        timeout: float | None = None,
    ) -> BaseNetworkStream:
        self.alpn_offers.append(alpn_protocols)
        self.connect_timeouts.append(timeout)
        return self._make_stream()


def test_request_override_disables_http2_and_skips_pooled_http2_connection() -> None:
    streams = iter([H2Stream(_ok_response_frames()), Http1OnceStream()])
    transport = MockTransport(lambda: next(streams))
    handler = StdNetworkHandler(http2=True, transport=transport)

    response = handler.handle(Request(URL("https://example.com/"), "GET"))
    assert response.context.get("network", {}).get("http_protocol") == "HTTP/2"
    response.read()

    response = handler.handle(
        Request(
            URL("https://example.com/"),
            "GET",
            context={"handler_overrides": {"network": {"http2": False}}},
        )
    )
    assert response.context.get("network", {}).get("http_protocol") == "HTTP/1.1"
    response.read()

    assert transport.alpn_offers == [["h2", "http/1.1"], ["http/1.1"]]


def test_request_override_disables_http1_and_skips_idle_http1_connection() -> None:
    streams = iter([Http1OnceStream(keep_alive=True), H2Stream(_ok_response_frames())])
    transport = MockTransport(lambda: next(streams))
    handler = StdNetworkHandler(http2=True, transport=transport)

    response = handler.handle(Request(URL("https://example.com/"), "GET"))
    assert response.context.get("network", {}).get("http_protocol") == "HTTP/1.1"
    response.read()

    response = handler.handle(
        Request(
            URL("https://example.com/"),
            "GET",
            context={"handler_overrides": {"network": {"http1": False}}},
        )
    )
    assert response.context.get("network", {}).get("http_protocol") == "HTTP/2"
    response.read()

    assert transport.alpn_offers == [["h2", "http/1.1"], ["h2"]]


def test_request_override_enables_http2_on_http1_only_handler() -> None:
    streams = iter([Http1OnceStream(), H2Stream(_ok_response_frames())])
    transport = MockTransport(lambda: next(streams))
    handler = StdNetworkHandler(transport=transport)

    response = handler.handle(Request(URL("https://example.com/"), "GET"))
    assert response.context.get("network", {}).get("http_protocol") == "HTTP/1.1"
    response.read()

    response = handler.handle(
        Request(
            URL("https://example.com/"),
            "GET",
            context={"handler_overrides": {"network": {"http2": True}}},
        )
    )
    assert response.context.get("network", {}).get("http_protocol") == "HTTP/2"
    response.read()

    assert transport.alpn_offers == [["http/1.1"], ["h2", "http/1.1"]]


def test_request_override_enabling_http2_without_h2_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zapros._handlers._std._sync.h2", None)
    handler = StdNetworkHandler()

    with pytest.raises(ImportError, match="zapros\\[http2\\]"):
        handler.handle(
            Request(
                URL("https://example.com/"),
                "GET",
                context={"handler_overrides": {"network": {"http2": True}}},
            )
        )


def test_request_override_disabling_every_protocol_raises() -> None:
    handler = StdNetworkHandler()

    with pytest.raises(ValueError, match="At least one of http1 or http2"):
        handler.handle(
            Request(
                URL("https://example.com/"),
                "GET",
                context={"handler_overrides": {"network": {"http1": False}}},
            )
        )


def test_request_override_timeouts_take_priority_over_context_timeouts() -> None:
    transport = MockTransport(Http1OnceStream)
    handler = StdNetworkHandler(connect_timeout=1.0, transport=transport)

    contexts: list[RequestContext] = [
        {},
        {"timeouts": {"connect": 2.0}},
        {"timeouts": {"connect": 2.0}, "handler_overrides": {"network": {"connect_timeout": 3.0}}},
        {"timeouts": {"connect": 2.0}, "handler_overrides": {"network": {"connect_timeout": None}}},
    ]
    for context in contexts:
        response = handler.handle(Request(URL("https://example.com/"), "GET", context=context))
        response.read()

    assert transport.connect_timeouts == [1.0, 2.0, 3.0, None]


def test_get_effective_config_merges_partial_overrides_with_handler_defaults() -> None:
    handler = StdNetworkHandler(http2=True, total_timeout=10.0, read_timeout=5.0)
    request = Request(
        URL("https://example.com/"),
        "GET",
        context={"timeouts": {"write": 2.0}, "handler_overrides": {"network": {"read_timeout": 1.0}}},
    )

    assert handler.get_effective_config(request) == {
        "total_timeout": 10.0,
        "connect_timeout": None,
        "read_timeout": 1.0,
        "write_timeout": 2.0,
        "http1": True,
        "http2": True,
    }
