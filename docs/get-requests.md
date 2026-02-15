# GET Requests

## Basic GET

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient


async def main():
    async with AsyncClient() as client:
        response = await client.get(
            "https://httpbin.org/get",
        )
        print(response.status)


asyncio.run(main())
```

```python [Sync]
from zapros import Client

with Client() as client:
    response = client.get("https://httpbin.org/get")
    print(response.status)
```

:::

## Query Parameters

Pass a `params` dict to append query parameters to the URL.

> **Note:** If the URL already contains query parameters and you also pass `params=`, both sets are merged. Duplicate keys are kept — they are not deduplicated or overwritten. For example, a URL of `https://example.com?tag=a` with `params={"tag": "b"}` results in `?tag=a&tag=b`.

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.get(
        "https://httpbin.org/get",
        params={
            "search": "python",
            "page": "1",
        },
    )
```

```python [Sync]
with Client() as client:
    response = client.get(
        "https://httpbin.org/get",
        params={
            "search": "python",
            "page": "1",
        },
    )
```

:::

## Reading the Response

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.get("https://httpbin.org/get")

    print(response.status)  # 200
    print(
        response.headers["content-type"]
    )  # application/json
    print(await response.atext())  # response body as string
```

```python [Sync]
with Client() as client:
    response = client.get("https://httpbin.org/get")

    print(response.status)  # 200
    print(
        response.headers["content-type"]
    )  # application/json
    print(response.text())  # response body as string
```

:::

## Streaming a Large Response

Use `stream()` to avoid loading the entire response into memory at once.

::: code-group

```python [Async]
async with AsyncClient() as client:
    async with client.stream(
        "GET",
        "https://httpbin.org/stream/100",
    ) as response:
        async for chunk in response.async_iter_bytes():
            process(chunk)
```

```python [Sync]
with Client() as client:
    with client.stream(
        "GET",
        "https://httpbin.org/stream/100",
    ) as response:
        for chunk in response.iter_bytes():
            process(chunk)
```

:::
