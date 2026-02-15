import gzip
import importlib.util
import zlib

import pytest

from zapros._decoders import (
    SUPPORTED_DECODERS,
    ByteChunker,
    DecodingError,
    DeflateDecoder,
    GZipDecoder,
    IdentityDecoder,
    MultiDecoder,
)


def test_identity_decoder():
    decoder = IdentityDecoder()
    data = b"Hello, World!"
    assert decoder.decode(data) == data
    assert decoder.flush() == b""


def test_gzip_decoder():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    decoder = GZipDecoder()
    decoded = decoder.decode(compressed)
    decoded += decoder.flush()

    assert decoded == original


def test_gzip_decoder_streaming():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    decoder = GZipDecoder()
    chunk_size = 10
    result = b""

    for i in range(0, len(compressed), chunk_size):
        chunk = compressed[i : i + chunk_size]
        result += decoder.decode(chunk)

    result += decoder.flush()
    assert result == original


def test_gzip_decoder_invalid_data():
    decoder = GZipDecoder()
    with pytest.raises(
        DecodingError,
        match="Failed to decode gzip data",
    ):
        decoder.decode(b"invalid gzip data")


def test_deflate_decoder():
    original = b"Hello, World! This is a test message for deflate compression."
    compressed = zlib.compress(original)

    decoder = DeflateDecoder()
    decoded = decoder.decode(compressed)
    decoded += decoder.flush()

    assert decoded == original


def test_deflate_decoder_raw():
    original = b"Hello, World! This is a test message for raw deflate compression."
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    compressed = compressor.compress(original) + compressor.flush()

    decoder = DeflateDecoder()
    decoded = decoder.decode(compressed)
    decoded += decoder.flush()

    assert decoded == original


def test_deflate_decoder_streaming():
    original = b"Hello, World! This is a test message for deflate compression."
    compressed = zlib.compress(original)

    decoder = DeflateDecoder()
    chunk_size = 10
    result = b""

    for i in range(0, len(compressed), chunk_size):
        chunk = compressed[i : i + chunk_size]
        result += decoder.decode(chunk)

    result += decoder.flush()
    assert result == original


def test_deflate_decoder_invalid_data():
    decoder = DeflateDecoder()
    decoder._first_attempt = False
    with pytest.raises(
        DecodingError,
        match="Failed to decode deflate data",
    ):
        decoder.decode(b"invalid deflate data that is long enough")


def test_brotli_decoder():
    try:
        import brotli
    except ImportError:
        try:
            import brotlicffi as brotli  # type: ignore[import-not-found, no-redef]
        except ImportError:
            pytest.skip("brotli not installed")

    from zapros._decoders import (
        BrotliDecoder,
    )

    original = b"Hello, World! This is a test message for brotli compression."
    compressed = brotli.compress(original)  # type: ignore[attr-defined]

    decoder = BrotliDecoder()
    decoded = decoder.decode(compressed)
    decoded += decoder.flush()

    assert decoded == original


def test_brotli_decoder_streaming():
    try:
        import brotli
    except ImportError:
        try:
            import brotlicffi as brotli  # type: ignore[import-not-found, no-redef]
        except ImportError:
            pytest.skip("brotli not installed")

    from zapros._decoders import (
        BrotliDecoder,
    )

    original = b"Hello, World! This is a test message for brotli compression."
    compressed = brotli.compress(original)

    decoder = BrotliDecoder()
    chunk_size = 10
    result = b""

    for i in range(0, len(compressed), chunk_size):
        chunk = compressed[i : i + chunk_size]
        result += decoder.decode(chunk)

    result += decoder.flush()
    assert result == original


def test_zstandard_decoder():
    try:
        import zstandard
    except ImportError:
        pytest.skip("zstandard not installed")

    from zapros._decoders import (
        ZStandardDecoder,
    )

    original = b"Hello, World! This is a test message for zstd compression."
    compressor = zstandard.ZstdCompressor()
    compressed = compressor.compress(original)

    decoder = ZStandardDecoder()
    decoded = decoder.decode(compressed)
    decoded += decoder.flush()

    assert decoded == original


def test_zstandard_decoder_streaming():
    try:
        import zstandard
    except ImportError:
        pytest.skip("zstandard not installed")

    from zapros._decoders import (
        ZStandardDecoder,
    )

    original = b"Hello, World! This is a test message for zstd compression."
    compressor = zstandard.ZstdCompressor()
    compressed = compressor.compress(original)

    decoder = ZStandardDecoder()
    chunk_size = 10
    result = b""

    for i in range(0, len(compressed), chunk_size):
        chunk = compressed[i : i + chunk_size]
        result += decoder.decode(chunk)

    result += decoder.flush()
    assert result == original


def test_multi_decoder():
    original = b"Hello, World! This is a test message for multi-layer compression."

    compressed_gzip = gzip.compress(original)
    compressed_deflate = zlib.compress(compressed_gzip)

    decoder = MultiDecoder(
        [
            GZipDecoder(),
            DeflateDecoder(),
        ]
    )
    decoded = decoder.decode(compressed_deflate)
    decoded += decoder.flush()

    assert decoded == original


def test_multi_decoder_streaming():
    original = b"Hello, World! This is a test message for multi-layer compression."

    compressed_gzip = gzip.compress(original)
    compressed_deflate = zlib.compress(compressed_gzip)

    decoder = MultiDecoder(
        [
            GZipDecoder(),
            DeflateDecoder(),
        ]
    )
    chunk_size = 20
    result = b""

    for i in range(
        0,
        len(compressed_deflate),
        chunk_size,
    ):
        chunk = compressed_deflate[i : i + chunk_size]
        result += decoder.decode(chunk)

    result += decoder.flush()
    assert result == original


def test_byte_chunker():
    chunker = ByteChunker(chunk_size=10)

    data = b"Hello, World! This is a test."
    chunks = list(chunker.feed(data))

    assert len(chunks) == 2
    assert chunks[0] == b"Hello, Wor"
    assert chunks[1] == b"ld! This i"

    remaining = chunker.flush()
    assert remaining == b"s a test."


def test_byte_chunker_exact_size():
    chunker = ByteChunker(chunk_size=10)

    data = b"1234567890"
    chunks = list(chunker.feed(data))

    assert len(chunks) == 1
    assert chunks[0] == b"1234567890"

    remaining = chunker.flush()
    assert remaining == b""


def test_byte_chunker_multiple_feeds():
    chunker = ByteChunker(chunk_size=10)

    all_chunks = []
    all_chunks.extend(chunker.feed(b"Hello, "))
    all_chunks.extend(chunker.feed(b"World! "))
    all_chunks.extend(chunker.feed(b"This is a test."))

    assert len(all_chunks) == 2
    assert all_chunks[0] == b"Hello, Wor"
    assert all_chunks[1] == b"ld! This i"

    remaining = chunker.flush()
    assert remaining == b"s a test."


def test_byte_chunker_empty():
    chunker = ByteChunker(chunk_size=10)
    chunks = list(chunker.feed(b""))
    assert chunks == []

    remaining = chunker.flush()
    assert remaining == b""


def test_supported_decoders_registry():
    assert "identity" in SUPPORTED_DECODERS
    assert "gzip" in SUPPORTED_DECODERS
    assert "deflate" in SUPPORTED_DECODERS

    assert SUPPORTED_DECODERS["identity"] == IdentityDecoder
    assert SUPPORTED_DECODERS["gzip"] == GZipDecoder
    assert SUPPORTED_DECODERS["deflate"] == DeflateDecoder


def test_brotli_in_registry():
    has_brotli = importlib.util.find_spec("brotli") is not None
    has_brotlicffi = importlib.util.find_spec("brotlicffi") is not None
    if has_brotli or has_brotlicffi:
        assert "br" in SUPPORTED_DECODERS
    else:
        assert "br" not in SUPPORTED_DECODERS


def test_zstandard_in_registry():
    has_zstandard = importlib.util.find_spec("zstandard") is not None
    if has_zstandard:
        assert "zstd" in SUPPORTED_DECODERS
    else:
        assert "zstd" not in SUPPORTED_DECODERS
