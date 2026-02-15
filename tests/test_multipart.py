import re
from typing import Iterator as TIterator

import pytest
from inline_snapshot import snapshot

from zapros._multipart import (
    Multipart,
    MultipartStream,
    Part,
    _escape_quoted_string,
    _generate_part_headers,
)


class _TestSyncStream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._consumed = False

    def __iter__(
        self,
    ) -> TIterator[bytes]:
        return self

    def __next__(self) -> bytes:
        if self._consumed:
            raise StopIteration
        self._consumed = True
        return self._data


class _TestAsyncStream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._consumed = False

    def __aiter__(
        self,
    ) -> "_TestAsyncStream":
        return self

    async def __anext__(self) -> bytes:
        if self._consumed:
            raise StopAsyncIteration
        self._consumed = True
        return self._data


def test_escape_quoted_string_no_special_chars():
    result = _escape_quoted_string("hello")
    assert result == snapshot("hello")


def test_escape_quoted_string_with_backslash():
    result = _escape_quoted_string("hello\\world")
    assert result == snapshot("hello\\\\world")


def test_escape_quoted_string_with_quotes():
    result = _escape_quoted_string('hello"world')
    assert result == snapshot('hello\\"world')


def test_escape_quoted_string_with_both():
    result = _escape_quoted_string('hello\\"world')
    assert result == snapshot('hello\\\\\\"world')


def test_part_bytes():
    data = b"test content"
    part = Part.bytes(data)

    assert part.content_type == snapshot("application/octet-stream")
    assert part.filename is None
    assert isinstance(part.content, bytes)
    assert part.content == snapshot(b"test content")


def test_part_async_bytes():
    data = b"async content"
    part = Part.bytes(data)

    assert part.content_type == snapshot("application/octet-stream")
    assert part.filename is None


def test_part_stream():
    stream = _TestSyncStream(b"stream content")
    part = Part.stream(stream)

    assert part.content is stream
    assert part.content_type == snapshot("application/octet-stream")
    assert part.filename is None


def test_part_async_stream():
    stream = _TestAsyncStream(b"async stream content")
    part = Part.async_stream(stream)

    assert part.content is stream
    assert part.content_type == snapshot("application/octet-stream")
    assert part.filename is None


def test_part_text():
    text = "hello world"
    part = Part.text(text)

    assert part.content_type == snapshot("text/plain; charset=utf-8")
    assert part.filename is None
    assert isinstance(part.content, bytes)
    assert part.content == snapshot(b"hello world")


def test_part_async_text():
    text = "async hello"
    part = Part.text(text)

    assert part.content_type == snapshot("text/plain; charset=utf-8")
    assert part.filename is None


def test_part_file_name():
    part = Part.bytes(b"data")
    result = part.file_name("test.txt")

    assert result is part
    assert part.filename == snapshot("test.txt")


def test_part_mime_type():
    part = Part.bytes(b"data")
    result = part.mime_type("image/png")

    assert result is part
    assert part.content_type == snapshot("image/png")


def test_part_fluent_api():
    part = Part.bytes(b"image data").file_name("photo.jpg").mime_type("image/jpeg")

    assert part.filename == snapshot("photo.jpg")
    assert part.content_type == snapshot("image/jpeg")


def test_generate_part_headers_no_filename():
    headers = _generate_part_headers("field_name", None, "text/plain")

    assert headers == snapshot(b'Content-Disposition: form-data; name="field_name"\r\nContent-Type: text/plain\r\n\r\n')


def test_generate_part_headers_with_filename():
    headers = _generate_part_headers(
        "file_field",
        "document.pdf",
        "application/pdf",
    )

    assert headers == snapshot(
        b'Content-Disposition: form-data; name="file_field"; filename="document.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
    )


def test_generate_part_headers_escaped_name():
    headers = _generate_part_headers('field"name', None, "text/plain")

    assert headers == snapshot(
        b'Content-Disposition: form-data; name="field\\"name"\r\nContent-Type: text/plain\r\n\r\n'
    )


def test_generate_part_headers_escaped_filename():
    headers = _generate_part_headers(
        "field",
        'file"name.txt',
        "text/plain",
    )

    assert headers == snapshot(
        b'Content-Disposition: form-data; name="field"; filename="file\\"name.txt"\r\nContent-Type: text/plain\r\n\r\n'
    )


def test_multipart_stream_single_part():
    part = Part.stream(_TestSyncStream(b"value1"))
    part.content_type = "text/plain; charset=utf-8"
    parts = [("field1", part)]
    boundary = "test-boundary"

    stream = MultipartStream(parts, boundary)
    result = b"".join(stream)

    assert result == snapshot(
        b'--test-boundary\r\nContent-Disposition: form-data; name="field1"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nvalue1\r\n--test-boundary--\r\n"
    )


def test_multipart_stream_multiple_parts():
    part1 = Part.stream(_TestSyncStream(b"value1"))
    part1.content_type = "text/plain; charset=utf-8"
    part2 = Part.stream(_TestSyncStream(b"value2"))
    part2.content_type = "text/plain; charset=utf-8"
    parts = [
        ("field1", part1),
        ("field2", part2),
    ]
    boundary = "test-boundary"

    stream = MultipartStream(parts, boundary)
    result = b"".join(stream)

    assert result == snapshot(
        b'--test-boundary\r\nContent-Disposition: form-data; name="field1"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nvalue1\r\n"
        b'--test-boundary\r\nContent-Disposition: form-data; name="field2"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nvalue2\r\n--test-boundary--\r\n"
    )


def test_multipart_stream_with_file():
    part = Part.stream(_TestSyncStream(b"file content"))
    part.file_name("test.txt").mime_type("text/plain")
    parts = [("file", part)]
    boundary = "boundary123"

    stream = MultipartStream(parts, boundary)
    result = b"".join(stream)

    assert result == snapshot(
        b'--boundary123\r\nContent-Disposition: form-data; name="file"; filename="test.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\nfile content\r\n--boundary123--\r\n"
    )


def test_multipart_stream_close():
    part1 = Part.bytes(b"data1")
    part2 = Part.bytes(b"data2")
    parts = [
        ("field1", part1),
        ("field2", part2),
    ]

    stream = MultipartStream(parts, "boundary")
    stream.close()


def test_multipart_stream_iteration():
    part = Part.stream(_TestSyncStream(b"x" * 100))
    parts = [("field", part)]
    boundary = "b"

    stream = MultipartStream(parts, boundary)
    chunks = list(stream)

    assert len(chunks) > 0
    assert b"".join(chunks).startswith(b"--b\r\n")


@pytest.mark.asyncio
async def test_async_multipart_stream_single_part():
    part = Part.async_stream(_TestAsyncStream(b"async value"))
    part.content_type = "text/plain; charset=utf-8"
    parts = [("field1", part)]
    boundary = "async-boundary"

    stream = MultipartStream(parts, boundary)
    result = b""
    async for chunk in stream:
        result += chunk

    assert result == snapshot(
        b'--async-boundary\r\nContent-Disposition: form-data; name="field1"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nasync value\r\n--async-boundary--\r\n"
    )


@pytest.mark.asyncio
async def test_async_multipart_stream_multiple_parts():
    part1 = Part.async_stream(_TestAsyncStream(b"value1"))
    part1.content_type = "text/plain; charset=utf-8"
    part2 = Part.async_stream(_TestAsyncStream(b"value2"))
    part2.content_type = "text/plain; charset=utf-8"
    parts = [
        ("field1", part1),
        ("field2", part2),
    ]
    boundary = "boundary"

    stream = MultipartStream(parts, boundary)
    result = b""
    async for chunk in stream:
        result += chunk

    assert result == snapshot(
        b'--boundary\r\nContent-Disposition: form-data; name="field1"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nvalue1\r\n"
        b'--boundary\r\nContent-Disposition: form-data; name="field2"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nvalue2\r\n--boundary--\r\n"
    )


@pytest.mark.asyncio
async def test_async_multipart_stream_with_file():
    part = Part.async_stream(_TestAsyncStream(b"binary data"))
    part.file_name("data.bin").mime_type("application/octet-stream")
    parts = [("upload", part)]
    boundary = "file-boundary"

    stream = MultipartStream(parts, boundary)
    result = b""
    async for chunk in stream:
        result += chunk

    assert result == snapshot(
        b'--file-boundary\r\nContent-Disposition: form-data; name="upload"; filename="data.bin"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\nbinary data\r\n--file-boundary--\r\n"
    )


@pytest.mark.asyncio
async def test_async_multipart_stream_aclose():
    part1 = Part.bytes(b"data1")
    part2 = Part.bytes(b"data2")
    parts = [
        ("field1", part1),
        ("field2", part2),
    ]

    stream = MultipartStream(parts, "boundary")
    await stream.aclose()


def test_multipart_default_boundary():
    mp = Multipart()

    assert mp._boundary.startswith("----FormBoundary")
    assert len(mp._boundary) == snapshot(48)


def test_multipart_custom_boundary():
    mp = Multipart(boundary="custom-boundary-123")

    assert mp._boundary == snapshot("custom-boundary-123")


def test_multipart_text():
    mp = Multipart(boundary="test")
    result = mp.text("username", "john_doe")

    assert result is mp
    assert len(mp._parts) == snapshot(1)

    name, part = mp._parts[0]
    assert name == snapshot("username")
    assert part.content_type == snapshot("text/plain; charset=utf-8")


def test_multipart_text_multiple():
    mp = Multipart()
    mp.text("field1", "value1").text("field2", "value2")

    assert len(mp._parts) == snapshot(2)


def test_multipart_part():
    mp = Multipart()
    custom_part = Part.bytes(b"custom").mime_type("custom/type")
    result = mp.part("custom_field", custom_part)

    assert result is mp
    assert len(mp._parts) == snapshot(1)

    name, part = mp._parts[0]
    assert name == snapshot("custom_field")
    assert part is custom_part


def test_multipart_to_stream():
    mp = Multipart(boundary="boundary")
    mp.text("field", "value")

    result = mp.to_body()

    assert isinstance(result, bytes)
    assert b"--boundary\r\n" in result
    assert b"value" in result


def test_multipart_to_async_body():
    mp = Multipart(boundary="boundary")
    mp.text("field", "value")

    result = mp.to_async_body()

    assert isinstance(result, bytes)


@pytest.mark.asyncio
async def test_multipart_to_async_body_iteration():
    mp = Multipart(boundary="async-b")
    mp.part("name", Part.text("test"))

    result = mp.to_async_body()

    assert result == snapshot(
        b'--async-b\r\nContent-Disposition: form-data; name="name"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\ntest\r\n--async-b--\r\n"
    )


def test_multipart_content_type():
    mp = Multipart(boundary="my-boundary")

    assert mp.content_type == snapshot('multipart/form-data; boundary="my-boundary"')


def test_multipart_complex_example():
    mp = Multipart(boundary="WebKitFormBoundary")
    mp.text("username", "alice")
    mp.text("email", "alice@example.com")
    mp.part(
        "avatar",
        Part.bytes(b"PNG_DATA").file_name("avatar.png").mime_type("image/png"),
    )

    result = mp.to_body()

    assert result == snapshot(
        b'--WebKitFormBoundary\r\nContent-Disposition: form-data; name="username"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nalice\r\n"
        b'--WebKitFormBoundary\r\nContent-Disposition: form-data; name="email"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nalice@example.com\r\n"
        b'--WebKitFormBoundary\r\nContent-Disposition: form-data; name="avatar"; filename="avatar.png"\r\n'
        b"Content-Type: image/png\r\n\r\nPNG_DATA\r\n--WebKitFormBoundary--\r\n"
    )


def test_multipart_stream_proper_format():
    mp = Multipart(boundary="B")
    mp.text("f", "v")

    result = mp.to_body()

    assert result == snapshot(
        b'--B\r\nContent-Disposition: form-data; name="f"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nv\r\n--B--\r\n"
    )


@pytest.mark.asyncio
async def test_async_multipart_stream_proper_format():
    mp = Multipart(boundary="B")
    mp.part("f", Part.text("v"))

    result = mp.to_async_body()

    assert result == snapshot(
        b'--B\r\nContent-Disposition: form-data; name="f"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nv\r\n--B--\r\n"
    )


def test_part_text_with_unicode():
    text = "Hello 世界 🌍"
    part = Part.text(text)

    assert isinstance(part.content, bytes)
    assert part.content == snapshot(b"Hello \xe4\xb8\x96\xe7\x95\x8c \xf0\x9f\x8c\x8d")
    assert part.content_type == snapshot("text/plain; charset=utf-8")


def test_multipart_text_with_unicode():
    mp = Multipart(boundary="unicode")
    mp.text("message", "Hello 世界")

    result = mp.to_body()

    assert result == snapshot(
        b'--unicode\r\nContent-Disposition: form-data; name="message"\r\n'
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello \xe4\xb8\x96\xe7\x95\x8c\r\n--unicode--\r\n"
    )


def test_escape_quoted_string_empty():
    result = _escape_quoted_string("")
    assert result == snapshot("")


def test_multipart_empty():
    mp = Multipart(boundary="empty")
    result = mp.to_body()

    assert result == snapshot(b"--empty--\r\n")


@pytest.mark.asyncio
async def test_async_multipart_empty():
    mp = Multipart(boundary="empty")
    result = mp.to_async_body()

    assert result == snapshot(b"--empty--\r\n")


def test_multipart_stream_assertion_on_wrong_stream_type():
    async_part = Part.async_stream(_TestAsyncStream(b"data"))
    parts = [("field", async_part)]
    stream = MultipartStream(parts, "boundary")

    with pytest.raises(
        AssertionError,
        match="Part content must be a Stream or bytes",
    ):
        list(stream)


@pytest.mark.asyncio
async def test_async_multipart_stream_assertion_on_wrong_stream_type():
    sync_part = Part.stream(_TestSyncStream(b"data"))
    parts = [("field", sync_part)]
    stream = MultipartStream(parts, "boundary")

    with pytest.raises(
        AssertionError,
        match="Part content must be an AsyncStream or bytes",
    ):
        async for _ in stream:
            pass


def test_multipart_stream_close_assertion_on_wrong_stream_type():
    async_part = Part.async_stream(_TestAsyncStream(b"data"))
    parts = [("field", async_part)]
    stream = MultipartStream(parts, "boundary")

    with pytest.raises(
        RuntimeError,
        match=re.escape("Part content is an AsyncStream, use aclose() to close it"),
    ):
        stream.close()


@pytest.mark.asyncio
async def test_async_multipart_stream_aclose_assertion_on_wrong_stream_type():
    sync_part = Part.stream(_TestSyncStream(b"data"))
    parts = [("field", sync_part)]
    stream = MultipartStream(parts, "boundary")

    with pytest.raises(
        RuntimeError,
        match=re.escape("Part content is a Stream, use close() to close it"),
    ):
        await stream.aclose()
