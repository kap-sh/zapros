import asyncio
import builtins
import mimetypes
import os
import uuid
from collections.abc import (
    AsyncIterator as ABCAsyncIterator,
    Iterator as ABCIterator,
)
from typing import (
    IO,
    AsyncIterator,
    Iterator,
)

from typing_extensions import Self

from ._models import (
    AsyncClosableStream,
    AsyncStream,
    ClosableStream,
    Stream,
)


def _escape_quoted_string(
    value: str,
) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class _FileStream(AsyncClosableStream, ClosableStream):
    _CHUNK_SIZE = 65536

    def __init__(
        self,
        path: str | os.PathLike[str],
    ) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    def _ensure_open_sync(
        self,
    ) -> IO[bytes]:
        if self._handle is None:
            self._handle = builtins.open(self._path, "rb")
        return self._handle

    async def _ensure_open_async(
        self,
    ) -> IO[bytes]:
        if self._handle is not None:
            return self._handle

        self._handle = await asyncio.to_thread(
            builtins.open,
            self._path,
            "rb",
        )
        return self._handle

    def __iter__(
        self,
    ) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        handle = self._ensure_open_sync()
        chunk = handle.read(self._CHUNK_SIZE)
        if not chunk:
            self.close()
            raise StopIteration
        return chunk

    def __aiter__(
        self,
    ) -> "_FileStream":
        return self

    async def __anext__(self) -> bytes:
        handle = await self._ensure_open_async()
        chunk = await asyncio.to_thread(
            handle.read,
            self._CHUNK_SIZE,
        )
        if not chunk:
            await self.aclose()
            raise StopAsyncIteration
        return chunk

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    async def aclose(self) -> None:
        if self._handle is not None:
            await asyncio.to_thread(self._handle.close)
            self._handle = None


class Part:
    __slots__ = (
        "content",
        "filename",
        "content_type",
    )

    def __init__(
        self,
        content: Iterator[bytes] | AsyncIterator[bytes] | Stream | AsyncStream | bytes,
    ) -> None:
        self.content = content
        self.filename: str | None = None
        self.content_type: str = "application/octet-stream"

    @classmethod
    def bytes(cls, data: bytes) -> Self:
        return cls(data)

    @classmethod
    def stream(
        cls,
        stream: Iterator[builtins.bytes] | Stream,
    ) -> Self:
        return cls(stream)

    @classmethod
    def async_stream(
        cls,
        stream: AsyncIterator[builtins.bytes] | AsyncStream,
    ) -> Self:
        return cls(stream)

    @classmethod
    def text(cls, text: str) -> Self:
        part = cls(text.encode("utf-8"))
        part.content_type = "text/plain; charset=utf-8"
        return part

    def file_name(self, name: str) -> Self:
        self.filename = name
        return self

    def mime_type(self, mime: str) -> Self:
        self.content_type = mime
        return self

    def close(self) -> None:
        if isinstance(self.content, ClosableStream):
            self.content.close()
        elif isinstance(
            self.content,
            ABCAsyncIterator,
        ):
            raise RuntimeError("Part content is an AsyncStream, use aclose() to close it")

    async def aclose(self) -> None:
        if isinstance(
            self.content,
            AsyncClosableStream,
        ):
            await self.content.aclose()
        elif isinstance(self.content, ABCIterator):
            raise RuntimeError("Part content is a Stream, use close() to close it")


def _generate_part_headers(
    name: str,
    filename: str | None,
    content_type: str,
) -> bytes:
    escaped_name = _escape_quoted_string(name)

    if filename:
        escaped_filename = _escape_quoted_string(filename)
        disposition = f'Content-Disposition: form-data; name="{escaped_name}"; filename="{escaped_filename}"\r\n'
    else:
        disposition = f'Content-Disposition: form-data; name="{escaped_name}"\r\n'

    headers = disposition.encode("utf-8")
    headers += f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
    return headers


class MultipartStream(ClosableStream, AsyncClosableStream):
    __slots__ = (
        "_parts",
        "_boundary",
        "_iterator",
        "_async_iterator",
    )

    def __init__(
        self,
        parts: list[tuple[str, Part]],
        boundary: str,
    ) -> None:
        self._parts = parts
        self._boundary = boundary
        self._iterator: Iterator[bytes] = self._generate_parts()
        self._async_iterator: AsyncIterator[bytes] = self._generate_async_parts()

    def _generate_parts(
        self,
    ) -> Iterator[bytes]:
        for name, part in self._parts:
            yield f"--{self._boundary}\r\n".encode("utf-8")
            yield _generate_part_headers(
                name,
                part.filename,
                part.content_type,
            )

            assert not isinstance(
                part.content,
                ABCAsyncIterator,
            ), "Part content must be a Stream or bytes"

            if isinstance(part.content, bytes):
                yield part.content
            else:
                for chunk in part.content:
                    yield chunk

            yield b"\r\n"

        yield f"--{self._boundary}--\r\n".encode("utf-8")

    async def _generate_async_parts(
        self,
    ) -> AsyncIterator[bytes]:
        for name, part in self._parts:
            yield f"--{self._boundary}\r\n".encode("utf-8")
            yield _generate_part_headers(
                name,
                part.filename,
                part.content_type,
            )

            assert not isinstance(
                part.content,
                ABCIterator,
            ), "Part content must be an AsyncStream or bytes"

            if isinstance(part.content, bytes):
                yield part.content
            else:
                async for chunk in part.content:
                    yield chunk

            yield b"\r\n"

        yield f"--{self._boundary}--\r\n".encode("utf-8")

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        return await anext(self._async_iterator)

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        return next(self._iterator)

    def close(self) -> None:
        for _, part in self._parts:
            part.close()

    async def aclose(self) -> None:
        for _, part in self._parts:
            await part.aclose()


class Multipart:
    __slots__ = ("_parts", "_boundary")

    def __init__(
        self,
        boundary: str | None = None,
    ) -> None:
        self._boundary = boundary or f"----FormBoundary{uuid.uuid4().hex}"
        self._parts: list[tuple[str, Part]] = []

    def text(self, name: str, value: str) -> Self:
        part = Part(value.encode("utf-8"))
        part.content_type = "text/plain; charset=utf-8"
        self._parts.append((name, part))
        return self

    def file(
        self,
        name: str,
        path: str | os.PathLike[str],
    ) -> Self:
        part = Part(_FileStream(path))
        part.filename = os.path.basename(os.fspath(path))
        part.content_type = mimetypes.guess_type(os.fspath(path))[0] or "application/octet-stream"
        self._parts.append((name, part))
        return self

    def part(self, name: str, part: Part) -> Self:
        self._parts.append((name, part))
        return self

    def to_body(
        self,
    ) -> bytes | MultipartStream:
        all_static = all(isinstance(part.content, bytes) for _, part in self._parts)

        if all_static:
            result = bytearray()
            for (
                name,
                part,
            ) in self._parts:
                result.extend(f"--{self._boundary}\r\n".encode("utf-8"))
                result.extend(
                    _generate_part_headers(
                        name,
                        part.filename,
                        part.content_type,
                    )
                )
                assert isinstance(part.content, bytes)
                result.extend(part.content)
                result.extend(b"\r\n")
            result.extend(f"--{self._boundary}--\r\n".encode("utf-8"))
            return bytes(result)
        else:
            return MultipartStream(
                parts=self._parts,
                boundary=self._boundary,
            )

    def to_async_body(
        self,
    ) -> bytes | MultipartStream:
        all_static = all(isinstance(part.content, bytes) for _, part in self._parts)

        if all_static:
            result = bytearray()
            for (
                name,
                part,
            ) in self._parts:
                result.extend(f"--{self._boundary}\r\n".encode("utf-8"))
                result.extend(
                    _generate_part_headers(
                        name,
                        part.filename,
                        part.content_type,
                    )
                )
                assert isinstance(part.content, bytes)
                result.extend(part.content)
                result.extend(b"\r\n")
            result.extend(f"--{self._boundary}--\r\n".encode("utf-8"))
            return bytes(result)
        else:
            return MultipartStream(
                parts=self._parts,
                boundary=self._boundary,
            )

    @property
    def content_type(self) -> str:
        return f'multipart/form-data; boundary="{self._boundary}"'
