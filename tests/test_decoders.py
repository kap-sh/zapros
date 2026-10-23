import gzip
import importlib.util
import zlib

import pytest

from zapros._decoders import (
    SUPPORTED_DECODERS,
    DecodingError,
    DeflateDecoder,
    GZipDecoder,
    IdentityDecoder,
    MultiDecoder,
    iter_chunks,
)


def test_identity_decoder_content_pass_untuched():
    decoder = IdentityDecoder(chunk_size=4)
    assert list(decoder.decode(b"Hello, World!")) == [b"Hello, World!"]
    assert list(decoder.flush()) == []


def test_identity_decoder_empty():
    decoder = IdentityDecoder(chunk_size=4)
    assert list(decoder.decode(b"")) == []
    assert list(decoder.flush()) == []


def test_gzip_decoder():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    decoder = GZipDecoder()
    decoded = b"".join(decoder.decode(compressed)) + b"".join(decoder.flush())

    assert decoded == original


def test_gzip_decoder_streaming():
    original = b"Hello, World! This is a test message for gzip compression."
    compressed = gzip.compress(original)

    decoder = GZipDecoder()
    result = b""
    for i in range(0, len(compressed), 10):
        result += b"".join(decoder.decode(compressed[i : i + 10]))
    result += b"".join(decoder.flush())

    assert result == original


def test_gzip_decoder_bounds_output():
    original = b"Z" * 1_000_000
    compressed = gzip.compress(original)

    decoder = GZipDecoder(chunk_size=4096)
    pieces = list(decoder.decode(compressed)) + list(decoder.flush())

    assert b"".join(pieces) == original
    assert max(len(p) for p in pieces) <= 4096


def test_gzip_decoder_invalid_data():
    decoder = GZipDecoder()
    with pytest.raises(DecodingError, match="Failed to decode gzip data"):
        list(decoder.decode(b"invalid gzip data"))


def test_deflate_decoder():
    original = b"Hello, World! This is a test message for deflate compression."
    compressed = zlib.compress(original)

    decoder = DeflateDecoder()
    decoded = b"".join(decoder.decode(compressed)) + b"".join(decoder.flush())

    assert decoded == original


def test_deflate_decoder_raw():
    original = b"Hello, World! This is a test message for raw deflate compression."
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    compressed = compressor.compress(original) + compressor.flush()

    decoder = DeflateDecoder()
    decoded = b"".join(decoder.decode(compressed)) + b"".join(decoder.flush())

    assert decoded == original


def test_deflate_decoder_streaming():
    original = b"Hello, World! This is a test message for deflate compression."
    compressed = zlib.compress(original)

    decoder = DeflateDecoder()
    result = b""
    for i in range(0, len(compressed), 10):
        result += b"".join(decoder.decode(compressed[i : i + 10]))
    result += b"".join(decoder.flush())

    assert result == original


def test_deflate_decoder_bounds_output():
    original = b"Z" * 1_000_000
    compressed = zlib.compress(original)

    decoder = DeflateDecoder(chunk_size=4096)
    pieces = list(decoder.decode(compressed)) + list(decoder.flush())

    assert b"".join(pieces) == original
    assert max(len(p) for p in pieces) <= 4096


def test_deflate_decoder_invalid_data():
    decoder = DeflateDecoder()
    decoder._first_attempt = False
    with pytest.raises(DecodingError, match="Failed to decode deflate data"):
        list(decoder.decode(b"invalid deflate data that is long enough"))


def test_brotli_decoder():
    try:
        import brotlicffi as brotli  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("brotlicffi not installed")

    from zapros._decoders import (
        BrotliDecoder,
    )

    original = b"Hello, World! This is a test message for brotli compression."
    compressed = brotli.compress(original)  # type: ignore[attr-defined]

    decoder = BrotliDecoder()
    decoded = b"".join(decoder.decode(compressed)) + b"".join(decoder.flush())

    assert decoded == original


def test_brotli_decoder_streaming():
    try:
        import brotlicffi as brotli  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("brotlicffi not installed")

    from zapros._decoders import (
        BrotliDecoder,
    )

    original = b"Hello, World! This is a test message for brotli compression."
    compressed = brotli.compress(original)

    decoder = BrotliDecoder()
    result = b""
    for i in range(0, len(compressed), 10):
        result += b"".join(decoder.decode(compressed[i : i + 10]))
    result += b"".join(decoder.flush())

    assert result == original


def test_brotli_decoder_bounds_output():
    try:
        import brotlicffi as brotli  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("brotlicffi not installed")

    from zapros._decoders import (
        BrotliDecoder,
    )

    original = b"Z" * 1_000_000
    compressed = brotli.compress(original)

    decoder = BrotliDecoder(chunk_size=4096)
    pieces = list(decoder.decode(compressed)) + list(decoder.flush())

    assert b"".join(pieces) == original
    assert max(len(p) for p in pieces) <= 4096


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
    decoded = b"".join(decoder.decode(compressed)) + b"".join(decoder.flush())

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
    result = b""
    for i in range(0, len(compressed), 10):
        result += b"".join(decoder.decode(compressed[i : i + 10]))
    result += b"".join(decoder.flush())

    assert result == original


def test_zstandard_decoder_bounds_output():
    try:
        import zstandard
    except ImportError:
        pytest.skip("zstandard not installed")

    from zapros._decoders import (
        ZStandardDecoder,
    )

    original = b"Z" * 1_000_000
    compressed = zstandard.ZstdCompressor().compress(original)

    decoder = ZStandardDecoder(chunk_size=4096)
    pieces = list(decoder.decode(compressed)) + list(decoder.flush())

    assert b"".join(pieces) == original
    assert max(len(p) for p in pieces) <= 4096


def test_multi_decoder():
    original = b"Hello, World! This is a test message for multi-layer compression."
    compressed = zlib.compress(gzip.compress(original))

    decoder = MultiDecoder([GZipDecoder(), DeflateDecoder()])
    decoded = b"".join(decoder.decode(compressed)) + b"".join(decoder.flush())

    assert decoded == original


def test_multi_decoder_streaming():
    original = b"Hello, World! This is a test message for multi-layer compression."
    compressed = zlib.compress(gzip.compress(original))

    decoder = MultiDecoder([GZipDecoder(), DeflateDecoder()])
    result = b""
    for i in range(0, len(compressed), 20):
        result += b"".join(decoder.decode(compressed[i : i + 20]))
    result += b"".join(decoder.flush())

    assert result == original


def test_multi_decoder_bounds_output():
    original = b"Z" * 1_000_000
    compressed = zlib.compress(gzip.compress(original))

    decoder = MultiDecoder([GZipDecoder(chunk_size=4096), DeflateDecoder(chunk_size=4096)])
    pieces = list(decoder.decode(compressed)) + list(decoder.flush())

    assert b"".join(pieces) == original
    assert max(len(p) for p in pieces) <= 4096


def test_iter_chunks_splits_oversized_data():
    chunks = list(iter_chunks(b"Hello, World! This is a test.", chunk_size=10))

    assert chunks == [b"Hello, Wor", b"ld! This i", b"s a test."]


def test_iter_chunks_exact_size():
    data = b"1234567890"
    chunks = list(iter_chunks(data, chunk_size=10))

    assert chunks == [data]
    assert chunks[0] is data


def test_iter_chunks_does_not_hold_small_data():
    assert list(iter_chunks(b"Hello, ", chunk_size=10)) == [b"Hello, "]
    assert list(iter_chunks(b"World! ", chunk_size=10)) == [b"World! "]


def test_iter_chunks_empty():
    assert list(iter_chunks(b"", chunk_size=10)) == []


def test_supported_decoders_registry():
    assert "identity" in SUPPORTED_DECODERS
    assert "gzip" in SUPPORTED_DECODERS
    assert "deflate" in SUPPORTED_DECODERS

    assert SUPPORTED_DECODERS["identity"] == IdentityDecoder
    assert SUPPORTED_DECODERS["gzip"] == GZipDecoder
    assert SUPPORTED_DECODERS["deflate"] == DeflateDecoder


# "br" stays registered without brotlicffi, which only Pyodide lacks
@pytest.mark.no_pyodide
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
