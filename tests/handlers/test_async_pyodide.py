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
