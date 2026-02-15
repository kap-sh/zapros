import pytest

from zapros import AsyncClient
from zapros._handlers._mock import Mock
from zapros._models import (
    Headers,
    Request,
    Response,
)
from zapros.matchers import method, path
from zapros.mock import mock_http


@pytest.mark.asyncio
async def test_verification_on_exit():
    with pytest.raises(
        AssertionError,
        match="expected 1 calls, got 0",
    ):
        with mock_http() as router:
            Mock().given(path("/api")).respond(Response(status=200)).once().mount(router)


@pytest.mark.asyncio
async def test_no_verification_on_exception():
    try:
        with mock_http() as router:
            Mock().given(path("/api")).respond(Response(status=200)).once().mount(router)
            raise RuntimeError("test error")
    except RuntimeError:
        pass


@pytest.mark.asyncio
async def test_multiple_mocks():
    with mock_http() as router:
        Mock().given(path("/users")).respond(Response(status=200, json=[{"id": 1}])).mount(router)
        Mock().given(path("/posts").method("POST")).respond(Response(status=201, json={"id": 1})).mount(router)
        Mock().given(path("/health")).respond(Response(status=200, text="OK")).mount(router)

        async with AsyncClient() as client:
            response = await client.get(
                "https://api.example.com/users",
            )
            assert response.status == 200
            assert response.json() == [{"id": 1}]

            response = await client.post(
                "https://api.example.com/posts",
                json={"title": "Test"},
            )
            assert response.status == 201
            assert response.json() == {"id": 1}

            response = await client.get(
                "https://api.example.com/health",
            )
            assert response.status == 200
            assert response.text() == "OK"


@pytest.mark.asyncio
async def test_context_manager_with_headers():
    with mock_http() as router:
        Mock().given(path("/api").header("x-api-key", "secret")).respond(
            Response(
                status=200,
                json={"authenticated": True},
            )
        ).mount(router)

        async with AsyncClient() as client:
            headers = Headers({"x-api-key": "secret"})
            response = await client.get(
                "https://api.example.com/api",
                headers=headers,
            )
            assert response.status == 200
            assert response.json() == {"authenticated": True}


@pytest.mark.asyncio
async def test_context_manager_with_query():
    with mock_http() as router:
        Mock().given(path("/search").query(q="test", page="1")).respond(
            Response(
                status=200,
                json={"results": []},
            )
        ).mount(router)

        async with AsyncClient() as client:
            response = await client.get(
                "https://api.example.com/search?q=test&page=1",
            )
            assert response.status == 200
            assert response.json() == {"results": []}


@pytest.mark.asyncio
async def test_context_manager_first_match_wins():
    with mock_http() as router:
        Mock().given(path("/api")).respond(Response(status=200, text="First")).mount(router)
        Mock().given(path("/api")).respond(Response(status=200, text="Second")).mount(router)

        async with AsyncClient() as client:
            response = await client.get(
                "https://api.example.com/api",
            )
            assert response.status == 200
            assert response.text() == "First"


@pytest.mark.asyncio
async def test_callback_in_context():
    def custom_handler(req: Request):
        from zapros._models import (
            Response,
        )

        status = 404 if req.url.pathname == "/notfound" else 200
        return Response(
            status=status,
            headers=Headers({}),
            content=None,
        )

    with mock_http() as router:
        Mock().given(method("GET")).callback(custom_handler).mount(router)

        async with AsyncClient() as client:
            response = await client.get(
                "https://api.example.com/found",
            )
            assert response.status == 200

            response = await client.get(
                "https://api.example.com/notfound",
            )
            assert response.status == 404


@pytest.mark.asyncio
async def test_expect_verification():
    with mock_http() as router:
        Mock().given(path("/api")).respond(Response(status=200)).expect(2).mount(router)

        async with AsyncClient() as client:
            await client.get(
                "https://api.example.com/api",
            )
            await client.get(
                "https://api.example.com/api",
            )


@pytest.mark.asyncio
async def test_expect_verification_failure():
    with pytest.raises(
        AssertionError,
        match="API Mock: expected 3 calls, got 2",
    ):
        with mock_http() as router:
            Mock().given(path("/api")).respond(Response(status=200)).expect(3).mount(router).name("API Mock")

            async with AsyncClient() as client:
                await client.get(
                    "https://api.example.com/api",
                )
                await client.get(
                    "https://api.example.com/api",
                )


@pytest.mark.asyncio
async def test_never_expectation():
    with mock_http() as router:
        Mock().given(path("/api")).respond(Response(status=200)).never().mount(router)


@pytest.mark.asyncio
async def test_never_expectation_failure():
    with pytest.raises(
        AssertionError,
        match="expected 0 calls, got 1",
    ):
        with mock_http() as router:
            Mock().given(path("/api")).respond(Response(status=200)).never().mount(router)

            async with AsyncClient() as client:
                await client.get(
                    "https://api.example.com/api",
                )


@pytest.mark.asyncio
async def test_different_methods():
    with mock_http() as router:
        Mock().given(path("/api").method("GET")).respond(
            Response(
                status=200,
                json={"method": "GET"},
            )
        ).mount(router)
        Mock().given(path("/api").method("POST")).respond(
            Response(
                status=201,
                json={"method": "POST"},
            )
        ).mount(router)
        Mock().given(path("/api").method("PUT")).respond(
            Response(
                status=200,
                json={"method": "PUT"},
            )
        ).mount(router)
        Mock().given(path("/api").method("DELETE")).respond(Response(status=204)).mount(router)

        async with AsyncClient() as client:
            response = await client.get(
                "https://api.example.com/api",
            )
            assert response.status == 200
            assert response.json() == {"method": "GET"}

            response = await client.post(
                "https://api.example.com/api",
                json={},
            )
            assert response.status == 201
            assert response.json() == {"method": "POST"}

            response = await client.put(
                "https://api.example.com/api",
                json={},
            )
            assert response.status == 200
            assert response.json() == {"method": "PUT"}

            response = await client.request(
                "DELETE",
                "https://api.example.com/api",
            )
            assert response.status == 204


@pytest.mark.asyncio
async def test_different_hosts():
    with mock_http() as router:
        from zapros.matchers import host

        Mock().given(host("api1.example.com").path("/data")).respond(
            Response(
                status=200,
                json={"host": "api1"},
            )
        ).mount(router)
        Mock().given(host("api2.example.com").path("/data")).respond(
            Response(
                status=200,
                json={"host": "api2"},
            )
        ).mount(router)

        async with AsyncClient() as client:
            response = await client.get(
                "https://api1.example.com/data",
            )
            assert response.status == 200
            assert response.json() == {"host": "api1"}

            response = await client.get(
                "https://api2.example.com/data",
            )
            assert response.status == 200
            assert response.json() == {"host": "api2"}
