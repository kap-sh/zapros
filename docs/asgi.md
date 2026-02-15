# ASGI Applications

The **AsgiHandler** allows you to test ASGI applications (such as FastAPI, Litestar, Starlette, etc.) without making actual network requests. It acts as a bridge between Zapros and any ASGI-compliant application.

## Basic Usage

```python
from litestar import Litestar, get
from zapros import AsyncClient
from zapros import AsgiHandler


@get("/hello")
async def hello() -> dict:
    return {"message": "Hello, World!"}


app = Litestar(route_handlers=[hello])
handler = AsgiHandler(app)

async with AsyncClient(handler=handler) as client:
    response = await client.get("http://testserver/hello")
    print(await response.ajson())
```

## Configuration Options

The `AsgiHandler` accepts several configuration parameters:

```python
handler = AsgiHandler(
    app,
    client=(
        "127.0.0.1",
        123,
    ),  # Client address tuple (host, port)
    root_path="",  # ASGI root_path for the application
    http_version="1.1",  # HTTP protocol version
    enable_lifespan=True,  # Enable ASGI lifespan protocol
    startup_timeout=10.0,  # Timeout for lifespan startup (seconds)
    shutdown_timeout=10.0,  # Timeout for lifespan shutdown (seconds)
)
```

## Lifespan Management

ASGI applications can implement startup and shutdown logic using the lifespan protocol. The `AsgiHandler` supports this:

```python
from litestar import Litestar, get
from litestar.datastructures import (
    State,
)


@get("/state")
async def get_state(
    state: State,
) -> dict:
    return {"value": state.get("initialized", False)}


async def on_startup(
    app: Litestar,
) -> None:
    app.state.initialized = True


app = Litestar(
    route_handlers=[get_state],
    on_startup=[on_startup],
)

handler = AsgiHandler(app, enable_lifespan=True)
try:
    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            "http://testserver/state",
        )
        print(await response.ajson())
finally:
    await handler.aclose()
```

**Important**: When using `enable_lifespan=True`, you must call `await handler.aclose()` to properly shut down the application.

## Streaming Responses

The handler fully supports streaming responses from ASGI applications:

```python
from litestar import (
    Litestar,
    get,
    Response,
    MediaType,
)


@get("/stream")
async def stream_data() -> Response:
    async def generate():
        for i in range(5):
            yield f"chunk-{i}\n".encode()

    return Response(
        content=generate(),
        media_type=MediaType.TEXT,
    )


app = Litestar(route_handlers=[stream_data])
handler = AsgiHandler(app, enable_lifespan=False)

async with AsyncClient(handler=handler) as client:
    async with client.stream(
        "GET",
        "http://testserver/stream",
    ) as response:
        async for chunk in response.async_iter_bytes():
            print(chunk.decode())
```
