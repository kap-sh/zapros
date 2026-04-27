# Configuration

Zapros is designed to be highly extensible and configurable. This page covers the main configuration options and how to use them.

## Handlers

The primary configuration point for the client is the `handler` parameter. Handlers are responsible for making the actual HTTP requests and must implement the `AsyncBaseHandler` interface (`BaseHandler` for sync clients).

### Built-in Handlers

Zapros ships three built-in transport handlers:

| Handler | Description |
|---|---|
| `AsyncStdNetworkHandler` / `StdNetworkHandler` | Default handler. Uses the standard library. Supported in all environments. |
| `AsyncPyodideHandler` / `PyodideHandler` | For [Pyodide](https://pyodide.org/) environments. Uses the browser's `fetch` API. |
| `AsyncPyrequestsHandler` / `PyrequestsHandler` *(Experimental)* | Uses the Rust-based pyrequests library. Supports advanced features not available in the standard library handler. |

To pass a handler explicitly:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
)

async with AsyncClient(
    handler=AsyncStdNetworkHandler()
) as client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import (
    Client,
    StdNetworkHandler,
)

with Client(handler=StdNetworkHandler()) as client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

### Middleware Handlers

In addition to transport handlers, Zapros includes **middleware handlers** — handlers that wrap another handler to add functionality. They implement the `AsyncBaseMiddleware` interface (`BaseMiddleware` for sync clients) and follow the [chain of responsibility](https://refactoring.guru/design-patterns/chain-of-responsibility) pattern.

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    RetryMiddleware,
    AsyncStdNetworkHandler,
)

async with AsyncClient(
    handler=RetryMiddleware(
        AsyncStdNetworkHandler(),
        max_attempts=3,
    )
) as client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import (
    Client,
    RetryMiddleware,
    StdNetworkHandler,
)

with Client(
    handler=RetryMiddleware(
        StdNetworkHandler(),
        max_attempts=3,
    )
) as client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

### Chaining Handlers

Multiple middleware handlers can be composed into a chain. For long chains, deeply nested constructors can become hard to read — use `wrap_with_middleware` for a more readable alternative:

```python
from zapros import (
    CacheMiddleware,
    RetryMiddleware,
    RedirectMiddleware,
    CookieMiddleware,
    Client,
    StdNetworkHandler,
)

handler = (
    RetryMiddleware(
        StdNetworkHandler(),
        max_attempts=3,
        backoff_factor=0.1,
    )
    .wrap_with_middleware(
        lambda next: RedirectMiddleware(next)
    )
    .wrap_with_middleware(lambda next: CookieMiddleware(next))
    .wrap_with_middleware(lambda next: CacheMiddleware(next))
)

with Client(handler) as client:
    ...
```

You can also implement your own middleware handlers — just ensure they satisfy the `AsyncBaseMiddleware` (`BaseMiddleware` for sync) interface.

## Default Headers

Pass `default_headers` to attach headers to every request made by the client. Headers passed directly to the request override any matching default headers:

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient(
    default_headers={"User-Agent": "MyCustomClient/1.0"}
) as client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import Client

with Client(
    default_headers={"User-Agent": "MyCustomClient/1.0"}
) as client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

## Default Parameters

Pass `default_params` to append query parameters to every request made by the client. When the same key appears in multiple places, the following priority applies (highest to lowest):

1. `params` passed directly to the request
2. Query parameters embedded in the URL string
3. `default_params` on the client



::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient(
    default_params={"api_key": "my_api_key"}
) as client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import Client

with Client(
    default_params={"api_key": "my_api_key"}
) as client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

## Base URL

Pass `base_url` to set a base URL that all request paths are resolved against. This is useful when making multiple requests to the same API:

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient(
    base_url="https://api.example.com/v1/"
) as client:
    response = await client.get("users")
    # Requests https://api.example.com/v1/users
```

```python [Sync]
from zapros import Client

with Client(base_url="https://api.example.com/v1/") as client:
    response = client.get("users")
    # Requests https://api.example.com/v1/users
```

:::

URL resolution follows the [WHATWG URL Standard](https://url.spec.whatwg.org/). Key behaviors to note:

| Base URL | Endpoint | Result |
|----------|----------|--------|
| `https://api.example.com/v1/` | `users` | `https://api.example.com/v1/users` |
| `https://api.example.com/v1` | `users` | `https://api.example.com/users` |
| `https://api.example.com/v1/` | `/health` | `https://api.example.com/health` |
| `https://api.example.com/v1/` | `https://other.com/path` | `https://other.com/path` |

::: tip
Always include a trailing slash on your base URL if you want relative paths appended to it. Without a trailing slash, the last path segment is replaced.
:::

::: warning
Query parameters on the base URL are dropped during resolution. Use `default_params` instead to include query parameters on every request.
:::

## Authentication

Pass `auth` to the client to authenticate every request. Auth passed directly to the request takes priority over the client-level `auth`:

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient(
    auth=("username", "password")
) as client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import Client

with Client(auth=("username", "password")) as client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

For more advanced authentication schemes such as Digest or token-based auth, see [Authentication](/authentication).
