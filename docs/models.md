# Core Models

Zapros uses three core models: `Headers`, `Request`, and `Response`. It's important to know how they work because you might need them when writing a custom handler, or using one of Zapros's built-in ones.

## Headers

Case-insensitive dictionary for HTTP headers with multi-value support.

**Creating and accessing:**

```python
from zapros import Headers

headers = Headers({"Content-Type": "application/json"})
headers["content-type"]  # Works (case-insensitive)
headers["CONTENT-TYPE"]  # Also works

headers.get("Accept", "*/*")  # With default
"Accept" in headers  # True
len(headers)  # Number of unique headers
```

**Multi-value headers:**

```python
headers = Headers()
headers.add("Set-Cookie", "session=abc")
headers.add("Set-Cookie", "user=john")

headers["Set-Cookie"]  # "session=abc" (first value)
headers.getall("Set-Cookie")  # ["session=abc", "user=john"]
```

**Dictionary operations:**

```python
headers = Headers({"Accept": "application/json"})

for name, value in headers.items():
    print(f"{name}: {value}")

list(headers.keys())  # ["accept"]
list(headers.values())  # ["application/json"]
headers.list()  # [("accept", "application/json")]

copied = headers.copy()  # Independent copy
```

**Using in requests:**

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient() as client:
    response = await client.get(
        "https://api.example.com/data",
        headers={
            "Authorization": "Bearer token",
            "Accept": "application/json",
        },
    )
```

```python [Sync]
from zapros import Client

with Client() as client:
    response = client.get(
        "https://api.example.com/data",
        headers={
            "Authorization": "Bearer token",
            "Accept": "application/json",
        },
    )
```

:::

**Accessing response headers:**

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.get("https://httpbin.org/get")

    content_type = response.headers["content-type"]
    server = response.headers.get("server", "unknown")

    if "set-cookie" in response.headers:
        cookies = response.headers.getall("set-cookie")
```

```python [Sync]
with Client() as client:
    response = client.get("https://httpbin.org/get")

    content_type = response.headers["content-type"]
    server = response.headers.get("server", "unknown")

    if "set-cookie" in response.headers:
        cookies = response.headers.getall("set-cookie")
```

:::

## Request

Represents an HTTP request with automatic header generation:

```python
from zapros import Request
from pywhatwgurl import URL

url = URL("https://api.example.com/users")

request = Request(url, "POST", json={"name": "Alice"})

request.headers[
    "Content-Type"
]  # "application/json" (auto-set)
request.headers["Host"]  # "api.example.com" (auto-set)
request.headers["Accept"]  # "*/*" (auto-set)
request.body  # b'{"name": "Alice"}'
```

**Body convenience parameters:**

```python
Request(url, "POST", json={"key": "value"})
Request(url, "POST", form={"user": "alice"})
Request(url, "POST", text="Hello")
Request(url, "POST", body=b"raw bytes")
```

**Automatic headers** (only added if not present):
- `Host` — from URL
- `User-Agent` — zapros/version
- `Accept` — `*/*`
- `Accept-Encoding` — supported compressions
- `Content-Length` — for bytes bodies
- `Transfer-Encoding: chunked` — for streaming bodies

**Overriding headers** (case-insensitive):

```python
Request(
    url,
    "GET",
    headers={"host": "custom.com"},  # Lowercase works
)
```

**Replayability:**

```python
Request(url, "POST", body=b"data").is_replayable()  # True


def stream():
    yield b"chunk1"


Request(url, "POST", body=stream()).is_replayable()  # False
```

Streaming bodies can't be replayed because the iterator is consumed.

## Response

Represents an HTTP response with automatic decompression.

**Basic attributes:**

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient() as client:
    response = await client.get("https://httpbin.org/get")

    print(response.status)  # 200
    print(
        response.headers["content-type"]
    )  # "application/json"
```

```python [Sync]
from zapros import Client

with Client() as client:
    response = client.get("https://httpbin.org/get")

    print(response.status)  # 200
    print(
        response.headers["content-type"]
    )  # "application/json"
```

:::

**Creating responses:**

```python
from zapros import Response

response = Response(200, json={"status": "ok"})
response = Response(200, text="Hello")
response = Response(200, content=b"raw bytes")
```

**Reading content:**

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.get("https://httpbin.org/json")

    data = await response.aread()  # bytes
     text = response.text  # str
     json_data = response.json  # parsed JSON
```

```python [Sync]
with Client() as client:
    response = client.get("https://httpbin.org/json")

    data = response.read()  # bytes
    text = response.text  # str
    json_data = response.json  # parsed JSON
```

:::

**Character encoding:**

```python
response.headers[
    "content-type"
]  # "text/html; charset=iso-8859-1"
response.encoding  # "iso-8859-1"

response.text  # Decoded with iso-8859-1
```

If no charset is specified, defaults to `utf-8`.

**Streaming content:**

::: code-group

```python [Async]
async with AsyncClient() as client:
    response = await client.get(
        "https://httpbin.org/stream-bytes/10000",
    )

    async for chunk in response.async_iter_bytes():
        process(chunk)

    async for text in response.async_iter_text():
        print(text)

    async for raw in response.async_iter_raw():
        save_compressed(raw)
```

```python [Sync]
with Client() as client:
    response = client.get(
        "https://httpbin.org/stream-bytes/10000",
    )

    for chunk in response.iter_bytes():
        process(chunk)

    for text in response.iter_text():
        print(text)

    for raw in response.iter_raw():
        save_compressed(raw)
```

:::

Custom chunk size (default 8192 bytes):

```python
for chunk in response.iter_bytes(chunk_size=4096):
    process(chunk)
```

**Stream caching:**

Once consumed, content is cached as bytes:

```python
data = response.read()  # Consumes stream
data2 = response.read()  # Returns cached (same object)
assert data is data2
```

**Automatic decompression:**

```python
import gzip

compressed = gzip.compress(b"Hello")
response = Response(
    200,
    headers={"Content-Encoding": "gzip"},
    content=compressed,
)

response.read()  # b"Hello" (auto-decompressed)
response.iter_raw()  # Returns compressed bytes
```

Supports: `gzip`, `deflate`, `br` (brotli), `zstd`, multiple encodings.

**Type safety:**

```python
sync_response.iter_bytes()  # OK
sync_response.async_iter_bytes()  # TypeError: use `iter_bytes`

async_response.async_iter_bytes()  # OK
async_response.iter_bytes()  # TypeError: use `async_iter_bytes`
```

**Resource cleanup:**

When using `client.stream()`, always use context managers:

::: code-group

```python [Async]
async with AsyncClient() as client:
    async with client.stream(
        "GET", "https://httpbin.org/stream/10"
    ) as response:
        async for chunk in response.async_iter_bytes():
            process(chunk)
```

```python [Sync]
with Client() as client:
    with client.stream(
        "GET", "https://httpbin.org/stream/10"
    ) as response:
        for chunk in response.iter_bytes():
            process(chunk)
```

:::

The context manager calls `aclose()` or `close()` automatically, even if you break early or an exception is raised.
