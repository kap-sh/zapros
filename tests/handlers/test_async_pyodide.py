from collections.abc import AsyncIterator
from typing import Any

import pytest
from pywhatwgurl import URL

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
