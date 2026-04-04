# Async & Sync Separation

To support both async and sync APIs, Zapros provides two versions of some APIs, distinguished by prefixes (e.g., `AsyncClient`, `AsyncBaseHandler`, `aread`, `async_iter_bytes`).

In some cases, Zapros uses entirely separate classes for async and sync APIs (like `Client` and `AsyncClient`). We try to avoid this where possible so users don't need to deal with two different classes in their codebase, but in some cases it's necessary to keep the API clean.

Some classes support both sync and async APIs (mixed classes). When using these, you must call the appropriate version for your context, or you'll get an error. For example:

```python
async def stream_data():
    yield b"data"

response = Response(200, content=stream_data())
response.close()
```

This raises an error because the response has an async stream but you're calling the sync `close()` instead of `aclose()`.

In these cases, Zapros raises an `AsyncSyncMismatchError`.

## AsyncSyncMismatchError

When you incorrectly use mixed classes that support both async and sync APIs, you'll get an `AsyncSyncMismatchError`.

If you encounter this error, check the method names you're using:

1. If you use `AsyncClient`, make sure to use the async version of methods when available (e.g., `aclose` instead of `close`).
2. If you use `Client`, make sure to use the sync version of methods when available (e.g., `close` instead of `aclose`).

As a rule of thumb: if a method performs I/O-bound operations, it likely has an async version with a prefix (e.g., `aread`, `async_iter_bytes`, `aclose`).

Here are examples of **incorrect** usage that raise `AsyncSyncMismatchError`:


### Using a sync multipart stream with an async client

```python
from zapros import AsyncClient, Multipart, Part

client = AsyncClient()


async def main():
    await client.get(
        "https://httpbin.org/get",
        multipart=Multipart().part(
            "test",
            Part.stream(iter([])),
        ),
    )
```


