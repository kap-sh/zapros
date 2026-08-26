from __future__ import annotations

from typing import Iterator

from pywhatwgurl import URL

from zapros._sync_pool import Http1ConnectionPool
from zapros._handlers._std._sync_http1 import Http1Connection
from zapros._io._base import BaseNetworkStream
from zapros._models import Headers, Request


class MockStream(BaseNetworkStream):
    def __init__(self, buffer: list[bytes]) -> None:
        self._buffer = list(buffer)
        self.written = bytearray()

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._buffer:
            return b""
        return self._buffer.pop(0)

    def write_all(self, data: bytes, timeout: float | None = None) -> int:
        self.written.extend(data)
        return len(data)

    def close(self) -> None:
        pass


_OK_RESPONSE = b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n"


def test_http1_bytes_body_with_trailers() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", body=b"hello", trailers={"X-Checksum": "abc"})
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert request.headers["Content-Length"] == "5"
    assert b"content-length" not in stream.written.lower()
    assert b"transfer-encoding: chunked\r\n" in stream.written.lower()
    assert b"trailer: x-checksum\r\n" in stream.written.lower()
    assert stream.written.endswith(b"5\r\nhello\r\n0\r\nX-Checksum: abc\r\n\r\n")


def test_http1_trailers_strip_explicit_content_length() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(
        URL("http://example.com/"),
        "POST",
        headers={"Content-Length": "5"},
        body=b"hello",
        trailers={"X-Checksum": "abc"},
    )
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert b"content-length" not in stream.written.lower()
    assert b"transfer-encoding: chunked\r\n" in stream.written.lower()


def test_http1_streaming_body_populates_trailers() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    trailers = Headers()

    def body() -> Iterator[bytes]:
        total = 0
        for chunk in (b"ab", b"cde"):
            total += len(chunk)
            yield chunk
        trailers["X-Total"] = str(total)

    request = Request(URL("http://example.com/"), "POST", body=body(), trailers=trailers)
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert stream.written.endswith(b"2\r\nab\r\n3\r\ncde\r\n0\r\nX-Total: 5\r\n\r\n")
    assert b"trailer:" not in stream.written.lower()


def test_http1_empty_trailers_end_chunked_body_plainly() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", body=b"hello", trailers={})
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert stream.written.endswith(b"5\r\nhello\r\n0\r\n\r\n")


def test_http1_no_body_with_trailers_uses_chunked_framing() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", trailers={"X-Checksum": "abc"})
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert b"content-length" not in stream.written.lower()
    assert b"transfer-encoding: chunked\r\n" in stream.written.lower()
    assert stream.written.endswith(b"\r\n\r\n0\r\nX-Checksum: abc\r\n\r\n")


def test_http1_trailer_header_lists_all_known_fields() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(
        URL("http://example.com/"),
        "POST",
        body=b"hello",
        trailers=Headers([("X-A", "1"), ("X-B", "2"), ("x-a", "3")]),
    )
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert b"Trailer: X-A, X-B\r\n" in stream.written


def test_http1_explicit_trailer_header_is_kept() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(
        URL("http://example.com/"),
        "POST",
        headers={"Trailer": "X-Custom"},
        body=b"hello",
        trailers={"X-Checksum": "abc"},
    )
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert stream.written.lower().count(b"trailer:") == 1
    assert b"trailer: x-custom\r\n" in stream.written.lower()
