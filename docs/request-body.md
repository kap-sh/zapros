# Request Body

Zapros supports several body formats, each setting the appropriate `Content-Type` header automatically.

## JSON

Pass any JSON-serialisable value to `json=`. The body is serialised with compact separators and encoded as UTF-8.

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        json={
            "name": "alice",
            "age": 30,
        },
    )
```

```python [Sync]
with Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        json={
            "name": "alice",
            "age": 30,
        },
    )
```

:::

`Content-Type: application/json` is set automatically.

## Form (URL-encoded)

Pass a mapping, a list of pairs, a `URLSearchParams`, or a raw string to `form=`. The body is encoded as `application/x-www-form-urlencoded`.

```python
from pywhatwgurl import URLSearchParams

# plain mapping
form={"username": "alice", "password": "secret"}

# list value for repeated fields
form={"username": "alice", "roles": ["admin", "editor"]}

# list of pairs
form=[["username", "alice"], ["password", "secret"]]

# URLSearchParams
form=URLSearchParams("username=alice&password=secret")

# pre-encoded string
form="username=alice&password=secret"
```

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        form={
            "username": "alice",
            "password": "secret",
        },
    )
```

```python [Sync]
with Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        form={
            "username": "alice",
            "password": "secret",
        },
    )
```

:::

`Content-Type: application/x-www-form-urlencoded` is set automatically.

## Raw Bytes

Pass `bytes` directly to `body=` when you have a pre-encoded payload.

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        body=b"\x00\x01\x02\x03",
        headers={
            "Content-Type": "application/octet-stream"
        },
    )
```

```python [Sync]
with Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        body=b"\x00\x01\x02\x03",
        headers={
            "Content-Type": "application/octet-stream"
        },
    )
```

:::

`Content-Length` is set automatically from the byte length. No `Content-Type` is inferred — set it explicitly if the server requires one.

## Streaming Body

Pass a `Stream` (sync) or `AsyncStream` (async) to `body=` to send data without buffering it in memory. The request is sent with `Transfer-Encoding: chunked`. If you know the total size upfront, set `Content-Length` explicitly — this skips chunked transfer encoding and can make the request slightly faster.

::: code-group

```python [Async]
from zapros import AsyncClient


async def file_chunks(path: str, chunk_size: int = 65536):
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk


async with AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        body=file_chunks("large-file.bin"),
        headers={
            "Content-Type": "application/octet-stream"
        },
    )
```

```python [Sync]
from zapros import Client


def file_chunks(path: str, chunk_size: int = 65536):
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk


with Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        body=file_chunks("large-file.bin"),
        headers={
            "Content-Type": "application/octet-stream"
        },
    )
```

:::

## Multipart

Use `Multipart` to upload files or mixed form data. Each part can be text, raw bytes, or a stream, and can have an explicit filename and MIME type.

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    Multipart,
)

multipart = (
    Multipart()
    .text("description", "monthly report")
    .file("file", "report.pdf")
)

async with AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        multipart=multipart,
    )
```

```python [Sync]
from zapros import Client, Multipart

multipart = (
    Multipart()
    .text("description", "monthly report")
    .file("file", "report.pdf")
)

with Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        multipart=multipart,
    )
```

:::

`Content-Type: multipart/form-data; boundary="..."` is set automatically. `Multipart.file()` infers the filename and MIME type from the path automatically.

For custom parts, use `Part` directly and add it with `.part()`:

```python
from zapros import Multipart, Part

file_part = (
    Part
    .bytes(b"file content")
    .file_name("report.txt")
    .mime_type("text/plain")
)
multipart = (
    Multipart()
    .text("description", "monthly report")
    .part("file", file_part)
)
```

Chain `.file_name(name)` and `.mime_type(mime)` on any part to override the `filename` disposition parameter and `Content-Type`.

> **Note:** Only one of `json`, `form`, `body`, or `multipart` can be passed per request.
