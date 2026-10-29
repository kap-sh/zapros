from __future__ import annotations

from typing import Iterator

from pywhatwgurl import URL

from zapros._sync_pool import Http1ConnectionPool
from zapros._constants import EXPECT_CONTINUE_TIMEOUT
from zapros._errors import ReadTimeoutError
from zapros._handlers._std._sync_http1 import Http1Connection
from zapros._io._base import BaseNetworkStream
from zapros._models import Headers, Request


class MockStream(BaseNetworkStream):
    def __init__(self, buffer: list[bytes | Exception]) -> None:
        self._buffer = list(buffer)
        self.written = bytearray()
        # What had been written, and the timeout used, at the time of each read.
        self.reads: list[tuple[bytes, float | None]] = []

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        self.reads.append((bytes(self.written), timeout))
        if not self._buffer:
            return b""
        item = self._buffer.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

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


_CONTINUE_RESPONSE = b"HTTP/1.1 100 Continue\r\n\r\n"


def test_http1_expect_continue_sends_body_after_100() -> None:
    stream = MockStream([_CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = conn.send_request(request, read_timeout=5.0)

    assert response.status == 200
    response.read()
    written_before_continue, continue_timeout = stream.reads[0]
    assert written_before_continue.endswith(b"\r\n\r\n")
    assert b"hello" not in written_before_continue
    assert continue_timeout == EXPECT_CONTINUE_TIMEOUT
    assert stream.written.endswith(b"\r\n\r\nhello")
    assert conn.can_handle_request()


def test_http1_expect_continue_streaming_body_is_not_consumed_before_100() -> None:
    stream = MockStream([_CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    def body() -> Iterator[bytes]:
        assert len(stream.reads) == 1
        yield b"hello"

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=body())
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert stream.written.endswith(b"5\r\nhello\r\n0\r\n\r\n")


def test_http1_expect_continue_final_response_skips_body() -> None:
    stream = MockStream([b"HTTP/1.1 417 Expectation Failed\r\ncontent-length: 2\r\n\r\nno"])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = conn.send_request(request)

    assert response.status == 417
    assert response.read() == b"no"
    assert b"hello" not in stream.written
    # The request was never completed, so the connection cannot carry another one.
    assert not conn.can_handle_request()


def test_http1_expect_continue_sends_body_after_timeout() -> None:
    stream = MockStream([ReadTimeoutError("Read operation timed out"), _CONTINUE_RESPONSE + _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = conn.send_request(request)

    # The late 100 (Continue) is skipped once the body is already on its way.
    assert response.status == 200
    response.read()
    assert b"hello" not in stream.reads[0][0]
    assert stream.reads[1][0].endswith(b"\r\n\r\nhello")
    assert conn.can_handle_request()


def test_http1_expect_continue_wait_is_capped_by_read_timeout() -> None:
    stream = MockStream([_CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = conn.send_request(request, read_timeout=0.25)

    assert response.status == 200
    response.read()
    assert stream.reads[0][1] == 0.25


def test_http1_expect_continue_without_body_does_not_wait() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"})
    response = conn.send_request(request, read_timeout=5.0)

    assert response.status == 200
    response.read()
    assert [timeout for _, timeout in stream.reads] == [5.0]


_EARLY_HINTS_RESPONSE = b"HTTP/1.1 103 Early Hints\r\nlink: </style.css>; rel=preload\r\n\r\n"


def test_http1_informational_responses_are_skipped() -> None:
    stream = MockStream([_EARLY_HINTS_RESPONSE, _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    response = conn.send_request(Request(URL("http://example.com/"), "GET"))

    assert response.status == 200
    response.read()
    assert "link" not in response.headers


def test_http1_expect_continue_keeps_waiting_after_other_informational_response() -> None:
    stream = MockStream([_EARLY_HINTS_RESPONSE, _CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert b"hello" not in stream.reads[1][0]
    assert stream.reads[2][0].endswith(b"\r\n\r\nhello")


def test_http1_expect_continue_sends_body_after_other_informational_response_and_timeout() -> None:
    stream = MockStream([_EARLY_HINTS_RESPONSE, ReadTimeoutError("Read operation timed out"), _OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = conn.send_request(request)

    assert response.status == 200
    response.read()
    assert stream.written.endswith(b"\r\n\r\nhello")


def test_http1_unread_empty_content_length_response_is_reused() -> None:
    stream = MockStream([_OK_RESPONSE])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    response = conn.send_request(Request(URL("http://example.com/"), "GET"))
    response.close()

    assert not conn.is_closed
    assert conn.can_handle_request()


def test_http1_unread_non_empty_response_is_not_reused() -> None:
    stream = MockStream([b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n", b"ok"])
    conn = Http1Connection(stream, pool=Http1ConnectionPool())

    response = conn.send_request(Request(URL("http://example.com/"), "GET"))
    response.close()

    assert conn.is_closed
