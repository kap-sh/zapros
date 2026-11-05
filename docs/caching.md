# Caching

Caching in Zapros is implemented as a [handler](/handlers) powered by [Hishel](https://hishel.com) — wrapping another handler to automatically cache HTTP responses.

## Installation

The caching handler is available with the `caching` optional feature:

```bash
pip install zapros[caching]
```

## Setup

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))
```

:::

## Basic usage

By default, `CacheMiddleware` caches successful `GET` and `HEAD` responses (except `206`) by method and URL. It ignores HTTP caching headers, so a stored response is served until the storage expires it:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
    print(response.status)
    print(response.context.get("caching"))
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
    )
    print(response.status)
    print(response.context.get("caching"))
```

:::

## RFC 9111 mode

Pass `rfc=True` to follow [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html) instead. The server's `Cache-Control`, `Vary`, `ETag` and related headers then decide what is stored, how long it stays fresh, and when it is revalidated:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(
        AsyncStdNetworkHandler(),
        rfc=True,
    )
)
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(
    handler=CacheMiddleware(
        StdNetworkHandler(),
        rfc=True,
    )
)
```

:::

To configure RFC 9111 mode, pass Hishel's `CacheOptions` instead of `True`. For example, `shared=False` makes it a private cache, which can store responses to requests with an `Authorization` header. See [Hishel's documentation](https://hishel.com/httpx.html) for all options:

::: code-group

```python [Async]
from hishel import CacheOptions
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(
        AsyncStdNetworkHandler(),
        rfc=CacheOptions(shared=False),
    )
)
```

```python [Sync]
from hishel import CacheOptions
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(
    handler=CacheMiddleware(
        StdNetworkHandler(),
        rfc=CacheOptions(shared=False),
    )
)
```

:::

::: warning
In the default mode the cache is shared across users, whatever their `Authorization` or `Cookie` headers. If responses differ per user, use RFC 9111 mode or a separate storage per user.
:::

## Custom storage

By default, responses are cached in an SQLite database (`.cache/hishel/hishel_cache_v2.db`). Closing the client also closes the middleware's storage, including one you passed in. You can customize the storage backend to use different databases or in-memory storage. See [Hishel storage documentation](https://hishel.com/storages.html) for more options, including Redis.

### Expiry

Storages accept `default_ttl` (seconds after the response is stored) and `default_tti` (seconds without being used). Whichever comes first expires the entry:

::: code-group

```python [Async]
from hishel import AsyncSqliteStorage
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(
        AsyncStdNetworkHandler(),
        storage=AsyncSqliteStorage(
            default_ttl=86400,
            default_tti=3600,
        ),
    )
)
```

```python [Sync]
from hishel import SqliteStorage
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(
    handler=CacheMiddleware(
        StdNetworkHandler(),
        storage=SqliteStorage(
            default_ttl=86400,
            default_tti=3600,
        ),
    )
)
```

:::

### In-memory storage

For temporary caching without persistent storage:

::: code-group

```python [Async]
import anysqlite
from hishel import AsyncSqliteStorage
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(
        AsyncStdNetworkHandler(),
        storage=AsyncSqliteStorage(
            connection=await anysqlite.connect(":memory:")
        ),
    )
)
```

```python [Sync]
import sqlite3
from hishel import SqliteStorage
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(
    handler=CacheMiddleware(
        StdNetworkHandler(),
        storage=SqliteStorage(
            connection=sqlite3.connect(
                ":memory:", check_same_thread=False
            )
        ),
    )
)
```

:::

### Custom SQLite file

Specify a custom database file location:

::: code-group

```python [Async]
from hishel import AsyncSqliteStorage
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(
        AsyncStdNetworkHandler(),
        storage=AsyncSqliteStorage(
            database_path="my_cache.db"
        ),
    )
)
```

```python [Sync]
from hishel import SqliteStorage
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(
    handler=CacheMiddleware(
        StdNetworkHandler(),
        storage=SqliteStorage(
            database_path="my_cache.db"
        ),
    )
)
```

:::

## Per-request configuration

Control caching behavior on a per-request basis using the `context` parameter.

### TTL (Time to Live)

Expire this response a number of seconds after it is stored:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
        context={
            "caching": {
                "ttl": 30.0,
            }
        },
    )
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
        context={
            "caching": {
                "ttl": 30.0,
            }
        },
    )
```

:::

### TTI (Time to Idle)

Expire this response after a number of seconds without being used, so each use keeps it alive:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
        context={
            "caching": {
                "tti": 300.0,
            }
        },
    )
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
        context={
            "caching": {
                "tti": 300.0,
            }
        },
    )
```

:::

### Cache key

Replace the default key (method and URL) with your own. Requests with the same key share an entry, so here both URLs are answered by one cached response. A custom key alone does not make `POST` and other unsafe methods cacheable, see [Forcing the cache](#forcing-the-cache):

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data?session=abc",
        context={
            "caching": {
                "key": "data",
            }
        },
    )
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data?session=abc",
        context={
            "caching": {
                "key": "data",
            }
        },
    )
```

:::

### Forcing the cache

`POST` and other unsafe methods are never cached by default, because serving them from cache means the request never reaches the server. For requests that only read data, such as GraphQL queries or search endpoints, set `force` to cache the response anyway.

The default key doesn't include the request body, so `force` on a method other than `GET` or `HEAD` requires a `key`, and raises `ValueError` without one. Choose a key that changes whenever the body does. A forced request ignores `rfc` and caches by method and key, storing only successful responses:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.post(
        "https://api.example.com/graphql",
        json={"query": "{ user(id: 1) { name } }"},
        context={
            "caching": {
                "force": True,
                "key": "user-1-name",
            }
        },
    )
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.post(
        "https://api.example.com/graphql",
        json={"query": "{ user(id: 1) { name } }"},
        context={
            "caching": {
                "force": True,
                "key": "user-1-name",
            }
        },
    )
```

:::

### Mode and storage

The `rfc` and `storage` arguments of `CacheMiddleware` can also be overridden for a single request:

::: code-group

```python [Async]
from hishel import AsyncSqliteStorage
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)
reports_storage = AsyncSqliteStorage(
    database_path="reports.db"
)

async with client:
    response = await client.get(
        "https://api.example.com/reports",
        context={
            "caching": {
                "rfc": True,
                "storage": reports_storage,
            }
        },
    )
```

```python [Sync]
from hishel import SqliteStorage
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))
reports_storage = SqliteStorage(database_path="reports.db")

with client:
    response = client.get(
        "https://api.example.com/reports",
        context={
            "caching": {
                "rfc": True,
                "storage": reports_storage,
            }
        },
    )
```

:::

## Response context

The response context provides useful information about caching behavior.

### Check if response was cached

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
    caching = response.context.get("caching")

    if caching:
        print(f"From cache: {caching.get('from_cache')}")
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
    )
    caching = response.context.get("caching")

    if caching:
        print(f"From cache: {caching.get('from_cache')}")
```

:::

### Available context fields

- **`from_cache`** - Whether the response was served from cache
- **`revalidated`** - Whether the cached response was revalidated with the origin server (RFC 9111 mode only, see [RFC 9111 validation](https://www.rfc-editor.org/rfc/rfc9111.html#name-validation))
- **`stored`** - Whether the response was stored in the cache. It is saved once its body has been fully read

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CacheMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
    caching = response.context.get("caching")

    if caching:
        print(f"From cache: {caching.get('from_cache')}")
        print(f"Revalidated: {caching.get('revalidated')}")
        print(f"Stored: {caching.get('stored')}")
```

```python [Sync]
from zapros import (
    Client,
    CacheMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CacheMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
    )
    caching = response.context.get("caching")

    if caching:
        print(f"From cache: {caching.get('from_cache')}")
        print(f"Revalidated: {caching.get('revalidated')}")
        print(f"Stored: {caching.get('stored')}")
```

:::

## Combining with other handlers

Chain `CacheMiddleware` with other handlers like cookies or retries:

```python
from zapros import (
    AsyncClient,
    CacheMiddleware,
    CookieMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CacheMiddleware(
        CookieMiddleware(AsyncStdNetworkHandler())
    )
)
```
