---
title: Authentication
description: Built-in helper for Bearer token and Basic authentication.
---

# Authentication

Zapros provides a convenient `auth` parameter at both the client and request level. This parameter accepts either a string (for Bearer tokens) or a tuple of `(username, password)` (for Basic authentication), automatically adding the appropriate `Authorization` header.

## Bearer Token Authentication

Pass a string to the `auth` parameter to use Bearer token authentication.

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient


async def main():
    async with AsyncClient(
        auth="your-token-here"
    ) as client:
        response = await client.get(
            "https://api.example.com/protected",
        )
        print(response.status)


asyncio.run(main())
```

```python [Sync]
from zapros import Client

with Client(auth="your-token-here") as client:
    response = client.get(
        "https://api.example.com/protected",
    )
    print(response.status)
```

:::

This automatically adds the header `Authorization: Bearer your-token-here` to all requests.

## Basic Authentication

Pass a tuple of `(username, password)` to the `auth` parameter to use Basic authentication.

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient


async def main():
    async with AsyncClient(
        auth=("username", "password")
    ) as client:
        response = await client.get(
            "https://api.example.com/protected",
        )
        print(response.status)


asyncio.run(main())
```

```python [Sync]
from zapros import Client

with Client(auth=("username", "password")) as client:
    response = client.get(
        "https://api.example.com/protected",
    )
    print(response.status)
```

:::

This automatically encodes the credentials as base64 and adds the header `Authorization: Basic <base64-credentials>` to all requests.

## Per-Request Authentication

You can also configure authentication on a per-request basis, which overrides any client-level authentication:

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient


async def main():
    async with AsyncClient(auth="default-token") as client:
        # Uses default-token
        response1 = await client.get(
            "https://api.example.com/data",
        )

        # Overrides with request-token
        response2 = await client.get(
            "https://api.example.com/special",
            auth="request-token",
        )

        # Uses basic auth for this request only
        response3 = await client.get(
            "https://api.example.com/legacy",
            auth=("user", "pass"),
        )


asyncio.run(main())
```

```python [Sync]
from zapros import Client

with Client(auth="default-token") as client:
    # Uses default-token
    response1 = client.get(
        "https://api.example.com/data",
    )

    # Overrides with request-token
    response2 = client.get(
        "https://api.example.com/special",
        auth="request-token",
    )

    # Uses basic auth for this request only
    response3 = client.get(
        "https://api.example.com/legacy",
        auth=("user", "pass"),
    )
```

:::

## Manual Header Alternative

If you need more control or different authentication schemes, you can always set headers manually:

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient


async def main():
    async with AsyncClient(
        default_headers={
            "Authorization": "Custom token-here"
        }
    ) as client:
        response = await client.get(
            "https://api.example.com/protected",
        )
        print(response.status)


asyncio.run(main())
```

```python [Sync]
from zapros import Client

with Client(
    default_headers={"Authorization": "Custom token-here"}
) as client:
    response = client.get(
        "https://api.example.com/protected",
    )
    print(response.status)
```

:::

Or per-request:

```python
response = client.get(
    "https://api.example.com/protected",
    headers={"Authorization": "Bearer different-token"},
)
```
