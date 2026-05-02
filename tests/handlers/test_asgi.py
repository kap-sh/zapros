import pytest
from inline_snapshot import snapshot
from litestar import (
    Litestar,
    Response,
    WebSocket,
    get,
    post,
    websocket,
)
from litestar.datastructures import (
    State,
)
from litestar.response import Stream
from pywhatwgurl import URL

from zapros import AsyncClient
from zapros._compat import anysleep
from zapros._errors import (
    AsgiLifespanShutdownTimeoutError,
    AsgiLifespanStartupTimeoutError,
)
from zapros._handlers._asgi import (
    AsgiHandler,
    AsgiWebSocketStream,
)
from zapros._models import Request, Response as ZaprosResponse
from zapros.websocket._errors import ConnectionClosed


@get("/")
async def get_root() -> str:
    return "Hello, World!"


@get("/json")
async def get_json() -> dict:
    return {
        "message": "Hello",
        "status": "ok",
    }


@post("/echo")
async def post_echo(data: dict) -> dict:
    return {"echoed": data}


@get("/headers")
async def get_headers(
    headers: dict,
) -> dict:
    return {"received_headers": dict(headers)}


@get("/query")
async def get_query(name: str = "guest", age: int = 0) -> dict:
    return {"name": name, "age": age}


@get("/stream")
async def get_stream() -> Stream:
    async def generate():
        for i in range(3):
            yield f"chunk-{i}\n".encode()

    return Stream(generate())


@get("/status/{code:int}")
async def get_status(
    code: int,
) -> Response:
    return Response(
        content={"status": code},
        status_code=code,
    )


@get("/state")
async def get_state(
    state: State,
) -> dict:
    return {"startup_value": state.get("startup_value", "not set")}


@pytest.fixture
def litestar_app():
    return Litestar(
        route_handlers=[
            get_root,
            get_json,
            post_echo,
            get_headers,
            get_query,
            get_stream,
            get_status,
            get_state,
        ],
    )


@pytest.fixture
def litestar_app_with_lifespan():
    async def on_startup(
        app: Litestar,
    ) -> None:
        app.state.startup_value = "initialized"

    async def on_shutdown(
        app: Litestar,
    ) -> None:
        pass

    return Litestar(
        route_handlers=[get_state],
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
    )


async def test_basic_get(litestar_app):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get("http://testserver/")
            assert response.status == snapshot(200)
            assert response.text == snapshot("Hello, World!")


async def test_json_response(
    litestar_app,
):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get(
                "http://testserver/json",
            )
            assert response.status == snapshot(200)
            data = response.json
            assert data == snapshot(
                {
                    "message": "Hello",
                    "status": "ok",
                }
            )


async def test_post_json(litestar_app):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.post(
                "http://testserver/echo",
                json={
                    "test": "data",
                    "number": 42,
                },
            )
            assert response.status == snapshot(201)
            data = response.json
            assert data == snapshot(
                {
                    "echoed": {
                        "test": "data",
                        "number": 42,
                    }
                }
            )


async def test_query_params(
    litestar_app,
):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get(
                "http://testserver/query",
                params={
                    "name": "alice",
                    "age": "30",
                },
            )
            assert response.status == snapshot(200)
            data = response.json
            assert data == snapshot(
                {
                    "name": "alice",
                    "age": 30,
                }
            )


async def test_custom_headers(
    litestar_app,
):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get(
                "http://testserver/headers",
                headers={"X-Custom-Header": "test-value"},
            )
            assert response.status == snapshot(200)
            data = response.json
            assert "x-custom-header" in data["received_headers"]
            assert data["received_headers"]["x-custom-header"] == snapshot("test-value")


async def test_streaming_response(
    litestar_app,
):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=True,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            async with client.stream(
                "GET",
                "http://testserver/stream",
            ) as response:
                assert response.status == snapshot(200)
                chunks = []
                async for chunk in response.async_iter_bytes():
                    chunks.append(chunk)
                content = b"".join(chunks).decode()
                assert content == snapshot("chunk-0\nchunk-1\nchunk-2\n")


async def test_startup_timeout(anyio_backend):
    @get("/")
    async def root() -> str:
        return "ok"

    async def slow_startup(app):
        await anysleep(1)

    app = Litestar(route_handlers=[root], on_startup=[slow_startup])
    handler = AsgiHandler(
        app,
        startup_timeout=0.01,
    )

    if anyio_backend == "asyncio" or isinstance(anyio_backend, tuple) and anyio_backend[0] == "asyncio":
        with pytest.raises(AsgiLifespanStartupTimeoutError):
            async with handler:
                async with AsyncClient(handler=handler) as client:
                    await client.get("http://testserver/")
    else:
        with pytest.RaisesGroup(AsgiLifespanStartupTimeoutError):
            async with handler:
                async with AsyncClient(handler=handler) as client:
                    await client.get("http://testserver/")


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_shutdown_timeout(anyio_backend):
    @get("/")
    async def root() -> str:
        return "ok"

    async def slow_shutdown(app):
        await anysleep(1)

    app = Litestar(
        route_handlers=[root],
        on_startup=[lambda app: None],
        on_shutdown=[slow_shutdown],
    )
    handler = AsgiHandler(
        app,
        shutdown_timeout=0.01,
    )
    async with handler:
        if anyio_backend == "asyncio":
            with pytest.raises(AsgiLifespanShutdownTimeoutError):
                async with AsyncClient(handler=handler) as client:
                    await client.get("http://testserver/")
        else:
            with pytest.RaisesGroup(AsgiLifespanStartupTimeoutError):
                async with handler:
                    async with AsyncClient(handler=handler) as client:
                        await client.get("http://testserver/")


async def test_status_codes(
    litestar_app,
):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response_200 = await client.get(
                "http://testserver/status/200",
            )
            assert response_200.status == snapshot(200)

            response_404 = await client.get(
                "http://testserver/status/404",
            )
            assert response_404.status == snapshot(404)

            response_500 = await client.get(
                "http://testserver/status/500",
            )
            assert response_500.status == snapshot(500)


async def test_lifespan_disabled(
    litestar_app_with_lifespan,
):
    handler = AsgiHandler(
        litestar_app_with_lifespan,
        enable_lifespan=False,
    )
    async with handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get(
                "http://testserver/state",
            )
            data = response.json
            assert data == snapshot({"startup_value": "not set"})


async def test_lifespan_enabled(
    litestar_app_with_lifespan,
):
    async with AsgiHandler(
        litestar_app_with_lifespan,
        enable_lifespan=True,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get(
                "http://testserver/state",
            )
            data = response.json
            assert data == snapshot({"startup_value": "initialized"})


async def test_multiple_requests_same_handler(
    litestar_app,
):
    async with AsgiHandler(
        litestar_app,
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response1 = await client.get(
                "http://testserver/",
            )
            assert response1.status == snapshot(200)

            response2 = await client.get(
                "http://testserver/json",
            )
            assert response2.status == snapshot(200)

            response3 = await client.post(
                "http://testserver/echo",
                json={"test": 1},
            )
            assert response3.status == snapshot(201)


async def test_root_path():
    @get("/test")
    async def test_route() -> dict:
        return {"path": "ok"}

    app = Litestar(route_handlers=[test_route])
    async with AsgiHandler(
        app,
        root_path="/api",
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get(
                "http://testserver/api/test",
            )
            assert response.status == snapshot(200)
            data = response.json
            assert data == snapshot({"path": "ok"})


async def test_http_version():
    @get("/")
    async def root() -> str:
        return "ok"

    app = Litestar(route_handlers=[root])
    async with AsgiHandler(
        app,
        http_version="2.0",
        enable_lifespan=False,
    ) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get("http://testserver/")
            assert response.status == snapshot(200)


def _ws_request(path: str = "/") -> Request:
    return Request(URL(f"ws://testserver{path}"), method="GET")


def _handoff(response: ZaprosResponse) -> AsgiWebSocketStream:
    ws = response.context.get("handoff", {}).get("_asgi_websocket_stream")
    assert isinstance(ws, AsgiWebSocketStream)
    return ws


class TestAsgiWebSocketStream:
    async def test_handshake_accepted(self):
        async def app(scope, receive, send):
            assert scope["type"] == "websocket"
            event = await receive()
            assert event["type"] == "websocket.connect"
            await send({"type": "websocket.accept"})
            await receive()

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            assert response.status == snapshot(101)
            ws = _handoff(response)
            assert ws.state == "connected"
            await ws.aclose()

    async def test_handshake_with_subprotocol_and_headers(self):
        async def app(scope, receive, send):
            await receive()
            await send(
                {
                    "type": "websocket.accept",
                    "subprotocol": "graphql-ws",
                    "headers": [(b"x-extra", b"yes")],
                }
            )
            await receive()

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            ws = _handoff(response)
            assert ws.accept_subprotocol == snapshot("graphql-ws")
            assert ws.accept_headers == snapshot([("x-extra", "yes")])
            await ws.aclose()

    async def test_handshake_rejected_via_close(self):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.close", "code": 4000, "reason": "no thanks"})

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            assert response.status == snapshot(403)
            assert "_asgi_websocket_stream" not in response.context.get("handoff", {})

    async def test_handshake_rejected_when_app_raises(self):
        async def app(scope, receive, send):
            raise RuntimeError("boom")

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            assert response.status == snapshot(403)
            assert "_asgi_websocket_stream" not in response.context.get("handoff", {})

    async def test_send_and_receive_text(self):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            msg = await receive()
            assert msg["type"] == "websocket.receive"
            await send({"type": "websocket.send", "text": f"echo:{msg['text']}"})
            await receive()

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            ws = _handoff(response)
            await ws.asend(text="hello")
            received = await ws.areceive()
            assert received["type"] == snapshot("websocket.send")
            assert received["text"] == snapshot("echo:hello")
            await ws.aclose()

    async def test_areceive_raises_on_app_close(self):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 4001, "reason": "done"})

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            ws = _handoff(response)
            with pytest.raises(ConnectionClosed) as exc_info:
                await ws.areceive()
            assert exc_info.value.code == snapshot(4001)
            assert exc_info.value.reason == snapshot("done")
            assert ws.state == "disconnected"
            await ws.aclose()

    async def test_asend_validation(
        self,
    ):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            await receive()

        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request())
            ws = _handoff(response)
            with pytest.raises(ValueError):
                await ws.asend()
            with pytest.raises(ValueError):
                await ws.asend(text="x", bytes=b"y")
            await ws.aclose()

    async def test_litestar_websocket_echo(self):
        @websocket("/ws/echo")
        async def echo(socket: WebSocket) -> None:
            await socket.accept()
            data = await socket.receive_text()
            await socket.send_text(f"echo:{data}")
            await socket.close()

        app = Litestar(route_handlers=[echo])
        async with AsgiHandler(app, enable_lifespan=False) as handler:
            response = await handler.ahandle(_ws_request("/ws/echo"))
            assert response.status == snapshot(101)
            ws = _handoff(response)
            await ws.asend(text="hello")
            received = await ws.areceive()
            assert received["text"] == snapshot("echo:hello")
            with pytest.raises(ConnectionClosed):
                await ws.areceive()
            await ws.aclose()
