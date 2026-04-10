from typing import AsyncIterator

import pytest

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
