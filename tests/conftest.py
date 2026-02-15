from typing import AsyncIterator

import pytest
import pytest_asyncio

from tests.mock._base import MockBuilder
from tests.mock._mock_async import (
    AsyncMockServer,
)
from tests.mock._mock_sync import (
    MockServer,
)
from zapros._async_client import (
    AsyncClient,
)
from zapros._handlers._cookies import (
    CookieHandler,
)
from zapros._handlers._mock import (
    MockHandler,
    MockRouter,
)


@pytest_asyncio.fixture
async def async_mock_server():
    server = AsyncMockServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
def mock_server():
    server = MockServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def async_mock_builder(request, async_mock_server):
    builder = MockBuilder(
        async_mock_server,
        request.node.nodeid,
    )
    yield builder
    async_mock_server.clear_mocks(request.node.nodeid)


@pytest.fixture
def mock_builder(request, mock_server):
    builder = MockBuilder(mock_server, request.node.nodeid)
    yield builder
    mock_server.clear_mocks(request.node.nodeid)


@pytest_asyncio.fixture
async def async_mock_client() -> AsyncIterator[tuple[AsyncClient, MockRouter]]:
    router = MockRouter()
    mock_handler = MockHandler(router=router)
    cookie_handler = CookieHandler(mock_handler)
    async with AsyncClient(handler=cookie_handler) as client:
        yield client, router


@pytest_asyncio.fixture
async def async_mock_client_no_cookies() -> AsyncIterator[tuple[AsyncClient, MockRouter]]:
    router = MockRouter()
    mock_handler = MockHandler(router=router)
    async with AsyncClient(handler=mock_handler) as client:
        yield client, router
