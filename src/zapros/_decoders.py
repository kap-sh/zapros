import codecs
import zlib
from typing import (
    Any,
    Iterator,
    Protocol,
)


class DecodingError(Exception):
    pass


class ContentDecoder(Protocol):
    def decode(self, data: bytes) -> bytes:
        raise NotImplementedError()

    def flush(self) -> bytes:
        raise NotImplementedError()


class IdentityDecoder:
    def decode(self, data: bytes) -> bytes:
        return data

    def flush(self) -> bytes:
        return b""


class GZipDecoder:
    def __init__(self) -> None:
        self._decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)

    def decode(self, data: bytes) -> bytes:
        try:
            return self._decompressor.decompress(data)
        except zlib.error as exc:
            raise DecodingError(f"Failed to decode gzip data: {exc}") from exc

    def flush(self) -> bytes:
        try:
            return self._decompressor.flush()
        except zlib.error as exc:
            raise DecodingError(f"Failed to flush gzip decoder: {exc}") from exc


class DeflateDecoder:
    def __init__(self) -> None:
        self._decompressor = zlib.decompressobj()
        self._first_attempt = True

    def decode(self, data: bytes) -> bytes:
        try:
            return self._decompressor.decompress(data)
        except zlib.error as exc:
            if self._first_attempt:
                self._first_attempt = False
                self._decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                try:
                    return self._decompressor.decompress(data)
                except zlib.error as exc2:
                    raise DecodingError(f"Failed to decode deflate data: {exc2}") from exc2
            raise DecodingError(f"Failed to decode deflate data: {exc}") from exc

    def flush(self) -> bytes:
        try:
            return self._decompressor.flush()
        except zlib.error as exc:
            raise DecodingError(f"Failed to flush deflate decoder: {exc}") from exc


try:
    import brotli  # type: ignore
except ImportError:
    try:
        import brotlicffi as brotli  # type: ignore
    except ImportError:
        brotli = None


class BrotliDecoder:
    def __init__(self) -> None:
        if brotli is None:
            raise ImportError("BrotliDecoder requires brotli or brotlicffi. Install with: pip install zapros[brotli]")
        self._decompressor: Any = brotli.Decompressor()  # type: ignore

    def decode(self, data: bytes) -> bytes:
        try:
            return self._decompressor.process(data)
        except brotli.error as exc:  # type: ignore
            raise DecodingError(f"Failed to decode brotli data: {exc}") from exc

    def flush(self) -> bytes:
        try:
            if hasattr(
                self._decompressor,
                "flush",
            ):
                return self._decompressor.flush()
            return b""
        except brotli.error as exc:  # type: ignore
            raise DecodingError(f"Failed to flush brotli decoder: {exc}") from exc


try:
    import zstandard  # type: ignore
except ImportError:
    zstandard = None


class ZStandardDecoder:
    def __init__(self) -> None:
        if zstandard is None:
            raise ImportError("ZStandardDecoder requires zstandard. Install with: pip install zapros[zstd]")
        self._decompressor = zstandard.ZstdDecompressor().decompressobj()  # type: ignore

    def decode(self, data: bytes) -> bytes:
        try:
            return self._decompressor.decompress(data)  # type: ignore
        except zstandard.ZstdError as exc:  # type: ignore
            raise DecodingError(f"Failed to decode zstd data: {exc}") from exc

    def flush(self) -> bytes:
        return b""


class MultiDecoder:
    def __init__(
        self,
        decoders: list[ContentDecoder],
    ) -> None:
        self._decoders = decoders

    def decode(self, data: bytes) -> bytes:
        for decoder in reversed(self._decoders):
            data = decoder.decode(data)
        return data

    def flush(self) -> bytes:
        result = b""
        for decoder in reversed(self._decoders):
            flushed = decoder.flush()
            if flushed:
                for dec in self._decoders[self._decoders.index(decoder) + 1 :]:
                    flushed = dec.decode(flushed)
                result += flushed
        return result


class TextDecoder:
    def __init__(self, encoding: str = "utf-8") -> None:
        self.decoder = codecs.getincrementaldecoder(encoding)(errors="replace")

    def decode(self, data: bytes) -> str:
        return self.decoder.decode(data)

    def flush(self) -> str:
        return self.decoder.decode(b"", True)


class ByteChunker:
    def __init__(self, chunk_size: int) -> None:
        self._chunk_size = chunk_size
        self._buffer = bytearray()

    def feed(self, data: bytes) -> Iterator[bytes]:
        self._buffer.extend(data)
        while len(self._buffer) >= self._chunk_size:
            chunk = bytes(self._buffer[: self._chunk_size])
            del self._buffer[: self._chunk_size]
            yield chunk

    def flush(self) -> bytes:
        if self._buffer:
            result = bytes(self._buffer)
            self._buffer.clear()
            return result
        return b""


SUPPORTED_DECODERS: dict[str, type[ContentDecoder]] = {
    "identity": IdentityDecoder,
    "gzip": GZipDecoder,
    "deflate": DeflateDecoder,
    "br": BrotliDecoder,
    "zstd": ZStandardDecoder,
}

_available_encodings: list[str] = []
if zstandard is not None:
    _available_encodings.append("zstd")
if brotli is not None:
    _available_encodings.append("br")
_available_encodings.extend(
    [
        "gzip",
        "deflate",
    ]
)
ACCEPT_ENCODING = ", ".join(_available_encodings)
