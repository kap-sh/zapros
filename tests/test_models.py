import gzip
import json as json_module
import zlib
from typing import AsyncIterator, Iterator

import pytest
from pywhatwgurl import URL

from zapros import (
    AsyncClosableStream,
    AsyncSyncMismatchError,
    ClosableStream,
    Headers,
    Request,
    RequestContext,
    Response,
    ResponseContext,
)
from zapros._errors import StatusCodeError


class StreamWrapper(ClosableStream):
    def __init__(self, iterator: Iterator[bytes]) -> None:
        self._iterator = iterator
        self._closed = False

    def __iter__(self) -> "StreamWrapper":
        return self

    def __next__(self) -> bytes:
        return next(self._iterator)

    def close(self) -> None:
        self._closed = True


class AsyncStreamWrapper(AsyncClosableStream):
    def __init__(self, generator: AsyncIterator[bytes]) -> None:
        self._generator = generator
        self._closed = False

    def __aiter__(self) -> "AsyncStreamWrapper":
        return self

    async def __anext__(self) -> bytes:
        return await self._generator.__anext__()

    async def aclose(self) -> None:
        self._closed = True


class TestHeaders:
    def test_headers_construction_empty(self):
        headers = Headers()
        assert len(headers) == 0

    def test_headers_construction_from_dict(self):
        headers = Headers({"Content-Type": "application/json"})
        assert headers["Content-Type"] == "application/json"
        assert len(headers) == 1

    def test_headers_construction_from_list_of_tuples(self):
        headers = Headers([("Content-Type", "application/json"), ("Accept", "*/*")])
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "*/*"
        assert len(headers) == 2

    def test_headers_construction_from_headers_instance(self):
        original = Headers({"Content-Type": "application/json"})
        headers = Headers(original)
        assert headers["Content-Type"] == "application/json"
        assert len(headers) == 1

    def test_headers_getitem(self):
        headers = Headers({"Content-Type": "application/json"})
        assert headers["Content-Type"] == "application/json"

    def test_headers_getitem_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        assert headers["content-type"] == "application/json"
        assert headers["CONTENT-TYPE"] == "application/json"

    def test_headers_getitem_missing_raises_keyerror(self):
        headers = Headers()
        with pytest.raises(KeyError):
            _ = headers["Missing-Header"]

    def test_headers_setitem(self):
        headers = Headers()
        headers["Content-Type"] = "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_headers_setitem_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        headers["content-type"] = "text/plain"
        assert headers["Content-Type"] == "text/plain"
        assert len(headers) == 1

    def test_headers_setitem_replaces_existing(self):
        headers = Headers({"Content-Type": "application/json"})
        headers["Content-Type"] = "text/plain"
        assert headers["Content-Type"] == "text/plain"

    def test_headers_delitem(self):
        headers = Headers({"Content-Type": "application/json"})
        del headers["Content-Type"]
        assert len(headers) == 0

    def test_headers_delitem_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        del headers["content-type"]
        assert len(headers) == 0

    def test_headers_delitem_missing_raises_keyerror(self):
        headers = Headers()
        with pytest.raises(KeyError):
            del headers["Missing-Header"]

    def test_headers_contains(self):
        headers = Headers({"Content-Type": "application/json"})
        assert "Content-Type" in headers
        assert "Missing-Header" not in headers

    def test_headers_contains_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        assert "content-type" in headers
        assert "CONTENT-TYPE" in headers

    def test_headers_iter(self):
        headers = Headers({"Content-Type": "application/json", "Accept": "*/*"})
        keys = list(headers)
        assert len(keys) == 2
        assert "Content-Type" in keys or "content-type" in keys
        assert "Accept" in keys or "accept" in keys

    def test_headers_len(self):
        headers = Headers()
        assert len(headers) == 0
        headers["Content-Type"] = "application/json"
        assert len(headers) == 1
        headers["Accept"] = "*/*"
        assert len(headers) == 2

    def test_headers_repr(self):
        headers = Headers({"Content-Type": "application/json"})
        repr_str = repr(headers)
        assert "Headers" in repr_str
        assert "Content-Type" in repr_str or "content-type" in repr_str

    def test_headers_get_with_default(self):
        headers = Headers({"Content-Type": "application/json"})
        assert headers.get("Content-Type") == "application/json"
        assert headers.get("Missing-Header") is None
        assert headers.get("Missing-Header", "default") == "default"

    def test_headers_get_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        assert headers.get("content-type") == "application/json"

    def test_headers_getall(self):
        headers = Headers([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])
        cookies = headers.getall("Set-Cookie")
        assert len(cookies) == 2
        assert "a=1" in cookies
        assert "b=2" in cookies

    def test_headers_getall_case_insensitive(self):
        headers = Headers([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])
        cookies = headers.getall("set-cookie")
        assert len(cookies) == 2

    def test_headers_getall_single_value(self):
        headers = Headers({"Content-Type": "application/json"})
        values = headers.getall("Content-Type")
        assert values == ["application/json"]

    def test_headers_add(self):
        headers = Headers()
        headers.add("Set-Cookie", "a=1")
        headers.add("Set-Cookie", "b=2")
        cookies = headers.getall("Set-Cookie")
        assert len(cookies) == 2

    def test_headers_add_case_insensitive(self):
        headers = Headers()
        headers.add("Set-Cookie", "a=1")
        headers.add("set-cookie", "b=2")
        cookies = headers.getall("Set-Cookie")
        assert len(cookies) == 2

    def test_headers_extend_from_dict(self):
        headers = Headers()
        headers.extend({"Content-Type": "application/json", "Accept": "*/*"})
        assert len(headers) == 2

    def test_headers_extend_from_list(self):
        headers = Headers()
        headers.extend([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])
        cookies = headers.getall("Set-Cookie")
        assert len(cookies) == 2

    def test_headers_pop_with_default(self):
        headers = Headers({"Content-Type": "application/json"})
        value = headers.pop("Content-Type")
        assert value == "application/json"
        assert len(headers) == 0

    def test_headers_pop_with_default_value(self):
        headers = Headers()
        value = headers.pop("Missing-Header", "default")
        assert value == "default"

    def test_headers_pop_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        value = headers.pop("content-type")
        assert value == "application/json"

    def test_headers_popitem(self):
        headers = Headers({"Content-Type": "application/json"})
        key, value = headers.popitem()
        assert key.lower() == "content-type"
        assert value == "application/json"
        assert len(headers) == 0

    def test_headers_popitem_empty_raises_keyerror(self):
        headers = Headers()
        with pytest.raises(KeyError):
            headers.popitem()

    def test_headers_clear(self):
        headers = Headers({"Content-Type": "application/json", "Accept": "*/*"})
        headers.clear()
        assert len(headers) == 0

    def test_headers_setdefault_new_key(self):
        headers = Headers()
        value = headers.setdefault("Content-Type", "application/json")
        assert value == "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_headers_setdefault_existing_key(self):
        headers = Headers({"Content-Type": "application/json"})
        value = headers.setdefault("Content-Type", "text/plain")
        assert value == "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_headers_setdefault_case_insensitive(self):
        headers = Headers({"Content-Type": "application/json"})
        value = headers.setdefault("content-type", "text/plain")
        assert value == "application/json"

    def test_headers_update_from_dict(self):
        headers = Headers()
        headers.update({"Content-Type": "application/json", "Accept": "*/*"})
        assert len(headers) == 2

    def test_headers_update_from_list(self):
        headers = Headers()
        headers.update([("Content-Type", "application/json"), ("Accept", "*/*")])
        assert len(headers) == 2

    def test_headers_copy(self):
        headers = Headers({"Content-Type": "application/json"})
        copied = headers.copy()
        assert copied["Content-Type"] == "application/json"
        copied["Accept"] = "*/*"
        assert "Accept" not in headers

    def test_headers_list(self):
        headers = Headers({"Content-Type": "application/json", "Accept": "*/*"})
        header_list = headers.list()
        assert len(header_list) == 2
        assert any(k.lower() == "content-type" and v == "application/json" for k, v in header_list)
        assert any(k.lower() == "accept" and v == "*/*" for k, v in header_list)

    def test_headers_keys(self):
        headers = Headers({"Content-Type": "application/json", "Accept": "*/*"})
        keys = list(headers.keys())
        assert len(keys) == 2

    def test_headers_values(self):
        headers = Headers({"Content-Type": "application/json", "Accept": "*/*"})
        values = list(headers.values())
        assert len(values) == 2
        assert "application/json" in values
        assert "*/*" in values

    def test_headers_items(self):
        headers = Headers({"Content-Type": "application/json"})
        items = list(headers.items())
        assert len(items) == 1
        key, value = items[0]
        assert key.lower() == "content-type"
        assert value == "application/json"


class TestRequest:
    def test_request_minimal(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert request.url == url
        assert request.method == "GET"
        assert request.body is None
        assert request.context == {}

    def test_request_json_parameter(self):
        url = URL("http://example.com/path")
        data = {"key": "value"}
        request = Request(url, "POST", json=data)
        assert isinstance(request.body, bytes)
        assert json_module.loads(request.body) == data
        assert request.headers["Content-Type"] == "application/json"
        assert "Content-Length" in request.headers

    def test_request_json_sets_content_type(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", json={"key": "value"})
        assert request.headers["Content-Type"] == "application/json"

    def test_request_json_does_not_override_content_type(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", headers={"Content-Type": "custom"}, json={"key": "value"})
        assert request.headers["Content-Type"] == "custom"

    def test_request_form_parameter(self):
        url = URL("http://example.com/path")
        form_data = {"key": "value", "name": "test"}
        request = Request(url, "POST", form=form_data)
        assert isinstance(request.body, bytes)
        assert b"key=value" in request.body
        assert b"name=test" in request.body
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert "Content-Length" in request.headers

    def test_request_form_does_not_override_content_type(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", headers={"Content-Type": "custom"}, form={"key": "value"})
        assert request.headers["Content-Type"] == "custom"

    def test_request_text_parameter(self):
        url = URL("http://example.com/path")
        text = "Hello, World!"
        request = Request(url, "POST", text=text)
        assert request.body == text.encode("utf-8")
        assert request.headers["Content-Type"] == "text/plain; charset=utf-8"
        assert "Content-Length" in request.headers

    def test_request_text_does_not_override_content_type(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", headers={"Content-Type": "custom"}, text="Hello")
        assert request.headers["Content-Type"] == "custom"

    def test_request_body_bytes(self):
        url = URL("http://example.com/path")
        body = b"raw bytes"
        request = Request(url, "POST", body=body)
        assert request.body == body
        assert request.headers["Content-Length"] == str(len(body))

    def test_request_body_bytes_does_not_override_content_length(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", headers={"Content-Length": "999"}, body=b"test")
        assert request.headers["Content-Length"] == "999"

    def test_request_body_iterator(self):
        url = URL("http://example.com/path")
        body = iter([b"chunk1", b"chunk2"])
        request = Request(url, "POST", body=body)
        assert request.body == body
        assert request.headers["Transfer-Encoding"] == "chunked"

    def test_request_body_iterator_does_not_override_transfer_encoding(self):
        url = URL("http://example.com/path")
        body = iter([b"chunk1"])
        request = Request(url, "POST", headers={"Transfer-Encoding": "custom"}, body=body)
        assert request.headers["Transfer-Encoding"] == "custom"

    def test_request_body_async_iterator(self):
        url = URL("http://example.com/path")

        async def body_gen():
            yield b"chunk1"

        request = Request(url, "POST", body=body_gen())
        assert request.headers["Transfer-Encoding"] == "chunked"

    def test_request_no_body_parameter(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert request.body is None
        assert "Content-Length" not in request.headers
        assert "Transfer-Encoding" not in request.headers

    def test_request_host_header_from_url(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert request.headers["Host"] == "example.com"

    def test_request_host_header_not_overridden(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET", headers={"Host": "custom.com"})
        assert request.headers["Host"] == "custom.com"

    def test_request_host_header_case_insensitive_check(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET", headers={"host": "custom.com"})
        assert request.headers.get("Host") == "custom.com"
        host_values = request.headers.getall("Host")
        assert len(host_values) == 1

    def test_request_accept_header_default(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert request.headers["Accept"] == "*/*"

    def test_request_accept_header_not_overridden(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET", headers={"Accept": "application/json"})
        assert request.headers["Accept"] == "application/json"

    def test_request_user_agent_header_default(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert "User-Agent" in request.headers
        assert "zapros" in request.headers["User-Agent"].lower()

    def test_request_user_agent_header_not_overridden(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET", headers={"User-Agent": "custom-agent"})
        assert request.headers["User-Agent"] == "custom-agent"

    def test_request_accept_encoding_header_default(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert "Accept-Encoding" in request.headers

    def test_request_accept_encoding_header_not_overridden(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET", headers={"Accept-Encoding": "gzip"})
        assert request.headers["Accept-Encoding"] == "gzip"

    def test_request_is_replayable_none_body(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert request.is_replayable() is True

    def test_request_is_replayable_bytes_body(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", body=b"data")
        assert request.is_replayable() is True

    def test_request_is_replayable_sync_stream(self):
        url = URL("http://example.com/path")
        request = Request(url, "POST", body=iter([b"chunk"]))
        assert request.is_replayable() is False

    def test_request_is_replayable_async_stream(self):
        url = URL("http://example.com/path")

        async def body_gen():
            yield b"chunk"

        request = Request(url, "POST", body=body_gen())
        assert request.is_replayable() is False

    def test_request_context_default(self):
        url = URL("http://example.com/path")
        request = Request(url, "GET")
        assert request.context == {}

    def test_request_context_provided(self):
        url = URL("http://example.com/path")
        context: RequestContext = {"timeouts": {"connect": 5.0}}
        request = Request(url, "GET", context=context)
        assert request.context == context


class TestResponse:
    def test_response_minimal(self):
        response = Response(200)
        assert response.status == 200
        assert len(response.headers) == 0
        assert response.content is None
        assert response.context == {}

    def test_response_with_headers_dict(self):
        response = Response(200, headers={"Content-Type": "application/json"})
        assert response.headers["Content-Type"] == "application/json"

    def test_response_with_headers_list(self):
        response = Response(200, headers=[("Content-Type", "application/json"), ("Accept", "*/*")])
        assert response.headers["Content-Type"] == "application/json"
        assert response.headers["Accept"] == "*/*"

    def test_response_with_headers_instance(self):
        headers = Headers({"Content-Type": "application/json"})
        response = Response(200, headers=headers)
        assert response.headers["Content-Type"] == "application/json"

    def test_response_content_bytes(self):
        content = b"Hello, World!"
        response = Response(200, content=content)
        assert response.content == content

    def test_response_content_sync_stream(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        assert response.content == stream

    def test_response_content_async_stream(self):
        async def gen():
            yield b"chunk1"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        assert response.content == stream

    def test_response_text_parameter(self):
        response = Response(200, text="Hello, World!")
        assert response.content == b"Hello, World!"
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
        assert "Content-Encoding" not in response.headers

    def test_response_text_strips_content_encoding(self):
        response = Response(200, headers={"Content-Encoding": "gzip"}, text="Hello, World!")
        assert "Content-Encoding" not in response.headers

    def test_response_text_does_not_override_content_type(self):
        response = Response(200, headers={"Content-Type": "custom"}, text="Hello, World!")
        assert response.headers["Content-Type"] == "custom"

    def test_response_json_data_parameter(self):
        data = {"key": "value"}
        response = Response(200, json=data)
        assert isinstance(response.content, bytes)
        assert json_module.loads(response.content) == data
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        assert "Content-Encoding" not in response.headers

    def test_response_json_data_strips_content_encoding(self):
        response = Response(200, headers={"Content-Encoding": "gzip"}, json={"key": "value"})
        assert "Content-Encoding" not in response.headers

    def test_response_multiple_body_parameters_raises_valueerror(self):
        with pytest.raises(ValueError) as exc_info:
            Response(200, content=b"data", text="text")  # type: ignore
        assert "Only one of" in str(exc_info.value)

    def test_response_context_default(self):
        response = Response(200)
        assert response.context == {}

    def test_response_context_provided(self):
        context: ResponseContext = {"caching": {"from_cache": True}}
        response = Response(200, context=context)
        assert response.context == context

    def test_response_read_bytes(self):
        response = Response(200, content=b"Hello, World!")
        content = response.read()
        assert content == b"Hello, World!"

    def test_response_read_sync_stream(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        content = response.read()
        assert content == b"chunk1chunk2"

    def test_response_read_none_content(self):
        response = Response(200)
        content = response.read()
        assert content == b""

    def test_response_read_caches_content(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        content1 = response.read()
        content2 = response.read()
        assert content1 == content2
        assert content1 is content2

    @pytest.mark.asyncio
    async def test_response_aread_bytes(self):
        response = Response(200, content=b"Hello, World!")
        content = await response.aread()
        assert content == b"Hello, World!"

    @pytest.mark.asyncio
    async def test_response_aread_async_stream(self):
        async def gen():
            yield b"chunk1"
            yield b"chunk2"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        content = await response.aread()
        assert content == b"chunk1chunk2"

    @pytest.mark.asyncio
    async def test_response_aread_none_content(self):
        response = Response(200)
        content = await response.aread()
        assert content == b""

    @pytest.mark.asyncio
    async def test_response_aread_caches_content(self):
        async def gen():
            yield b"chunk1"
            yield b"chunk2"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        content1 = await response.aread()
        content2 = await response.aread()
        assert content1 == content2
        assert content1 is content2

    def test_response_text_method(self):
        response = Response(200, content=b"Hello, World!")
        text = response.text
        assert text == "Hello, World!"

    def test_response_text_with_encoding(self):
        response = Response(
            200,
            headers={"Content-Type": "text/plain; charset=latin-1"},
            content="Hëllo".encode("latin-1"),
        )
        text = response.text
        assert text == "Hëllo"

    def test_response_json_method(self):
        data = {"key": "value"}
        response = Response(200, content=json_module.dumps(data).encode("utf-8"))
        result = response.json
        assert result == data

    def test_response_encoding_from_content_type(self):
        response = Response(200, headers={"Content-Type": "text/html; charset=latin-1"})
        assert response.encoding == "latin-1"

    def test_response_encoding_default_utf8(self):
        response = Response(200)
        assert response.encoding == "utf-8"

    def test_response_encoding_no_content_type(self):
        response = Response(200, headers={})
        assert response.encoding == "utf-8"

    def test_response_iter_bytes_from_bytes(self):
        response = Response(200, content=b"Hello, World!")
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == b"Hello, World!"

    def test_response_iter_bytes_from_stream(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == b"chunk1chunk2"

    def test_response_iter_bytes_none_content(self):
        response = Response(200)
        chunks = list(response.iter_bytes())
        assert chunks == []

    def test_response_iter_bytes_custom_chunk_size(self):
        response = Response(200, content=b"Hello, World!")
        chunks = list(response.iter_bytes(chunk_size=5))
        assert all(len(chunk) <= 5 for chunk in chunks)

    def test_response_iter_bytes_gzip_decompression(self):
        original = b"Hello, World!"
        compressed = gzip.compress(original)
        stream = StreamWrapper(iter([compressed]))
        response = Response(200, headers={"Content-Encoding": "gzip"}, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == original

    def test_response_iter_bytes_deflate_decompression(self):
        original = b"Hello, World!"
        compressed = zlib.compress(original)
        stream = StreamWrapper(iter([compressed]))
        response = Response(200, headers={"Content-Encoding": "deflate"}, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == original

    def test_response_iter_bytes_multiple_encodings(self):
        original = b"Hello, World!"
        compressed_gzip = gzip.compress(original)
        compressed_deflate = zlib.compress(compressed_gzip)
        stream = StreamWrapper(iter([compressed_deflate]))
        response = Response(200, headers={"Content-Encoding": "gzip, deflate"}, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == original

    def test_response_iter_bytes_case_insensitive_encoding(self):
        original = b"Hello, World!"
        compressed = gzip.compress(original)
        stream = StreamWrapper(iter([compressed]))
        response = Response(200, headers={"Content-Encoding": "GZIP"}, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == original

    def test_response_iter_bytes_unknown_encoding(self):
        original = b"Hello, World!"
        stream = StreamWrapper(iter([original]))
        response = Response(200, headers={"Content-Encoding": "unknown"}, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == original

    def test_response_iter_bytes_identity_encoding(self):
        original = b"Hello, World!"
        stream = StreamWrapper(iter([original]))
        response = Response(200, headers={"Content-Encoding": "identity"}, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == original

    def test_response_iter_bytes_async_stream_raises_typeerror(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        with pytest.raises(AsyncSyncMismatchError) as exc_info:
            list(response.iter_bytes())
        assert "using `async_iter_bytes`" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_response_async_iter_bytes_from_bytes(self):
        response = Response(200, content=b"Hello, World!")
        chunks = [chunk async for chunk in response.async_iter_bytes()]
        result = b"".join(chunks)
        assert result == b"Hello, World!"

    @pytest.mark.asyncio
    async def test_response_async_iter_bytes_from_async_stream(self):
        async def gen():
            yield b"chunk1"
            yield b"chunk2"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        chunks = [chunk async for chunk in response.async_iter_bytes()]
        result = b"".join(chunks)
        assert result == b"chunk1chunk2"

    @pytest.mark.asyncio
    async def test_response_async_iter_bytes_none_content(self):
        response = Response(200)
        chunks = [chunk async for chunk in response.async_iter_bytes()]
        assert chunks == []

    @pytest.mark.asyncio
    async def test_response_async_iter_bytes_custom_chunk_size(self):
        response = Response(200, content=b"Hello, World!")
        chunks = [chunk async for chunk in response.async_iter_bytes(chunk_size=5)]
        assert all(len(chunk) <= 5 for chunk in chunks)

    @pytest.mark.asyncio
    async def test_response_async_iter_bytes_gzip_decompression(self):
        original = b"Hello, World!"
        compressed = gzip.compress(original)

        async def gen():
            yield compressed

        stream = AsyncStreamWrapper(gen())
        response = Response(200, headers={"Content-Encoding": "gzip"}, content=stream)
        chunks = [chunk async for chunk in response.async_iter_bytes()]
        result = b"".join(chunks)
        assert result == original

    @pytest.mark.asyncio
    async def test_response_async_iter_bytes_sync_stream_raises_typeerror(self):
        stream = StreamWrapper(iter([b"chunk"]))
        response = Response(200, content=stream)
        with pytest.raises(AsyncSyncMismatchError) as exc_info:
            async for _ in response.async_iter_bytes():
                pass
        assert "using `iter_bytes`" in str(exc_info.value)

    def test_response_iter_raw_from_bytes(self):
        response = Response(200, content=b"Hello, World!")
        chunks = list(response.iter_raw())
        result = b"".join(chunks)
        assert result == b"Hello, World!"

    def test_response_iter_raw_from_stream(self):
        original = b"Hello, World!"
        compressed = gzip.compress(original)
        stream = StreamWrapper(iter([compressed]))
        response = Response(200, headers={"Content-Encoding": "gzip"}, content=stream)
        chunks = list(response.iter_raw())
        result = b"".join(chunks)
        assert result == compressed

    def test_response_iter_raw_none_content(self):
        response = Response(200)
        chunks = list(response.iter_raw())
        assert chunks == []

    def test_response_iter_raw_async_stream_raises_typeerror(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        with pytest.raises(AsyncSyncMismatchError) as exc_info:
            list(response.iter_raw())
        assert "using `async_iter_raw`" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_response_async_iter_raw_from_bytes(self):
        response = Response(200, content=b"Hello, World!")
        chunks = [chunk async for chunk in response.async_iter_raw()]
        result = b"".join(chunks)
        assert result == b"Hello, World!"

    @pytest.mark.asyncio
    async def test_response_async_iter_raw_from_async_stream(self):
        original = b"Hello, World!"
        compressed = gzip.compress(original)

        async def gen():
            yield compressed

        stream = AsyncStreamWrapper(gen())
        response = Response(200, headers={"Content-Encoding": "gzip"}, content=stream)
        chunks = [chunk async for chunk in response.async_iter_raw()]
        result = b"".join(chunks)
        assert result == compressed

    @pytest.mark.asyncio
    async def test_response_async_iter_raw_none_content(self):
        response = Response(200)
        chunks = [chunk async for chunk in response.async_iter_raw()]
        assert chunks == []

    @pytest.mark.asyncio
    async def test_response_async_iter_raw_sync_stream_raises_typeerror(self):
        stream = StreamWrapper(iter([b"chunk"]))
        response = Response(200, content=stream)
        with pytest.raises(AsyncSyncMismatchError) as exc_info:
            async for _ in response.async_iter_raw():
                pass
        assert "using `iter_raw`" in str(exc_info.value)

    def test_response_iter_text_from_bytes(self):
        response = Response(200, content=b"Hello, World!")
        chunks = list(response.iter_text())
        result = "".join(chunks)
        assert result == "Hello, World!"

    def test_response_iter_text_with_encoding(self):
        response = Response(
            200,
            headers={"Content-Type": "text/plain; charset=latin-1"},
            content="Hëllo".encode("latin-1"),
        )
        chunks = list(response.iter_text())
        result = "".join(chunks)
        assert result == "Hëllo"

    def test_response_iter_text_custom_chunk_size(self):
        response = Response(200, content=b"Hello, World!")
        chunks = list(response.iter_text(chunk_size=5))
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_response_async_iter_text_from_bytes(self):
        response = Response(200, content=b"Hello, World!")
        chunks = [chunk async for chunk in response.async_iter_text()]
        result = "".join(chunks)
        assert result == "Hello, World!"

    def test_response_read_then_iterate(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        content = response.read()
        assert content == b"chunk1chunk2"
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == b"chunk1chunk2"

    def test_response_iterate_then_read(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        chunks = list(response.iter_bytes())
        result = b"".join(chunks)
        assert result == b"chunk1chunk2"
        content = response.read()
        assert content == b"chunk1chunk2"

    def test_response_close_bytes_content(self):
        response = Response(200, content=b"Hello, World!")
        response.close()

    def test_response_close_none_content(self):
        response = Response(200)
        response.close()

    def test_response_close_sync_stream(self):
        stream = StreamWrapper(iter([b"chunk"]))
        response = Response(200, content=stream)
        response.close()
        assert stream._closed is True

    def test_response_close_async_stream_raises_typeerror(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        with pytest.raises(AsyncSyncMismatchError) as exc_info:
            response.close()
        assert "use `aclose()`" in str(exc_info.value)

    def test_response_close_after_stream_consumed(self):
        stream = StreamWrapper(iter([b"chunk"]))
        response = Response(200, content=stream)
        response.read()
        response.close()

    def test_response_close_idempotent(self):
        stream = StreamWrapper(iter([b"chunk"]))
        response = Response(200, content=stream)
        response.close()
        response.close()

    @pytest.mark.asyncio
    async def test_response_aclose_bytes_content(self):
        response = Response(200, content=b"Hello, World!")
        await response.aclose()

    @pytest.mark.asyncio
    async def test_response_aclose_none_content(self):
        response = Response(200)
        await response.aclose()

    @pytest.mark.asyncio
    async def test_response_aclose_async_stream(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        await response.aclose()
        assert stream._closed is True

    @pytest.mark.asyncio
    async def test_response_aclose_sync_stream_raises_typeerror(self):
        stream = StreamWrapper(iter([b"chunk"]))
        response = Response(200, content=stream)
        with pytest.raises(AsyncSyncMismatchError) as exc_info:
            await response.aclose()
        assert "use `close()`" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_response_aclose_after_stream_consumed(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        await response.aread()
        await response.aclose()

    @pytest.mark.asyncio
    async def test_response_aclose_idempotent(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        response = Response(200, content=stream)
        await response.aclose()
        await response.aclose()

    def test_response_context_manager(self):
        stream = StreamWrapper(iter([b"chunk"]))
        with Response(200, content=stream):
            pass
        assert stream._closed is True

    @pytest.mark.asyncio
    async def test_response_async_context_manager(self):
        async def gen():
            yield b"chunk"

        stream = AsyncStreamWrapper(gen())
        async with Response(200, content=stream):
            pass
        assert stream._closed is True

    def test_response_stream_consumption_caching(self):
        stream = StreamWrapper(iter([b"chunk1", b"chunk2"]))
        response = Response(200, content=stream)
        list(response.iter_bytes())
        assert isinstance(response.content, bytes)

    def test_raise_for_status_with_success(self):
        response = Response(200)
        response.raise_for_status()

    def test_raise_for_status_with_client_error(self):
        response = Response(404)
        with pytest.raises(StatusCodeError) as exc_info:
            response.raise_for_status()
        assert exc_info.value.response == response
