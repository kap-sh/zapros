# Caching

Caching in Zapros is implemented as a [handler](/handlers) powered by [Hishel](https://hishel.com) — wrapping another handler to automatically cache HTTP responses according to RFC 9111 standards.

## Installation

The caching handler is available with the `cache` optional feature:

```bash
pip install zapros[cache]
```

## Setup

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
)
```

```python [Sync]
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))
```

:::

## Basic usage

By default, `CachingHandler` uses RFC 9111 compliant caching, respecting standard HTTP cache headers:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
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
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
    )
    print(response.status)
    print(response.context.get("caching"))
```

:::

## Caching policies

Customize caching behavior with different policies. See [Hishel policies documentation](https://hishel.com/1.0/policies/) for more details.

### SpecificationPolicy (default)

Strict RFC 9111 compliant caching:

::: code-group

```python [Async]
from hishel import SpecificationPolicy
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(
        AsyncStdNetworkHandler(),
        policy=SpecificationPolicy(),
    )
)
```

```python [Sync]
from hishel import SpecificationPolicy
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(
    handler=CachingHandler(
        StdNetworkHandler(),
        policy=SpecificationPolicy(),
    )
)
```

:::

### FilterPolicy

Cache anything that passes custom filters:

::: code-group

```python [Async]
from hishel import FilterPolicy
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(
        AsyncStdNetworkHandler(),
        policy=FilterPolicy(),
    )
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from hishel import FilterPolicy
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(
    handler=CachingHandler(
        StdNetworkHandler(),
        policy=FilterPolicy(),
    )
)

with client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

You can pass both request and response filters to `FilterPolicy` to control what gets cached:

::: code-group

```python [Async]
from hishel import FilterPolicy
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

policy = FilterPolicy(
    request_filter=lambda req: req.method == "GET",
    response_filter=lambda resp: resp.status == 200,
)

client = AsyncClient(
    handler=CachingHandler(
        AsyncStdNetworkHandler(),
        policy=policy,
    )
)
```

```python [Sync]
from hishel import FilterPolicy
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

policy = FilterPolicy(
    request_filter=lambda req: req.method == "GET",
    response_filter=lambda resp: resp.status == 200,
)

client = Client(
    handler=CachingHandler(
        StdNetworkHandler(),
        policy=policy,
    )
)
```

:::

## Custom storage

By default, responses are cached in an SQLite database (`hishel_cache.db`). You can customize the storage backend to use different databases or in-memory storage. See [Hishel storage documentation](https://hishel.com/1.0/storages/) for more options.

### In-memory storage

For temporary caching without persistent storage:

::: code-group

```python [Async]
import anysqlite
from hishel import AsyncSqliteStorage
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(
        AsyncStdNetworkHandler(),
        storage=AsyncSqliteStorage(
            connection=anysqlite.connect(":memory:")
        ),
    )
)
```

```python [Sync]
import sqlite3
from hishel import SyncSqliteStorage
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(
    handler=CachingHandler(
        StdNetworkHandler(),
        storage=SyncSqliteStorage(
            connection=sqlite3.connect(":memory:")
        ),
    )
)
```

:::

### Custom SQLite file

Specify a custom database file location:

::: code-group

```python [Async]
import anysqlite
from hishel import AsyncSqliteStorage
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(
        AsyncStdNetworkHandler(),
        storage=AsyncSqliteStorage(
            connection=sqlite3.connect("my_cache.db")
        ),
    )
)
```

```python [Sync]
import sqlite3
from hishel import SyncSqliteStorage
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(
    handler=CachingHandler(
        StdNetworkHandler(),
        storage=SyncSqliteStorage(
            connection=sqlite3.connect("my_cache.db")
        ),
    )
)
```

:::

## Per-request configuration

Control caching behavior on a per-request basis using the `context` parameter.

### TTL (Time to Live)

Set a maximum lifetime for cached responses:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
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
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))

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

### Refresh TTL on access

Extend the cache lifetime each time a cached response is accessed:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
        context={
            "caching": {
                "refresh_ttl_on_access": True,
            }
        },
    )
```

```python [Sync]
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
        context={
            "caching": {
                "refresh_ttl_on_access": True,
            }
        },
    )
```

:::

### Body key

Use a custom key for caching responses with request bodies:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
)

async with client:
    response = await client.post(
        "https://api.example.com/data",
        json={"query": "search"},
        context={
            "caching": {
                "body_key": "custom_key",
            }
        },
    )
```

```python [Sync]
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))

with client:
    response = client.post(
        "https://api.example.com/data",
        json={"query": "search"},
        context={
            "caching": {
                "body_key": "custom_key",
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
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
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
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))

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
- **`cached`** - The cached response that was used to serve the request, if available
- **`revalidated`** - Whether the cached response was revalidated with the origin server (see [RFC 9111 validation](https://www.rfc-editor.org/rfc/rfc9111.html#name-validation))
- **`created_at`** - Timestamp of when the cache entry was created

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CachingHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
    caching = response.context.get("caching")

    if caching:
        print(f"From cache: {caching.get('from_cache')}")
        print(f"Revalidated: {caching.get('revalidated')}")
        print(f"Created at: {caching.get('created_at')}")
        if caching.get("cached"):
            print(
                f"Cached response: {caching.get('cached')}"
            )
```

```python [Sync]
from zapros import (
    Client,
    CachingHandler,
    StdNetworkHandler,
)

client = Client(handler=CachingHandler(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
    )
    caching = response.context.get("caching")

    if caching:
        print(f"From cache: {caching.get('from_cache')}")
        print(f"Revalidated: {caching.get('revalidated')}")
        print(f"Created at: {caching.get('created_at')}")
        if caching.get("cached"):
            print(
                f"Cached response: {caching.get('cached')}"
            )
```

:::

## Combining with other handlers

Chain `CachingHandler` with other handlers like cookies or retries:

```python
from zapros import (
    AsyncClient,
    CachingHandler,
    CookieHandler,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CachingHandler(
        CookieHandler(AsyncStdNetworkHandler())
    )
)
```
