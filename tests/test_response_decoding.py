import gzip
import importlib.util
import zlib
from typing import (
    AsyncIterator,
    Iterator,
)

import pytest

from zapros import Headers, Response
from zapros._models import (
    AsyncClosableStream,
    ClosableStream,
)


class StreamWrapper(ClosableStream):
    def __init__(self, iterator: Iterator[bytes]) -> None:
        self._iterator = iterator

    def __iter__(
        self,
    ) -> "StreamWrapper":
        return self

    def __next__(self) -> bytes:
        return next(self._iterator)

    def close(self) -> None:
        pass


class AsyncStreamWrapper(AsyncClosableStream):
    def __init__(
        self,
        generator: AsyncIterator[bytes],
    ) -> None:
        self._generator = generator

    def __aiter__(
        self,
    ) -> "AsyncStreamWrapper":
        return self

    async def __anext__(self) -> bytes:
        return await self._generator.__anext__()

    async def aclose(self) -> None:
        pass


def test_response_iter_bytes_no_encoding():
    body = [b"Hello, ", b"World!"]
    response = Response(
        status=200,
        headers=Headers(),
        content=StreamWrapper(iter(body)),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == b"Hello, World!"


def test_response_iter_bytes_gzip():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_gzip_streaming():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    chunk_size = 10
    body_chunks = [
        compressed[i : i + chunk_size]
        for i in range(
            0,
            len(compressed),
            chunk_size,
        )
    ]

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter(body_chunks)),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_deflate():
    original = b"Hello, World! This is a test message for deflate compression."
    compressed = zlib.compress(original)

    response = Response(
        status=200,
        headers=Headers(
            [
                (
                    "Content-Encoding",
                    "deflate",
                )
            ]
        ),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_multiple_encodings():
    original = b"Hello, World! This is a test message for multi-layer compression."
    compressed_gzip = gzip.compress(original)
    compressed_deflate = zlib.compress(compressed_gzip)

    response = Response(
        status=200,
        headers=Headers(
            [
                (
                    "Content-Encoding",
                    "gzip, deflate",
                )
            ]
        ),
        content=StreamWrapper(iter([compressed_deflate])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_case_insensitive():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "GZIP")]),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_with_spaces():
    original = b"Hello, World! This is a test message for multi-layer compression."
    compressed_gzip = gzip.compress(original)
    compressed_deflate = zlib.compress(compressed_gzip)

    response = Response(
        status=200,
        headers=Headers(
            [
                (
                    "Content-Encoding",
                    " gzip , deflate ",
                )
            ]
        ),
        content=StreamWrapper(iter([compressed_deflate])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_unknown_encoding():
    original = b"Hello, World!"

    response = Response(
        status=200,
        headers=Headers(
            [
                (
                    "Content-Encoding",
                    "unknown",
                )
            ]
        ),
        content=StreamWrapper(iter([original])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_iter_raw():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_raw())
    result = b"".join(chunks)
    assert result == compressed
    assert result.startswith(b"\x1f\x8b")


def test_response_iter_raw_streaming():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    chunk_size = 10
    body_chunks = [
        compressed[i : i + chunk_size]
        for i in range(
            0,
            len(compressed),
            chunk_size,
        )
    ]

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter(body_chunks)),
    )

    chunks = list(response.iter_raw())
    result = b"".join(chunks)
    assert result == compressed


def test_response_read():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter([compressed])),
    )

    content = response.read()
    assert content == original

    content2 = response.read()
    assert content2 == original
    assert content2 is content


def test_response_read_then_iter():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter([compressed])),
    )

    content = response.read()
    assert content == original

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


@pytest.mark.asyncio
async def test_response_async_iter_bytes_gzip():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    async def body_generator():
        yield compressed

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=AsyncStreamWrapper(body_generator()),
    )

    chunks = [chunk async for chunk in response.async_iter_bytes()]
    result = b"".join(chunks)
    assert result == original


@pytest.mark.asyncio
async def test_response_async_iter_bytes_streaming():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    chunk_size = 10
    body_chunks = [
        compressed[i : i + chunk_size]
        for i in range(
            0,
            len(compressed),
            chunk_size,
        )
    ]

    async def body_generator():
        for chunk in body_chunks:
            yield chunk

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=AsyncStreamWrapper(body_generator()),
    )

    chunks = [chunk async for chunk in response.async_iter_bytes()]
    result = b"".join(chunks)
    assert result == original


@pytest.mark.asyncio
async def test_response_async_iter_raw():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    async def body_generator():
        yield compressed

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=AsyncStreamWrapper(body_generator()),
    )

    chunks = [chunk async for chunk in response.async_iter_raw()]
    result = b"".join(chunks)
    assert result == compressed
    assert result.startswith(b"\x1f\x8b")


@pytest.mark.asyncio
async def test_response_aread():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    async def body_generator():
        yield compressed

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=AsyncStreamWrapper(body_generator()),
    )

    content = await response.aread()
    assert content == original

    content2 = await response.aread()
    assert content2 == original
    assert content2 is content


@pytest.mark.asyncio
async def test_response_aread_then_async_iter():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    async def body_generator():
        yield compressed

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=AsyncStreamWrapper(body_generator()),
    )

    content = await response.aread()
    assert content == original

    chunks = [chunk async for chunk in response.async_iter_bytes()]
    result = b"".join(chunks)
    assert result == original


def test_response_iter_bytes_custom_chunk_size():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_bytes(chunk_size=10))
    assert all(len(chunk) <= 10 for chunk in chunks[:-1])

    result = b"".join(chunks)
    assert result == original


def test_response_brotli_not_installed():
    has_brotli = importlib.util.find_spec("brotli") is not None
    has_brotlicffi = importlib.util.find_spec("brotlicffi") is not None
    if has_brotli:
        pytest.skip("brotli is installed")
    if has_brotlicffi:
        pytest.skip("brotlicffi is installed")

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "br")]),
        content=StreamWrapper(iter([b"some data"])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == b"some data"


def test_response_zstd_not_installed():
    has_zstandard = importlib.util.find_spec("zstandard") is not None
    if has_zstandard:
        pytest.skip("zstandard is installed")

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "zstd")]),
        content=StreamWrapper(iter([b"some data"])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == b"some data"


def test_response_brotli_if_installed():
    try:
        import brotli
    except ImportError:
        try:
            import brotlicffi as brotli  # type: ignore[import-not-found, no-redef]
        except ImportError:
            pytest.skip("brotli not installed")

    original = b"Hello, World! This is a test message for brotli compression."
    compressed = brotli.compress(original)  # type: ignore[attr-defined]

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "br")]),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_zstd_if_installed():
    try:
        import zstandard
    except ImportError:
        pytest.skip("zstandard not installed")

    original = b"Hello, World! This is a test message for zstd compression."
    compressor = zstandard.ZstdCompressor()
    compressed = compressor.compress(original)

    response = Response(
        status=200,
        headers=Headers([("Content-Encoding", "zstd")]),
        content=StreamWrapper(iter([compressed])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_identity_encoding():
    original = b"Hello, World!"

    response = Response(
        status=200,
        headers=Headers(
            [
                (
                    "Content-Encoding",
                    "identity",
                )
            ]
        ),
        content=StreamWrapper(iter([original])),
    )

    chunks = list(response.iter_bytes())
    result = b"".join(chunks)
    assert result == original


def test_response_empty_body():
    response = Response(
        status=204,
        headers=Headers(),
        content=None,
    )

    chunks = list(response.iter_bytes())
    assert chunks == []


def test_response_empty_body_with_encoding():
    response = Response(
        status=204,
        headers=Headers([("Content-Encoding", "gzip")]),
        content=None,
    )

    chunks = list(response.iter_bytes())
    assert chunks == []
