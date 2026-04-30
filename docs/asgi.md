# asgi

The **AsgiHandler** lets Zapros talk directly to ASGI apps such as FastAPI, Litestar, and Starlette without making real network requests.

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
     print(response.json)
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

## Timeouts

When an ASGI application's lifespan startup or shutdown takes too long, Zapros raises timeout exceptions:

- **`AsgiLifespanStartupTimeoutError`** — raised if the application does not complete startup within `startup_timeout` seconds
- **`AsgiLifespanShutdownTimeoutError`** — raised if the application does not complete shutdown within `shutdown_timeout` seconds

Both default to 10 seconds. Set to `None` for no timeout, or adjust for applications with longer initialization:

```python
from zapros import AsgiHandler

handler = AsgiHandler(
    app,
    startup_timeout=30.0,
    shutdown_timeout=5.0,
)
```

## Trio Support

The `AsgiHandler` fully supports running under Trio. To respect Trio's philosophy that background tasks should only run within a nursery, you **must** use the handler as an async context manager when running in a Trio context:

```python
import trio
from litestar import Litestar, get
from zapros import AsyncClient
from zapros import AsgiHandler


@get("/hello")
async def hello() -> dict:
    return {"message": "Hello, World!"}


app = Litestar(route_handlers=[hello])


async def main():
    async with AsgiHandler(app) as handler:
        async with AsyncClient(handler=handler) as client:
            response = await client.get("http://testserver/hello")
            print(response.json)


trio.run(main)
```

**Important**: If you attempt to use `AsgiHandler` in a Trio run without the async context manager, a `RuntimeError` will be raised:

```
RuntimeError: When using `AsgiHandler` with Trio, you must use it as an async context manager (i.e. `async with AsgiHandler(...) as handler:`)
```

When using the handler as a context manager with Trio, lifespan management is handled automatically—the nursery ensures proper startup and shutdown sequencing.

## Lifespan Management

Zapros implements the [ASGI lifespan protocol](https://asgi.readthedocs.io/en/latest/specs/lifespan.html), allowing ASGI applications to implement startup and shutdown logic. The `AsgiHandler` supports this:

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
         print(response.json)
finally:
    await handler.aclose()
```

