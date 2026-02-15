import base64

import pytest

from zapros import AsyncClient, Client
from zapros._handlers._mock import (
    Mock,
    MockHandler,
    MockRouter,
)
from zapros._models import Response
from zapros.matchers import path


def test_bearer_token_sync():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer test-token",
        )
    ).respond(Response(status=200)).mount(router)

    with Client(
        handler=MockHandler(router),
        auth="test-token",
    ) as client:
        response = client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_bearer_token_async():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer test-token",
        )
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(
        handler=MockHandler(router),
        auth="test-token",
    ) as client:
        response = await client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


def test_basic_auth_sync():
    router = MockRouter()
    username = "user"
    password = "pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    with Client(
        handler=MockHandler(router),
        auth=(username, password),
    ) as client:
        response = client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_basic_auth_async():
    router = MockRouter()
    username = "user"
    password = "pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(
        handler=MockHandler(router),
        auth=(username, password),
    ) as client:
        response = await client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


def test_no_auth_sync():
    router = MockRouter()
    Mock.given(path("/api")).respond(Response(status=200)).mount(router)

    with Client(handler=MockHandler(router)) as client:
        response = client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_no_auth_async():
    router = MockRouter()
    Mock.given(path("/api")).respond(Response(status=200)).mount(router)

    async with AsyncClient(handler=MockHandler(router)) as client:
        response = await client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


def test_bearer_with_default_headers_sync():
    router = MockRouter()
    Mock.given(
        path("/api")
        .header(
            "authorization",
            "Bearer token123",
        )
        .header("x-custom", "value")
    ).respond(Response(status=200)).mount(router)

    with Client(
        handler=MockHandler(router),
        auth="token123",
        default_headers={"x-custom": "value"},
    ) as client:
        response = client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_bearer_with_default_headers_async():
    router = MockRouter()
    Mock.given(
        path("/api")
        .header(
            "authorization",
            "Bearer token123",
        )
        .header("x-custom", "value")
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(
        handler=MockHandler(router),
        auth="token123",
        default_headers={"x-custom": "value"},
    ) as client:
        response = await client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200


def test_with_handler_preserves_bearer_sync():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer my-token",
        )
    ).respond(Response(status=200)).mount(router)

    client = Client(
        handler=MockHandler(router),
        auth="my-token",
    )

    response = client.get(
        "https://api.example.com/api",
    )
    assert response.status == 200

    client.close()


@pytest.mark.asyncio
async def test_with_handler_preserves_bearer_async():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer my-token",
        )
    ).respond(Response(status=200)).mount(router)

    client = AsyncClient(
        handler=MockHandler(router),
        auth="my-token",
    )

    response = await client.get(
        "https://api.example.com/api",
    )
    assert response.status == 200

    await client.aclose()


def test_with_handler_preserves_basic_auth_sync():
    router = MockRouter()
    username = "user"
    password = "pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    client = Client(
        handler=MockHandler(router),
        auth=(username, password),
    )

    response = client.get(
        "https://api.example.com/api",
    )
    assert response.status == 200

    client.close()


@pytest.mark.asyncio
async def test_with_handler_preserves_basic_auth_async():
    router = MockRouter()
    username = "user"
    password = "pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    client = AsyncClient(
        handler=MockHandler(router),
        auth=(username, password),
    )

    response = await client.get(
        "https://api.example.com/api",
    )
    assert response.status == 200

    await client.aclose()


def test_per_request_bearer_sync():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer request-token",
        )
    ).respond(Response(status=200)).mount(router)

    with Client(handler=MockHandler(router)) as client:
        response = client.get(
            "https://api.example.com/api",
            auth="request-token",
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_per_request_bearer_async():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer request-token",
        )
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(handler=MockHandler(router)) as client:
        response = await client.get(
            "https://api.example.com/api",
            auth="request-token",
        )
        assert response.status == 200


def test_per_request_basic_auth_sync():
    router = MockRouter()
    username = "req_user"
    password = "req_pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    with Client(handler=MockHandler(router)) as client:
        response = client.get(
            "https://api.example.com/api",
            auth=(username, password),
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_per_request_basic_auth_async():
    router = MockRouter()
    username = "req_user"
    password = "req_pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(handler=MockHandler(router)) as client:
        response = await client.get(
            "https://api.example.com/api",
            auth=(username, password),
        )
        assert response.status == 200


def test_per_request_overrides_client_bearer_sync():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer request-token",
        )
    ).respond(Response(status=200)).mount(router)

    with Client(
        handler=MockHandler(router),
        auth="client-token",
    ) as client:
        response = client.get(
            "https://api.example.com/api",
            auth="request-token",
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_per_request_overrides_client_bearer_async():
    router = MockRouter()
    Mock.given(
        path("/api").header(
            "authorization",
            "Bearer request-token",
        )
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(
        handler=MockHandler(router),
        auth="client-token",
    ) as client:
        response = await client.get(
            "https://api.example.com/api",
            auth="request-token",
        )
        assert response.status == 200


def test_per_request_overrides_client_basic_auth_sync():
    router = MockRouter()
    username = "req_user"
    password = "req_pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    with Client(
        handler=MockHandler(router),
        auth=(
            "client_user",
            "client_pass",
        ),
    ) as client:
        response = client.get(
            "https://api.example.com/api",
            auth=(username, password),
        )
        assert response.status == 200


@pytest.mark.asyncio
async def test_per_request_overrides_client_basic_auth_async():
    router = MockRouter()
    username = "req_user"
    password = "req_pass"
    expected_credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    expected_header = f"Basic {expected_credentials}"

    Mock.given(
        path("/api").header(
            "authorization",
            expected_header,
        )
    ).respond(Response(status=200)).mount(router)

    async with AsyncClient(
        handler=MockHandler(router),
        auth=(
            "client_user",
            "client_pass",
        ),
    ) as client:
        response = await client.get(
            "https://api.example.com/api",
            auth=(username, password),
        )
        assert response.status == 200
