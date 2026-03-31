# Handlers

Handlers are the core extension point in Zapros. Every request passes through a handler chain before reaching the network. You can write custom transport handlers to change *how* requests are sent, or middleware handlers to intercept and transform requests and responses.

## Custom Transport Handlers

A transport handler is the terminal node in the chain — it makes the actual HTTP call. Implement `AsyncBaseHandler` for async clients or `BaseHandler` for sync clients.

::: code-group

```python [Async]
from zapros import (
    AsyncBaseHandler,
    AsyncClient,
    Request,
    Response,
)


class MyAsyncHandler(AsyncBaseHandler):
    async def ahandle(self, request: Request) -> Response:
        # perform the HTTP call and return a Response
        ...

    async def aclose(self) -> None:
        # release any resources
        ...


async with AsyncClient(handler=MyAsyncHandler()) as client:
    response = await client.get(
        "https://api.example.com/users",
    )
```

```python [Sync]
from zapros import (
    BaseHandler,
    Client,
    Request,
    Response,
)


class MySyncHandler(BaseHandler):
    def handle(self, request: Request) -> Response:
        # perform the HTTP call and return a Response
        ...

    def close(self) -> None:
        # release any resources
        ...


with Client(handler=MySyncHandler()) as client:
    response = client.get(
        "https://api.example.com/users",
    )
```

:::

Async handlers must be **task-safe**: a single handler instance may be called concurrently from multiple tasks, so avoid mutable per-request state on `self`. Sync handlers must be **thread-safe** for the same reason when shared across threads.

## Custom Middleware Handlers

A middleware handler wraps another handler to add behaviour before or after the call. Implement `AsyncBaseMiddleware` (or `BaseMiddleware`) and forward to the next handler.

::: code-group

```python [Async]
from typing import cast

from zapros import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
    AsyncClient,
    Request,
    Response,
    StdNetworkHandler,
)


class TimingMiddleware(AsyncBaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler,
    ) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        import time

        start = time.perf_counter()
        response = await self.async_next.ahandle(request)
        elapsed = time.perf_counter() - start
        print(
            f"{request.method} {request.url} → {response.status} ({elapsed:.3f}s)"
        )
        return response


async with AsyncClient(
    handler=TimingMiddleware(StdNetworkHandler())
) as client:
    response = await client.get(
        "https://api.example.com/users",
    )
```

```python [Sync]
from typing import cast

from zapros import (
    BaseHandler,
    BaseMiddleware,
    Client,
    Request,
    Response,
    StdNetworkHandler,
)


class TimingMiddleware(BaseMiddleware):
    def __init__(self, next_handler: BaseHandler) -> None:
        self.next = next_handler

    def handle(self, request: Request) -> Response:
        import time

        start = time.perf_counter()
        response = self.next.handle(request)
        elapsed = time.perf_counter() - start
        print(
            f"{request.method} {request.url} → {response.status} ({elapsed:.3f}s)"
        )
        return response


with Client(
    handler=TimingMiddleware(StdNetworkHandler())
) as client:
    response = client.get(
        "https://api.example.com/users",
    )
```

:::

## Request and Response Context

Every `Request` carries a `context` dict that travels through the entire handler chain. Every `Response` carries its own `context` dict back. You can use these to pass data between handlers without touching the HTTP headers.

### Reading request context

Built-in keys on `request.context`:

| Key | Type | Description |
|---|---|---|
| `timeouts` | dict | Per-request timeout overrides (`connect`, `read`, `write`, `total`) |
| `caching` | dict | Caching directives (`ttl`, `refresh_ttl_on_access`, `body_key`) |

A middleware can read these to adjust its behaviour:

```python
from typing import cast

from zapros import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
    Request,
    Response,
)


class RespectCachingContextMiddleware(AsyncBaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler,
    ) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        caching = request.context.get("caching", {})
        ttl = caching.get("ttl")
        if ttl is not None:
            print(f"Request wants caching with TTL={ttl}s")
        return await self.async_next.ahandle(request)
```

### Writing custom context keys

You can add your own keys to `request.context` at call time, and read them in your middleware:

```python
from typing import cast

from zapros import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
    AsyncClient,
    Request,
    Response,
    StdNetworkHandler,
)


class TraceMiddleware(AsyncBaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler,
    ) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        trace_id = request.context.get("x-trace-id")
        if trace_id:
            request.headers.add("X-Trace-Id", trace_id)
        return await self.async_next.ahandle(request)


async with AsyncClient(
    handler=TraceMiddleware(StdNetworkHandler())
) as client:
    response = await client.get(
        "https://api.example.com/users",
        context={"x-trace-id": "abc-123"},
    )
```

### Reading response context

Handlers can annotate responses by setting keys on `response.context`. For example, `CacheMiddleware` sets `response.context["caching"]` with cache metadata:

| Key | Description |
|---|---|
| `response.context["caching"]["from_cache"]` | `True` if the response was served from cache |
| `response.context["caching"]["stored"]` | `True` if the response was stored into cache |
| `response.context["caching"]["revalidated"]` | `True` if the cache entry was revalidated |

Your own middleware can enrich the response context the same way:

```python
import time
from typing import cast

from zapros import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
    Request,
    Response,
)


class TimingMiddleware(AsyncBaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler,
    ) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        start = time.perf_counter()
        response = await self.async_next.ahandle(request)
        response.context["x-elapsed"] = (
            time.perf_counter() - start
        )
        return response
```

Callers can then inspect `response.context["x-elapsed"]` after the request completes.

## Response Ownership

When a handler receives a response from the next handler in the chain, it becomes the **owner** of that response and is responsible for closing it. There are two valid paths:

- **Propagate ownership** — return the response (or pass it further up the chain). The parent handler or client becomes the new owner and takes responsibility for closing it.
- **Close and discard** — if the handler needs to return a modified response or raise an exception instead, it must close the original response before doing so. Failing to close it leaks the underlying connection.

```python
from zapros import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
    Request,
    Response,
)


class RetryOn503Middleware(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        response = await self.async_next.ahandle(request)
        if response.status != 503:
            return response  # propagate ownership to the caller

        await response.aclose()  # we won't return this response — close it first
        return await self.async_next.ahandle(request)  # retry, propagate new response
```

The same rule applies when raising an exception after receiving a response:

```python
from zapros import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
    Request,
    Response,
)


class ErrorOnServerErrorMiddleware(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        response = await self.async_next.ahandle(request)
        if response.status < 500:
            return response  # propagate ownership to the caller

        await response.aclose()  # must close before raising — we are not returning it
        raise RuntimeError(f"Server error: {response.status}")
```
