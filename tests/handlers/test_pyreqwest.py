from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from tests.mock_server import MockServer

if TYPE_CHECKING:
    from pyreqwest.client import ClientBuilder, SyncClientBuilder
else:
    try:
        from pyreqwest.client import ClientBuilder, SyncClientBuilder
    except ImportError:
        ClientBuilder = None
        SyncClientBuilder = None

from zapros import (
    AsyncClient,
    AsyncPyreqwestHandler,
    Client,
    HandlerClosedError,
    PyreqwestHandler,
)

pytestmark = pytest.mark.skipif(
    SyncClientBuilder is None,
    reason="pyreqwest is not supported for python 3.10 and below",
)


@pytest.fixture(
    params=[
        "asyncio",
        ("asyncio", {"use_uvloop": True}),
    ]
)
def anyio_backend(request):
    """pyreqwest drives its own runtime and only integrates with asyncio."""
    return request.param


def test_concurrent_requests_with_shared_builder(
    mock_server: MockServer,
):
    """A handler built from a caller-provided builder must be safe to use from many threads at once."""
    thread_count = 16

    with Client(handler=PyreqwestHandler(client=SyncClientBuilder())) as client:

        def send(_: int) -> int:
            return client.get(f"{mock_server.url}/echo").status

        with ThreadPoolExecutor(thread_count) as executor:
            statuses = list(executor.map(send, range(thread_count)))

    assert statuses == [201] * thread_count


def test_request_after_close_raises_handler_closed(
    mock_server: MockServer,
):
    handler = PyreqwestHandler(client=SyncClientBuilder())
    client = Client(handler=handler)

    assert client.get(f"{mock_server.url}/echo").status == 201

    client.close()

    with pytest.raises(HandlerClosedError):
        client.get(f"{mock_server.url}/echo")


def test_close_is_idempotent(
    mock_server: MockServer,
):
    handler = PyreqwestHandler(client=SyncClientBuilder())
    handler.close()
    handler.close()


async def test_async_request_after_close_raises_handler_closed(
    mock_server: MockServer,
):
    handler = AsyncPyreqwestHandler(client=ClientBuilder())
    client = AsyncClient(handler=handler)

    response = await client.get(f"{mock_server.url}/echo")
    assert response.status == 201

    await client.aclose()

    with pytest.raises(HandlerClosedError):
        await client.get(f"{mock_server.url}/echo")
