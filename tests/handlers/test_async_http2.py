from __future__ import annotations

import hpack
import hyperframe.frame
import pytest
from pywhatwgurl import URL

from zapros._errors import ConnectionError as ZaprosConnectionError
from zapros._handlers._std._async_http2 import AsyncHttp2Connection
from zapros._io._base import AsyncBaseNetworkStream
from zapros._models import Request


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
