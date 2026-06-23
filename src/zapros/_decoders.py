import codecs
import zlib
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterator,
    Protocol,
)

from zapros._constants import CHUNK_SIZE

if TYPE_CHECKING:
    # brotlicffi ships no type stubs; treat it as untyped to keep strict happy.
    brotlicffi: Any = None
else:
    try:
        import brotlicffi
    except ImportError:
        brotlicffi = None


if TYPE_CHECKING:
    import zstandard
else:
    try:
        import zstandard
    except ImportError:
        zstandard = None


class DecodingError(Exception):
    pass


class ContentDecoder(Protocol):
    def decode(self, data: bytes) -> Iterator[bytes]:
        raise NotImplementedError()

    def flush(self) -> Iterator[bytes]:
        raise NotImplementedError()


class IdentityDecoder:
    def __init__(self, chunk_size: int = CHUNK_SIZE) -> None:
        self._chunk_size = chunk_size

    def decode(self, data: bytes) -> Iterator[bytes]:
        for i in range(0, len(data), self._chunk_size):
            yield data[i : i + self._chunk_size]

    def flush(self) -> Iterator[bytes]:
        yield from ()


class GZipDecoder:
    def __init__(self, chunk_size: int = CHUNK_SIZE) -> None:
        self._chunk_size = chunk_size
        self._decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)

    def decode(self, data: bytes) -> Iterator[bytes]:
        try:
            while data:
                out = self._decompressor.decompress(data, self._chunk_size)
                data = self._decompressor.unconsumed_tail
                if out:
                    yield out
        except zlib.error as exc:
            raise DecodingError(f"Failed to decode gzip data: {exc}") from exc

    def flush(self) -> Iterator[bytes]:
        try:
            out = self._decompressor.flush()
        except zlib.error as exc:
            raise DecodingError(f"Failed to flush gzip decoder: {exc}") from exc
        if out:
            yield out


class DeflateDecoder:
    def __init__(self, chunk_size: int = CHUNK_SIZE) -> None:
        self._chunk_size = chunk_size
        self._decompressor = zlib.decompressobj()
        self._first_attempt = True

    def decode(self, data: bytes) -> Iterator[bytes]:
        produced = False
        try:
            for piece in self._collect(data):
                produced = True
                yield piece
            self._first_attempt = False
        except zlib.error as exc:
            if self._first_attempt and not produced:
                self._first_attempt = False
                self._decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                try:
                    yield from self._collect(data)
                    return
                except zlib.error as exc2:
                    raise DecodingError(f"Failed to decode deflate data: {exc2}") from exc2
            raise DecodingError(f"Failed to decode deflate data: {exc}") from exc

    def _collect(self, data: bytes) -> Iterator[bytes]:
        while data:
            out = self._decompressor.decompress(data, self._chunk_size)
            data = self._decompressor.unconsumed_tail
            if out:
                yield out

    def flush(self) -> Iterator[bytes]:
        try:
            out = self._decompressor.flush()
        except zlib.error as exc:
            raise DecodingError(f"Failed to flush deflate decoder: {exc}") from exc
        if out:
            yield out


class BrotliDecoder:
    def __init__(self, chunk_size: int = CHUNK_SIZE) -> None:
        if brotlicffi is None:
            raise ImportError("BrotliDecoder requires brotlicffi. Install with: pip install zapros[brotli]")
        self._chunk_size = chunk_size
        self._decompressor: Any = brotlicffi.Decompressor()

    def decode(self, data: bytes) -> Iterator[bytes]:
        try:
            while True:
                out = self._decompressor.process(data, output_buffer_limit=self._chunk_size)
                data = b""
                if out:
                    yield out
                if self._decompressor.is_finished():
                    break
                if self._decompressor.can_accept_more_data() and not out:
                    break
        except brotlicffi.error as exc:
            raise DecodingError(f"Failed to decode brotli data: {exc}") from exc

    def flush(self) -> Iterator[bytes]:
        yield from ()


class _ByteCollector:
    """Sink for zstandard's stream_writer that keeps each bounded write separate."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._chunks.append(bytes(data))
        return len(data)

    def drain(self) -> list[bytes]:
        chunks = self._chunks
        self._chunks = []
        return chunks


class ZStandardDecoder:
    def __init__(self, chunk_size: int = CHUNK_SIZE) -> None:
        if zstandard is None:
            raise ImportError("ZStandardDecoder requires zstandard. Install with: pip install zapros[zstd]")
        self._collector = _ByteCollector()
        # zstandard's stream_writer is a C extension typed for IO[bytes]; our sink
        # only needs write(). Go through Any so the call isn't spuriously rejected.
        decompressor: Any = zstandard.ZstdDecompressor()
        self._writer = decompressor.stream_writer(
            self._collector,
            write_size=chunk_size,
            closefd=False,
        )

    def decode(self, data: bytes) -> Iterator[bytes]:
        try:
            self._writer.write(data)
        except zstandard.ZstdError as exc:
            raise DecodingError(f"Failed to decode zstd data: {exc}") from exc
        yield from self._collector.drain()

    def flush(self) -> Iterator[bytes]:
        try:
            self._writer.flush()
        except zstandard.ZstdError as exc:
            raise DecodingError(f"Failed to flush zstd decoder: {exc}") from exc
        yield from self._collector.drain()


class MultiDecoder:
    def __init__(
        self,
        decoders: list[ContentDecoder],
    ) -> None:
        self._decoders = decoders

    def decode(self, data: bytes) -> Iterator[bytes]:
        stream: Iterator[bytes] = iter((data,))
        for decoder in reversed(self._decoders):
            stream = self._chain(decoder, stream)
        yield from stream

    def flush(self) -> Iterator[bytes]:
        pipeline = list(reversed(self._decoders))
        for i, decoder in enumerate(pipeline):
            stream = decoder.flush()
            for downstream in pipeline[i + 1 :]:
                stream = self._chain(downstream, stream)
            yield from stream

    @staticmethod
    def _chain(decoder: ContentDecoder, source: Iterator[bytes]) -> Iterator[bytes]:
        for piece in source:
            yield from decoder.decode(piece)


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


SUPPORTED_DECODERS: dict[str, Callable[[int], ContentDecoder]] = {
    "identity": IdentityDecoder,
    "gzip": GZipDecoder,
    "deflate": DeflateDecoder,
    "br": BrotliDecoder,
    "zstd": ZStandardDecoder,
}

_available_encodings: list[str] = []
if zstandard is not None:
    _available_encodings.append("zstd")
if brotlicffi is not None:
    _available_encodings.append("br")
_available_encodings.extend(
    [
        "gzip",
        "deflate",
    ]
)
ACCEPT_ENCODING = ", ".join(_available_encodings)
