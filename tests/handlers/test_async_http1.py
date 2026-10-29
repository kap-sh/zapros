from __future__ import annotations

from typing import AsyncIterator

from pywhatwgurl import URL

from zapros._async_pool import AsyncHttp1ConnectionPool
from zapros._constants import EXPECT_CONTINUE_TIMEOUT
from zapros._errors import ReadTimeoutError
from zapros._handlers._std._async_http1 import AsyncHttp1Connection
from zapros._io._base import AsyncBaseNetworkStream
from zapros._models import Headers, Request


class AsyncMockStream(AsyncBaseNetworkStream):
    def __init__(self, buffer: list[bytes | Exception]) -> None:
        self._buffer = list(buffer)
        self.written = bytearray()
        # What had been written, and the timeout used, at the time of each read.
        self.reads: list[tuple[bytes, float | None]] = []

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        self.reads.append((bytes(self.written), timeout))
        if not self._buffer:
            return b""
        item = self._buffer.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        self.written.extend(data)
        return len(data)

    async def close(self) -> None:
        pass


_OK_RESPONSE = b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n"


async def test_http1_bytes_body_with_trailers() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", body=b"hello", trailers={"X-Checksum": "abc"})
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert request.headers["Content-Length"] == "5"
    assert b"content-length" not in stream.written.lower()
    assert b"transfer-encoding: chunked\r\n" in stream.written.lower()
    assert b"trailer: x-checksum\r\n" in stream.written.lower()
    assert stream.written.endswith(b"5\r\nhello\r\n0\r\nX-Checksum: abc\r\n\r\n")


async def test_http1_trailers_strip_explicit_content_length() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(
        URL("http://example.com/"),
        "POST",
        headers={"Content-Length": "5"},
        body=b"hello",
        trailers={"X-Checksum": "abc"},
    )
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert b"content-length" not in stream.written.lower()
    assert b"transfer-encoding: chunked\r\n" in stream.written.lower()


async def test_http1_streaming_body_populates_trailers() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    trailers = Headers()

    async def body() -> AsyncIterator[bytes]:
        total = 0
        for chunk in (b"ab", b"cde"):
            total += len(chunk)
            yield chunk
        trailers["X-Total"] = str(total)

    request = Request(URL("http://example.com/"), "POST", body=body(), trailers=trailers)
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert stream.written.endswith(b"2\r\nab\r\n3\r\ncde\r\n0\r\nX-Total: 5\r\n\r\n")
    assert b"trailer:" not in stream.written.lower()


async def test_http1_empty_trailers_end_chunked_body_plainly() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", body=b"hello", trailers={})
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert stream.written.endswith(b"5\r\nhello\r\n0\r\n\r\n")


async def test_http1_no_body_with_trailers_uses_chunked_framing() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", trailers={"X-Checksum": "abc"})
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert b"content-length" not in stream.written.lower()
    assert b"transfer-encoding: chunked\r\n" in stream.written.lower()
    assert stream.written.endswith(b"\r\n\r\n0\r\nX-Checksum: abc\r\n\r\n")


async def test_http1_trailer_header_lists_all_known_fields() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(
        URL("http://example.com/"),
        "POST",
        body=b"hello",
        trailers=Headers([("X-A", "1"), ("X-B", "2"), ("x-a", "3")]),
    )
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert b"Trailer: X-A, X-B\r\n" in stream.written


async def test_http1_explicit_trailer_header_is_kept() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(
        URL("http://example.com/"),
        "POST",
        headers={"Trailer": "X-Custom"},
        body=b"hello",
        trailers={"X-Checksum": "abc"},
    )
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert stream.written.lower().count(b"trailer:") == 1
    assert b"trailer: x-custom\r\n" in stream.written.lower()


_CONTINUE_RESPONSE = b"HTTP/1.1 100 Continue\r\n\r\n"


async def test_http1_expect_continue_sends_body_after_100() -> None:
    stream = AsyncMockStream([_CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = await conn.send_request(request, read_timeout=5.0)

    assert response.status == 200
    await response.aread()
    written_before_continue, continue_timeout = stream.reads[0]
    assert written_before_continue.endswith(b"\r\n\r\n")
    assert b"hello" not in written_before_continue
    assert continue_timeout == EXPECT_CONTINUE_TIMEOUT
    assert stream.written.endswith(b"\r\n\r\nhello")
    assert conn.can_handle_request()


async def test_http1_expect_continue_streaming_body_is_not_consumed_before_100() -> None:
    stream = AsyncMockStream([_CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    async def body() -> AsyncIterator[bytes]:
        assert len(stream.reads) == 1
        yield b"hello"

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=body())
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert stream.written.endswith(b"5\r\nhello\r\n0\r\n\r\n")


async def test_http1_expect_continue_final_response_skips_body() -> None:
    stream = AsyncMockStream([b"HTTP/1.1 417 Expectation Failed\r\ncontent-length: 2\r\n\r\nno"])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = await conn.send_request(request)

    assert response.status == 417
    assert await response.aread() == b"no"
    assert b"hello" not in stream.written
    # The request was never completed, so the connection cannot carry another one.
    assert not conn.can_handle_request()


async def test_http1_expect_continue_sends_body_after_timeout() -> None:
    stream = AsyncMockStream([ReadTimeoutError("Read operation timed out"), _CONTINUE_RESPONSE + _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = await conn.send_request(request)

    # The late 100 (Continue) is skipped once the body is already on its way.
    assert response.status == 200
    await response.aread()
    assert b"hello" not in stream.reads[0][0]
    assert stream.reads[1][0].endswith(b"\r\n\r\nhello")
    assert conn.can_handle_request()


async def test_http1_expect_continue_wait_is_capped_by_read_timeout() -> None:
    stream = AsyncMockStream([_CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = await conn.send_request(request, read_timeout=0.25)

    assert response.status == 200
    await response.aread()
    assert stream.reads[0][1] == 0.25


async def test_http1_expect_continue_without_body_does_not_wait() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"})
    response = await conn.send_request(request, read_timeout=5.0)

    assert response.status == 200
    await response.aread()
    assert [timeout for _, timeout in stream.reads] == [5.0]


_EARLY_HINTS_RESPONSE = b"HTTP/1.1 103 Early Hints\r\nlink: </style.css>; rel=preload\r\n\r\n"


async def test_http1_informational_responses_are_skipped() -> None:
    stream = AsyncMockStream([_EARLY_HINTS_RESPONSE, _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    response = await conn.send_request(Request(URL("http://example.com/"), "GET"))

    assert response.status == 200
    await response.aread()
    assert "link" not in response.headers


async def test_http1_expect_continue_keeps_waiting_after_other_informational_response() -> None:
    stream = AsyncMockStream([_EARLY_HINTS_RESPONSE, _CONTINUE_RESPONSE, _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert b"hello" not in stream.reads[1][0]
    assert stream.reads[2][0].endswith(b"\r\n\r\nhello")


async def test_http1_expect_continue_sends_body_after_other_informational_response_and_timeout() -> None:
    stream = AsyncMockStream([_EARLY_HINTS_RESPONSE, ReadTimeoutError("Read operation timed out"), _OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    request = Request(URL("http://example.com/"), "POST", headers={"Expect": "100-continue"}, body=b"hello")
    response = await conn.send_request(request)

    assert response.status == 200
    await response.aread()
    assert stream.written.endswith(b"\r\n\r\nhello")


async def test_http1_unread_empty_content_length_response_is_reused() -> None:
    stream = AsyncMockStream([_OK_RESPONSE])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    response = await conn.send_request(Request(URL("http://example.com/"), "GET"))
    await response.aclose()

    assert not conn.is_closed
    assert conn.can_handle_request()


async def test_http1_unread_non_empty_response_is_not_reused() -> None:
    stream = AsyncMockStream([b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n", b"ok"])
    conn = AsyncHttp1Connection(stream, pool=AsyncHttp1ConnectionPool())

    response = await conn.send_request(Request(URL("http://example.com/"), "GET"))
    await response.aclose()

    assert conn.is_closed
