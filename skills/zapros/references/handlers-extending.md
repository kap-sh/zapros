# Handlers & Extending

Handlers are Zapros's core extension point. Every request flows through a chain of **middleware handlers** (each wraps the next) that ends in one **transport handler** (does the actual I/O). Extending Zapros almost always means writing a middleware; the built-in transports cover the I/O.

```
Client ──► Middleware A ──► Middleware B ──► Transport handler ──► network / ASGI app / fetch()
```

## The contracts

Four runtime-checkable `Protocol`s, exported from `zapros`:

```python
class AsyncBaseHandler(Protocol):
    async def ahandle(self, request: Request) -> Response: ...      # required
    async def aclose(self) -> None: ...                              # default no-op
    def wrap_with_async_middleware(self, factory) -> AsyncBaseMiddleware  # returns factory(self)

class AsyncBaseMiddleware(AsyncBaseHandler, Protocol):
    async_next: AsyncBaseHandler                                     # the wrapped handler

class BaseHandler(Protocol):
    def handle(self, request: Request) -> Response: ...
    def close(self) -> None: ...
    def wrap_with_middleware(self, factory) -> BaseMiddleware

class BaseMiddleware(BaseHandler, Protocol):
    next: BaseHandler
```

Because they're Protocols, subclassing is optional — any object with the right methods/attributes passes `isinstance`. Subclass anyway to get the default `aclose`/`close` and the `wrap_with_*` helpers.

Rules the client relies on:

- **`AsyncClient` requires an `AsyncBaseHandler`; `Client` requires a `BaseHandler`.** A mismatched chain fails at call time: built-in middlewares raise `AsyncSyncMismatchError` when delegating to a wrong-kind `next`; the client itself just hits `AttributeError` (missing `ahandle`/`aclose` or `handle`/`close`).
- **Closing**: `client.aclose()` / context exit walks the chain — calls `aclose()` on the handler, then on its `async_next`, and so on — so every handler and middleware gets closed without extra wiring. Middlewares must expose `async_next` (or `next`) for this to reach the transport.
- **Concurrency**: one handler instance serves many concurrent tasks (async) or threads (sync). Keep per-request state in locals or on `request.context`, never on `self`.
- **Non-streaming calls** (`client.get(...)` etc.): the client reads the whole body and closes the response after `ahandle` returns. **`client.stream(...)`** leaves the response open until the caller's context exits. Handlers don't need to care which path is in use — only follow the ownership rule below.

## Writing a middleware

Store the wrapped handler as `async_next` (async) / `next` (sync), do work before and/or after delegating.

```python
import time
from zapros import AsyncBaseHandler, AsyncBaseMiddleware, AsyncClient, AsyncStdNetworkHandler, Request, Response


class TimingMiddleware(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        start = time.perf_counter()
        response = await self.async_next.ahandle(request)
        response.context["myapp.elapsed"] = time.perf_counter() - start   # annotate for callers
        return response


async with AsyncClient(handler=TimingMiddleware(AsyncStdNetworkHandler())) as client:
    response = await client.get("https://api.example.com/users")
    print(response.context["myapp.elapsed"])
```

Sync version: subclass `BaseMiddleware`, store `self.next`, implement `handle` calling `self.next.handle(request)`.

### Supporting both sync and async in one class

All built-in middlewares (`RetryMiddleware`, `CookieMiddleware`, `MockMiddleware`, …) are "mixed": they inherit both protocols and implement both `ahandle` and `handle`, sharing pure helper methods. The constructor stores the same `next_handler` under both names:

```python
from typing import cast
from zapros import AsyncBaseHandler, AsyncBaseMiddleware, BaseHandler, BaseMiddleware, Request, Response


class HeaderMiddleware(AsyncBaseMiddleware, BaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler | BaseHandler, name: str, value: str) -> None:
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(AsyncBaseHandler, next_handler)
        self._name, self._value = name, value

    def _prepare(self, request: Request) -> None:          # shared, I/O-free logic
        request.headers.add(self._name, self._value)

    async def ahandle(self, request: Request) -> Response:
        self._prepare(request)
        return await self.async_next.ahandle(request)

    def handle(self, request: Request) -> Response:
        self._prepare(request)
        return self.next.handle(request)
```

Keep I/O-free logic in shared helpers; only the `handle`/`ahandle` bodies differ. If a mixed middleware's `aclose`/`close` must release resources, implement both.

### Response ownership (the rule that prevents connection leaks)

When `ahandle` receives a response from `async_next`, the middleware **owns** it. Exactly one of:

1. **Return it** (possibly with mutated headers/context) — ownership passes up the chain.
2. **Close it, then do something else** — retry, return a substitute `Response`, or raise (deliberately, or because your own post-processing failed). Not closing before raising/replacing leaks the underlying connection.

```python
class RetryOn503(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        response = await self.async_next.ahandle(request)
        if response.status != 503:
            return response                            # (1) propagate
        await response.aclose()                        # (2) close before retrying
        return await self.async_next.ahandle(request)


class RaiseOn5xx(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        response = await self.async_next.ahandle(request)
        if response.status < 500:
            return response
        await response.aclose()                        # close before raising
        raise RuntimeError(f"Server error: {response.status}")
```

The same applies when your post-processing can fail unexpectedly. Anything you do with the response between receiving and returning it — reading the body, parsing JSON, validating a schema, calling a hook — may raise, and the exception unwinds through your frame while you still own the response. Guard it with `try/except` and close before re-raising:

```python
class ValidateJson(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        response = await self.async_next.ahandle(request)
        try:
            await response.aread()
            validate(response.json)                    # may raise
        except BaseException:
            await response.aclose()                    # we're still the owner — release it
            raise
        return response                                # propagate on success
```

Only the failure path closes; on success ownership still passes up the chain, so don't use `finally` (it would close a response you're about to return).

Retrying requires a replayable body — check `request.is_replayable()` before re-sending (streaming bodies are consumed on first send).

### Request and response context

`request.context` is a dict that travels down the chain; `response.context` travels back. Use them to pass data between callers and middlewares — and to annotate responses for callers — instead of smuggling it through HTTP headers. Built-in handlers use the same mechanism (e.g. `context={"timeouts": {...}}` per request, `response.context["caching"]` from `CacheMiddleware`); see https://zapros.dev/handlers#request-and-response-context for the built-in keys.

```python
class TraceMiddleware(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler) -> None:
        self.async_next = next_handler

    async def ahandle(self, request: Request) -> Response:
        if trace_id := request.context.get("myapp.trace_id"):
            request.headers.add("X-Trace-Id", trace_id)
        return await self.async_next.ahandle(request)


await client.get(url, context={"myapp.trace_id": "abc-123"})
```

Namespace custom keys (`"myapp.trace_id"`) to avoid colliding with built-ins.

## Composing chains

Nested constructors work but read inside-out. Prefer `wrap_with_middleware` (sync) / `wrap_with_async_middleware` (async): each call wraps the current chain, so **the last wrap is the outermost layer and runs first**.

```python
from zapros import CacheMiddleware, CookieMiddleware, RedirectMiddleware, RetryMiddleware, StdNetworkHandler, Client

handler = (
    RetryMiddleware(StdNetworkHandler(), max_attempts=3, backoff_factor=0.1)
    .wrap_with_middleware(lambda next: RedirectMiddleware(next))
    .wrap_with_middleware(lambda next: CookieMiddleware(next))
    .wrap_with_middleware(lambda next: CacheMiddleware(next))
)
# request path: Cache -> Cookie -> Redirect -> Retry -> StdNetwork

with Client(handler) as client:
    ...
```

Order matters: put `RetryMiddleware` closest to the transport (retries a single hop), `RedirectMiddleware` above it, `CacheMiddleware` near the top so cache hits skip everything below, `MockMiddleware`/`CassetteMiddleware` wherever you want interception to occur.

### Per-request handler override

`handler=` on any request method accepts either an explicit handler (used instead of the client's) or a callable `handler -> handler` that receives the client's handler and returns a wrapped one. The client's own handler is never mutated.

```python
response = await client.get(url, handler=lambda h: TimingMiddleware(h))   # wrap for this call only
response = await client.get(url, handler=AsyncStdNetworkHandler(http2=True))  # replace for this call
```

## Built-in handlers and middlewares

Don't reimplement what ships with Zapros. Check these first; the docs are the complete reference for their options:

- Transport handlers — overview: https://zapros.dev/configuration#handlers
  - `AsyncStdNetworkHandler` / `StdNetworkHandler` (default; HTTP/1.1 + optional HTTP/2, timeouts, proxies, SSL, Trio): https://zapros.dev/python-std
  - `AsgiHandler` (call an ASGI app in-process): https://zapros.dev/asgi
  - `AsyncPyodideHandler` (browser `fetch()`): https://zapros.dev/browser
  - `AsyncPyreqwestHandler` / `PyreqwestHandler` (Rust `reqwest`): https://zapros.dev/rust
- Middlewares — `RetryMiddleware` (https://zapros.dev/retries), `RedirectMiddleware` (https://zapros.dev/redirects), `CookieMiddleware` (https://zapros.dev/cookies), `CacheMiddleware` (https://zapros.dev/caching), `ProxyMiddleware` (https://zapros.dev/python-std#proxies), `CassetteMiddleware` and `MockMiddleware` (see the testing-mocking reference)

All built-in middlewares are mixed (work with both `Client` and `AsyncClient`) and take `next_handler` as the first positional argument — except `MockMiddleware(router=None, next_handler=None)`, where it comes second. Names ending in `Handler` for these (`RetryHandler`, `RedirectHandler`, `CookieHandler`, `CachingHandler`, `CassetteHandler`, `MockHandler`, …) are deprecated aliases of the `*Middleware` classes — don't use them in new code.

## Quick Checklist

- Middleware: store `async_next`/`next`, delegate, return the response **or** close it before retrying/raising/substituting.
- Post-processing the response (reading, parsing, validating) can raise — wrap it in `try/except`, `aclose()` the response, re-raise. Don't use `finally`; the success path returns the response open.
- Mixed sync+async middleware: inherit both `AsyncBaseMiddleware, BaseMiddleware`, set both `next` and `async_next`, implement both `handle` and `ahandle`.
- Keep per-request state off `self` — one instance serves many tasks/threads.
- Compose with `wrap_with_middleware` — last wrap is outermost; keep `RetryMiddleware` nearest the transport.
- Pass data via `request.context` / `response.context`, not ad-hoc headers; namespace custom keys.
- Per-request tweaks: `client.get(url, handler=lambda h: MyMiddleware(h))`.

