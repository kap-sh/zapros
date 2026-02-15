---
title: HTTP Redirects
description: RFC 9110 compliant redirect handling
---

# HTTP Redirects

Zapros includes a `RedirectHandler` for following HTTP redirects (3xx status codes).

## Quickstart

To enable redirect following, wrap your handler with `RedirectHandler`:

::: code-group

```python [Async]
import asyncio
from zapros import (
    AsyncClient,
    RedirectHandler,
    AsyncStdNetworkHandler,
)


async def main():
    base_handler = AsyncStdNetworkHandler()
    handler = RedirectHandler(
        base_handler, max_redirects=10
    )

    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            "https://api.example.com/redirect",
        )
        print(
            response.status
        )  # 200 (after following redirects)


asyncio.run(main())
```

```python [Sync]
from zapros import (
    Client,
    RedirectHandler,
    StdNetworkHandler,
)

base_handler = StdNetworkHandler()
handler = RedirectHandler(base_handler, max_redirects=10)

with Client(handler=handler) as client:
    response = client.get(
        "https://api.example.com/redirect",
    )
    print(
        response.status
    )  # 200 (after following redirects)
```

:::

## Configuration

### Max Redirects

Control the maximum number of redirects to follow. Default is `10`.

::: code-group

```python [Async]
import asyncio
from zapros import (
    AsyncClient,
    RedirectHandler,
    AsyncStdNetworkHandler,
)


async def main():
    base_handler = AsyncStdNetworkHandler()
    handler = RedirectHandler(base_handler, max_redirects=5)

    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            "https://api.example.com/many-redirects",
        )
        if response.status in {
            301,
            302,
            303,
            307,
            308,
        }:
            print("Stopped at redirect limit")


asyncio.run(main())
```

```python [Sync]
from zapros import (
    Client,
    RedirectHandler,
    StdNetworkHandler,
)

base_handler = StdNetworkHandler()
handler = RedirectHandler(base_handler, max_redirects=5)

with Client(handler=handler) as client:
    response = client.get(
        "https://api.example.com/many-redirects",
    )
    if response.status in {
        301,
        302,
        303,
        307,
        308,
    }:
        print("Stopped at redirect limit")
```

:::

## Method Rewriting

Different redirect status codes have different method rewriting semantics per RFC 9110:

### 303 See Other

Converts all methods to GET, except HEAD which remains HEAD:

::: code-group

```python [Async]
import asyncio
from zapros import (
    AsyncClient,
    RedirectHandler,
    AsyncStdNetworkHandler,
)


async def main():
    handler = RedirectHandler(AsyncStdNetworkHandler())

    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            "https://api.example.com/submit",
            json={"data": "value"},
        )
        print(response.status)  # 200


asyncio.run(main())
```

```python [Sync]
from zapros import (
    Client,
    RedirectHandler,
    StdNetworkHandler,
)

handler = RedirectHandler(StdNetworkHandler())

with Client(handler=handler) as client:
    response = client.post(
        "https://api.example.com/submit",
        json={"data": "value"},
    )
    print(response.status)  # 200
```

:::

### 301/302 Historical Behavior

Only POST is converted to GET. Other methods (PUT, PATCH, DELETE) are preserved:

::: code-group

```python [Async]
import asyncio
from zapros import (
    AsyncClient,
    RedirectHandler,
    AsyncStdNetworkHandler,
)


async def main():
    handler = RedirectHandler(AsyncStdNetworkHandler())

    async with AsyncClient(handler=handler) as client:
        post_response = await client.post(
            "https://api.example.com/old",
            json={},
        )
        delete_response = await client.delete(
            "https://api.example.com/old",
        )


asyncio.run(main())
```

```python [Sync]
from zapros import (
    Client,
    RedirectHandler,
    StdNetworkHandler,
)

handler = RedirectHandler(StdNetworkHandler())

with Client(handler=handler) as client:
    post_response = client.post(
        "https://api.example.com/old",
        json={},
    )
    delete_response = client.delete(
        "https://api.example.com/old",
    )
```

:::

### 307/308 Method Preservation

Method and body are always preserved:

::: code-group

```python [Async]
import asyncio
from zapros import (
    AsyncClient,
    RedirectHandler,
    AsyncStdNetworkHandler,
)


async def main():
    handler = RedirectHandler(AsyncStdNetworkHandler())

    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            "https://api.example.com/v1/resource",
            json={"data": "preserved"},
        )
        print(response.status)  # 200


asyncio.run(main())
```

```python [Sync]
from zapros import (
    Client,
    RedirectHandler,
    StdNetworkHandler,
)

handler = RedirectHandler(StdNetworkHandler())

with Client(handler=handler) as client:
    response = client.post(
        "https://api.example.com/v1/resource",
        json={"data": "preserved"},
    )
    print(response.status)  # 200
```

:::

## Body Handling

### Body Removal

When a redirect changes the method to GET or HEAD (e.g., 303 redirects), the request body is removed.

### Body Preservation

For 307/308 redirects, the body is preserved and sent to the redirect target.

### Streaming Bodies Limitation

Streaming bodies (generators/iterators) cannot be replayed on redirect. If a 307/308 redirect occurs with a non-bytes body, an error is raised:

```python
raise NotImplementedError(
    "Redirect with non-replayable body is not supported"
)
```

For requests that may redirect, use bytes instead:

```python
data = b"large file content"

response = await client.post(
    "https://api.example.com/upload",
    body=data,
)
```


