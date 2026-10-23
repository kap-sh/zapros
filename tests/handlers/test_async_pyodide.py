import gzip
import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pywhatwgurl import URL

from tests.mock_server import MockServer
from zapros import AsyncClient
from zapros._handlers import _async_pyodide as pyodide_module
from zapros._models import Request


class FakeJsError(Exception):
    name = "TypeError"


class FakeAbortController:
    signal = object()

    @classmethod
    def new(cls) -> "FakeAbortController":
        return cls()

    def abort(self) -> None:
        pass


class FakeEntriesIterator:
    def __init__(self) -> None:
        self.done = True
        self.value = None

    def next(self) -> "FakeEntriesIterator":
        return self


class FakeHeaders:
    def entries(self) -> FakeEntriesIterator:
        return FakeEntriesIterator()


class FakeJsResponse:
    status = 200
    headers = FakeHeaders()
    body = None


@pytest.fixture
def fetch_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_fetch(url: str, options: dict[str, Any]) -> FakeJsResponse:
        calls.append(options)
        # Browsers reject GET/HEAD requests that carry a body, even an empty one.
        if options["method"] in ("GET", "HEAD") and "body" in options:
            raise FakeJsError("Request with GET/HEAD method cannot have body.")
        return FakeJsResponse()

    class FakeObject:
        @staticmethod
        def fromEntries(value: Any) -> Any:
            return value

    monkeypatch.setattr(pyodide_module, "AbortController", FakeAbortController)
    monkeypatch.setattr(pyodide_module, "Object", FakeObject)
    monkeypatch.setattr(pyodide_module, "setTimeout", lambda cb, ms: 1)
    monkeypatch.setattr(pyodide_module, "clearTimeout", lambda timeout_id: None)
    monkeypatch.setattr(pyodide_module, "fetch", fake_fetch)
    monkeypatch.setattr(pyodide_module, "to_js", lambda value, **kwargs: value)
    return calls


@pytest.mark.anyio
async def test_get_with_empty_body_does_not_send_body(fetch_calls: list[dict[str, Any]]) -> None:
    handler = pyodide_module.AsyncPyodideHandler()
    request = Request(URL("https://example.com/"), "GET", body=b"")

    response = await handler.ahandle(request)

    assert response.status == 200
    assert "body" not in fetch_calls[0]


class FakeJsNull:
    """Mimics ``pyodide.ffi.jsnull``: a falsy, non-None singleton that JS null becomes in Pyodide >= 0.28."""

    def __bool__(self) -> bool:
        return False


@pytest.mark.anyio
async def test_null_body_is_treated_as_empty_stream(fetch_calls: list[dict[str, Any]]) -> None:
    class NullBodyResponse(FakeJsResponse):
        body = FakeJsNull()

    stream = pyodide_module.PyodideAsyncClosableStream(NullBodyResponse())

    assert [chunk async for chunk in stream] == []


@pytest.mark.anyio
async def test_chunked_transfer_encoding_is_not_forwarded_to_fetch(fetch_calls: list[dict[str, Any]]) -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"data"

    handler = pyodide_module.AsyncPyodideHandler()
    request = Request(URL("https://example.com/"), "PUT", body=body())
    assert request.headers["transfer-encoding"] == "chunked"

    await handler.ahandle(request)

    sent_headers = [k.lower() for k, _ in fetch_calls[0]["headers"]]
    assert "transfer-encoding" not in sent_headers
    assert fetch_calls[0]["body"] == b"data"


@pytest.mark.anyio
async def test_non_chunked_transfer_encoding_raises(fetch_calls: list[dict[str, Any]]) -> None:
    handler = pyodide_module.AsyncPyodideHandler()
    request = Request(
        URL("https://example.com/"),
        "PUT",
        headers={"Transfer-Encoding": "gzip, chunked"},
        body=b"data",
    )

    with pytest.raises(NotImplementedError, match="Transfer-Encoding"):
        await handler.ahandle(request)

    assert fetch_calls == []


# The tests below send real requests through the JS fetch API to the mock server,
# so they only run inside Pyodide (scripts/test-pyodide).
needs_fetch = pytest.mark.skipif(sys.platform != "emscripten", reason="needs Pyodide's fetch")


@needs_fetch
async def test_basic(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.get(f"{mock_server.url}/echo")
        assert response.status == 201
        assert "GET /echo HTTP/1.1" in response.text


@needs_fetch
async def test_json_body(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            json={"key": "value", "num": 42},
        )
        assert response.status == 201
        assert "POST /echo HTTP/1.1" in response.text
        assert "content-type: application/json" in response.text
        assert '{"key":"value","num":42}' in response.text


@needs_fetch
async def test_json_nested(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            json={"user": {"name": "alice", "age": 30}, "tags": ["a", "b"]},
        )
        assert response.status == 201
        assert '{"user":{"name":"alice","age":30},"tags":["a","b"]}' in response.text


@needs_fetch
async def test_form_body(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            form={"username": "alice", "password": "secret"},
        )
        assert response.status == 201
        assert "content-type: application/x-www-form-urlencoded" in response.text
        assert "username=alice&password=secret" in response.text


@needs_fetch
async def test_form_url_encoding(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            form={"message": "hello world"},
        )
        assert response.status == 201
        assert "message=hello+world" in response.text


@needs_fetch
async def test_bytes_body(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            body=b"raw binary data",
        )
        assert response.status == 201
        assert "raw binary data" in response.text


@needs_fetch
async def test_query_params(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.get(
            f"{mock_server.url}/echo",
            params={"q": "hello", "page": "1"},
        )
        assert response.status == 201
        assert "GET /echo HTTP/1.1" in response.text


@needs_fetch
async def test_custom_headers(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.get(
            f"{mock_server.url}/echo",
            headers={
                "X-Custom-Header": "my-value",
                "Authorization": "Bearer token123",
            },
        )
        assert response.status == 201
        assert "x-custom-header: my-value" in response.text
        assert "authorization: Bearer token123" in response.text


@needs_fetch
async def test_put_method(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.put(
            f"{mock_server.url}/echo",
            json={"name": "updated"},
        )
        assert response.status == 201
        assert "PUT /echo HTTP/1.1" in response.text
        assert '{"name":"updated"}' in response.text


@needs_fetch
async def test_delete_method(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        response = await client.request("DELETE", f"{mock_server.url}/echo")
        assert response.status == 201
        assert "DELETE /echo HTTP/1.1" in response.text


@needs_fetch
async def test_stream_context_manager(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        async with client.stream("GET", f"{mock_server.url}/echo") as response:
            assert response.status == 201
            await response.aread()
            assert "GET /echo HTTP/1.1" in response.text


@needs_fetch
async def test_stream_iter_bytes(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        async with client.stream("GET", f"{mock_server.url}/echo") as response:
            chunks = []
            async for chunk in response.async_iter_bytes():
                chunks.append(chunk)
            assert response.status == 201
            assert b"GET /echo HTTP/1.1" in b"".join(chunks)


@needs_fetch
async def test_stream_json_body(mock_server: MockServer) -> None:
    async with AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{mock_server.url}/echo",
            json={"stream": True},
        ) as response:
            await response.aread()
            assert response.status == 201
            assert '{"stream":true}' in response.text


@needs_fetch
@pytest.mark.xfail(reason="fetch auto-decodes gzip, raw bytes aren't exposed")
async def test_gzip_raw_bytes_unchanged(mock_server: MockServer) -> None:
    original = "hello from the server"

    async with AsyncClient() as client:
        async with client.stream("GET", f"{mock_server.url}/gzip", params={"data": original}) as response:
            chunks = []
            async for chunk in response.async_iter_raw():
                chunks.append(chunk)

    assert b"".join(chunks) == gzip.compress(original.encode())
