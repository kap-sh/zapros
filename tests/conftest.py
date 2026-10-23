import sys
from typing import AsyncIterator

import pytest

if sys.platform == "emscripten":
    # Pyodide (scripts/test-pyodide) has no threads. Litestar's default logging
    # config starts a queue listener thread, so log to the console directly.
    from litestar.logging import config as _litestar_logging_config

    _litestar_logging_config.default_handlers["queue_listener"] = _litestar_logging_config.default_handlers["console"]

    # Pyodide's event loop is the JS one and always reports itself as running, which
    # trips anyio's re-entrancy guard on every async fixture.
    from anyio._backends._asyncio import TestRunner as _AsyncioTestRunner

    _AsyncioTestRunner.is_running = lambda self: False  # type: ignore[method-assign]

from tests.mock_server import MockServer
from zapros._async_client import (
    AsyncClient,
)
from zapros._handlers._cookies import (
    CookieMiddleware,
)
from zapros._handlers._mock import (
    MockMiddleware,
    MockRouter,
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if sys.platform == "emscripten":
        skip = pytest.mark.skip(reason="does not run on Pyodide (no_pyodide marker)")
        for item in items:
            if "no_pyodide" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(
    # trio and uvloop do not run on Pyodide
    params=["asyncio"]
    if sys.platform == "emscripten"
    else [
        "asyncio",
        ("asyncio", {"use_uvloop": True}),
        "trio",
    ]
)
def anyio_backend(request):
    return request.param


@pytest.fixture(scope="session")
def mock_server():
    server = MockServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
async def async_mock_client() -> AsyncIterator[tuple[AsyncClient, MockRouter]]:
    router = MockRouter()
    mock_handler = MockMiddleware(router=router)
    cookie_handler = CookieMiddleware(mock_handler)
    async with AsyncClient(handler=cookie_handler) as client:
        yield client, router


@pytest.fixture
async def async_mock_client_no_cookies() -> AsyncIterator[tuple[AsyncClient, MockRouter]]:
    router = MockRouter()
    mock_handler = MockMiddleware(router=router)
    async with AsyncClient(handler=mock_handler) as client:
        yield client, router
