# Sending Requests

How to make HTTP requests with Zapros: clients, URLs, query parameters, request bodies, headers, and reading responses. Always import from the top-level `zapros` package.

## Clients

Two separate client classes with identical APIs: `AsyncClient` (async) and `Client` (sync). Always use them as context managers.

```python
import asyncio
from zapros import AsyncClient, Client


async def main():
    async with AsyncClient() as client:
        response = await client.get("https://httpbin.org/get")
        print(response.status)             # 200
        print(response.headers["content-type"])
        print(response.text)


asyncio.run(main())

# Sync — same API, no await
with Client() as client:
    response = client.get("https://httpbin.org/get")
```

Verb methods: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`. Generic: `client.request(method, url, ...)`. Streaming: `client.stream(method, url, ...)` (context manager, see below).

Every request method accepts keyword-only options: `headers`, `params`, `auth`, `trailers`, `context`, `handler`. `post`/`put`/`patch`/`delete`/`options` additionally accept at most one body argument (`json`, `form`, `body`, `multipart`); `get`/`head` take none.

### Client-level configuration

```python
async with AsyncClient(
    base_url="https://api.example.com/v1/",       # trailing slash matters, see below
    default_headers={"User-Agent": "MyApp/1.0"},  # per-request headers override these
    default_params={"version": "1"},              # merged into every request
    auth=("user", "pass"),                        # or a bearer token string
) as client:
    response = await client.get("users")          # -> https://api.example.com/v1/users
```

`base_url` resolution follows the WHATWG URL Standard:

| Base URL | Endpoint | Result |
|----------|----------|--------|
| `https://api.example.com/v1/` | `users` | `https://api.example.com/v1/users` |
| `https://api.example.com/v1` | `users` | `https://api.example.com/users` (last segment replaced!) |
| `https://api.example.com/v1/` | `/health` | `https://api.example.com/health` |
| `https://api.example.com/v1/` | `https://other.com/path` | `https://other.com/path` |

- Always end `base_url` with `/` when you want relative paths appended.
- Query parameters on `base_url` are dropped. Use `default_params` instead.

### Async / sync mismatch

Some objects (e.g. `Response`, `Part`) work in both modes, and you must call the variant matching your client: `aread`/`read`, `async_iter_bytes`/`iter_bytes`, `aclose`/`close`. Calling the wrong one raises `AsyncSyncMismatchError`. Rule of thumb: I/O methods have an `a`/`async_` prefixed variant for async use. Likewise, don't pass a sync iterator (e.g. `Part.stream(iter([...]))`) to an `AsyncClient`.

## URLs

`url` accepts a `str` or a `URL` (from [pywhatwgurl](https://github.com/pywhatwgurl/pywhatwgurl), re-exported as `zapros.URL`, WHATWG-compatible).

```python
from zapros import URL

url = URL("https://api.example.com:8080/users?page=1#section")
url.protocol   # "https:"
url.hostname   # "api.example.com"
url.port       # "8080"
url.pathname   # "/users"
url.search     # "?page=1"
url.hash       # "#section"

url.search_params["limit"] = "10"   # mutate query
str(url) / url.to_string()

response = await client.get(url)    # URL objects are accepted directly
```

## Query Parameters

Pass `params=`; values are percent-encoded automatically. Accepted forms:

```python
from zapros import URLSearchParams

params={"q": "hello world", "page": "1"}               # mapping
params=[["q", "hello world"], ["page", "1"]]            # list of pairs
params=URLSearchParams("q=hello+world&page=1")         # URLSearchParams
params="q=hello+world&page=1"                          # pre-encoded string
```

Repeated query keys are **not** supported: a list value, a list of pairs with duplicate names, or `?a=1&a=2` in the URL all collapse to the first value. (`form=` does keep repeats, see below.)

Merge order, lowest to highest priority; same key in a higher source overwrites the lower one:

1. `default_params` on the client
2. query string already in the `url`
3. `params=` argument

```python
async with AsyncClient(default_params={"version": "1"}) as client:
    await client.get("https://api.example.com/search?lang=en", params={"q": "zapros"})
    # GET /search?version=1&lang=en&q=zapros

    await client.get("https://api.example.com/items?tag=python", params={"tag": "http"})
    # GET /items?tag=http
```

## Headers

Pass a plain mapping or a `Headers` object. `Headers` is case-insensitive and supports multiple values per name.

```python
from zapros import Headers

h = Headers({"Content-Type": "application/json"})
h["content-type"]              # case-insensitive lookup
h.get("Accept", "*/*")
"Accept" in h
h.add("Set-Cookie", "a=1"); h.add("Set-Cookie", "b=2")
h["Set-Cookie"]                # first value
h.getall("Set-Cookie")         # all values
h.items() / h.keys() / h.values() / h.list() / h.copy()

response = await client.get(url, headers={"Authorization": "Bearer token", "Accept": "application/json"})
```

Zapros adds these automatically **only if absent** (override by passing them, any case): `Host`, `User-Agent` (`python-zapros/<version>`), `Accept: */*`, `Accept-Encoding`, `Content-Length` (bytes bodies), `Transfer-Encoding: chunked` (streaming bodies), and `Content-Type` for `json`/`form`/`multipart`.

Request trailers (HTTP/1.1 chunked trailers): `trailers={"Checksum": "..."}`.

## Request Bodies

Exactly one of `json`, `form`, `body`, `multipart` per request.

### JSON — `json=`

Any JSON-serialisable value; compact separators, UTF-8. Sets `Content-Type: application/json`.

```python
await client.post(url, json={"name": "alice", "age": 30})
```

### Form — `form=`

Accepts a mapping, a mapping with list values (repeated key), a list of pairs, `URLSearchParams`, or a pre-encoded string. Sets `Content-Type: application/x-www-form-urlencoded`.

```python
await client.post(url, form={"username": "alice", "roles": ["admin", "editor"]})
```

### Raw bytes — `body=bytes`

Sets `Content-Length`. **No `Content-Type` is inferred** — pass it in `headers` if the server needs one.

```python
await client.post(url, body=b"\x00\x01", headers={"Content-Type": "application/octet-stream"})
```

### Streaming body — `body=<iterator>`

Async iterator/generator for `AsyncClient`, sync iterator for `Client`. Sent with `Transfer-Encoding: chunked`; set `Content-Length` explicitly in `headers` if the size is known to skip chunking. Streaming bodies are not replayable (retries/redirects can't resend them).

```python
async def file_chunks(path, chunk_size=65536):
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk

await client.post(url, body=file_chunks("large.bin"), headers={"Content-Type": "application/octet-stream"})
```

### Multipart — `multipart=`

Build with `Multipart` (chainable). Sets `Content-Type: multipart/form-data; boundary=...`.

```python
from zapros import Multipart, Part

multipart = (
    Multipart()
    .text("description", "monthly report")
    .file("file", "report.pdf")             # filename + MIME type inferred from path
    .part("raw", Part.bytes(b"content").file_name("hello.txt").mime_type("text/plain"))
)
await client.post(url, multipart=multipart)
```

`Part` constructors: `Part.bytes(...)`, `Part.text(...)`, `Part.stream(...)` (sync iterator, for `Client`), `Part.async_stream(...)` (async iterator, for `AsyncClient`). Chain `.file_name(name)` / `.mime_type(mime)` to override the disposition filename and part `Content-Type`.

## Reading Responses

```python
response = await client.get("https://httpbin.org/json")

response.status                 # int
response.headers                # Headers (case-insensitive)
response.headers.getall("set-cookie")
response.encoding               # from Content-Type charset, defaults to "utf-8"

await response.aread()          # bytes (sync: response.read())
response.text                   # str, decoded with response.encoding
response.json                   # parsed JSON (property, not a method)
response.request                # originating Request, or None
```

- Body is decompressed automatically (`gzip`, `deflate`, `br`, `zstd`, stacked encodings). `iter_raw` / `async_iter_raw` yields the still-compressed bytes.
- Once read, content is cached: repeated `read()` returns the same bytes object.

### Streaming responses

Use `client.stream(...)` as a context manager so the connection is released even on early `break` or exception. Iterate with `async_iter_bytes` / `async_iter_text` / `async_iter_raw` (sync: `iter_bytes` / `iter_text` / `iter_raw`); default `chunk_size=16384`.

```python
async with AsyncClient() as client:
    async with client.stream("GET", "https://httpbin.org/stream/100") as response:
        async for chunk in response.async_iter_bytes(chunk_size=4096):
            process(chunk)

# Sync
with Client() as client:
    with client.stream("GET", "https://httpbin.org/stream/100") as response:
        for chunk in response.iter_bytes():
            process(chunk)
```

## Building `Request` / `Response` directly

Useful in handlers, middlewares, and tests.

```python
from zapros import Request, Response, URL

request = Request(URL("https://api.example.com/users"), "POST", json={"name": "Alice"})
# also: form=..., text="Hello", body=b"raw" / iterator
request.headers["Content-Type"]   # "application/json" (auto)
request.body                      # b'{"name":"Alice"}'
request.is_replayable()           # False for streaming bodies

response = Response(200, json={"ok": True}, request=request)
# also: text="...", content=b"...", headers={...}
```

## Quick Checklist

- Use `async with AsyncClient()` / `with Client()`; match `a*`/`async_*` methods to the client type.
- `base_url` needs a trailing `/`; put shared query params in `default_params`, not in `base_url`.
- One body kwarg per request; `body=bytes` needs an explicit `Content-Type`.
- `response.json` is a property; read bodies with `await response.aread()` / `response.read()`.
- Always wrap `client.stream()` in a context manager.
- `response.text` / `response.json` raise `ResponseNotRead` until the body has been read.
