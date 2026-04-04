# Getting Started

## Installation

```bash
pip install zapros
```

## Basic Request

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
        print(response.headers["content-type"])
         print(response.text)


asyncio.run(main())
```

```python [Sync]
from zapros import Client

with Client() as client:
    response = client.get(
        "https://httpbin.org/get",
    )
    print(response.status)
    print(response.headers["content-type"])
     print(response.text)
```

:::

## Query Parameters

::: code-group

```python [Async]
response = await client.get(
    "https://httpbin.org/get",
    params={"page": "1", "limit": "10"},
)
```

```python [Sync]
response = client.get(
    "https://httpbin.org/get",
    params={"page": "1", "limit": "10"},
)
```

:::

## Request Body

### JSON

::: code-group

```python [Async]
response = await client.post(
    "https://httpbin.org/post",
    json={"key": "value"},
)
```

```python [Sync]
response = client.post(
    "https://httpbin.org/post",
    json={"key": "value"},
)
```

:::

### Form (URL-encoded)

::: code-group

```python [Async]
response = await client.post(
    "https://httpbin.org/post",
    form={
        "username": "alice",
        "password": "secret",
    },
)
```

```python [Sync]
response = client.post(
    "https://httpbin.org/post",
    form={
        "username": "alice",
        "password": "secret",
    },
)
```

:::

### Raw bytes

::: code-group

```python [Async]
response = await client.post(
    "https://httpbin.org/post",
    body=b"raw bytes here",
)
```

```python [Sync]
response = client.post(
    "https://httpbin.org/post",
    body=b"raw bytes here",
)
```

:::

## Custom Headers

::: code-group

```python [Async]
response = await client.get(
    "https://httpbin.org/get",
    headers={"Authorization": "Bearer my-token"},
)
```

```python [Sync]
response = client.get(
    "https://httpbin.org/get",
    headers={"Authorization": "Bearer my-token"},
)
```

:::

## Multipart File Upload

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    Multipart,
    Part,
)

file_part = (
    Part
    .bytes(b"file content")
    .file_name("hello.txt")
    .mime_type("text/plain")
)
multipart = (
    Multipart()
    .text("field", "value")
    .part("file", file_part)
)

async with AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        multipart=multipart,
    )
```

```python [Sync]
from zapros import (
    Client,
    Multipart,
    Part,
)

file_part = (
    Part
    .bytes(b"file content")
    .file_name("hello.txt")
    .mime_type("text/plain")
)
multipart = (
    Multipart()
    .text("field", "value")
    .part("file", file_part)
)

with Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        multipart=multipart,
    )
```

:::

## Streaming Responses

Use `stream()` to process the response body incrementally without loading it all into memory.

::: code-group

```python [Async]
async with AsyncClient() as client:
    async with client.stream(
        "GET",
        "https://httpbin.org/stream/10",
    ) as response:
        async for chunk in response.async_iter_bytes():
            process(chunk)
```

```python [Sync]
from zapros import Client

with Client() as client:
    with client.stream(
        "GET",
        "https://httpbin.org/stream/10",
    ) as response:
        for chunk in response.iter_bytes():
            process(chunk)
```
