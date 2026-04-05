# Standard Library

Zapros ships with standard-library-backed handlers for both sync and async clients: `StdNetworkHandler` and `AsyncStdNetworkHandler`.

`Client` uses `StdNetworkHandler` by default. `AsyncClient` uses `AsyncStdNetworkHandler` by default outside browser environments.

These handlers implement HTTP/1.1 in pure Python using `socket` / `asyncio`, `ssl`, and `h11`.

## Usage

::: code-group

```python [Async]
from zapros import AsyncClient

async with AsyncClient() as client:
    response = await client.get("https://api.example.com/data")
    print(response.text)
```

```python [Sync]
from zapros import Client

with Client() as client:
    response = client.get("https://api.example.com/data")
    print(response.text)
```

:::

## Timeouts

Timeouts are configured on the standard library handlers and can be overridden per request.

::: code-group

```python [Async]
from zapros import AsyncClient, AsyncStdNetworkHandler

client = AsyncClient(
    handler=AsyncStdNetworkHandler(
        total_timeout=30.0,
        connect_timeout=5.0,
        read_timeout=10.0,
        write_timeout=10.0,
    )
)
```

```python [Sync]
from zapros import Client, StdNetworkHandler

client = Client(
    handler=StdNetworkHandler(
        total_timeout=30.0,
        connect_timeout=5.0,
        read_timeout=10.0,
        write_timeout=10.0,
    )
)
```

:::

Supported timeout types:

- `total` / `total_timeout`: from request start until response headers are received
- `connect_timeout`: connection establishment
- `read_timeout`: each socket read operation
- `write_timeout`: each socket write operation

Per-request values go through `context["timeouts"]` and override handler defaults:

```python
response = await client.get(
    "https://api.example.com/data",
    context={
        "timeouts": {
            "total": 15.0,
            "read": 5.0,
        }
    },
)
```

`read_timeout` and `write_timeout` are per-operation timeouts, not cumulative across the full request. Set any timeout to `None` to disable it.

When a timeout is hit, Zapros raises a `TimeoutError` subclass such as `ConnectTimeoutError`, `ReadTimeoutError`, `WriteTimeoutError`, `TotalTimeoutError`, or `PoolTimeoutError`.

## Proxies

Proxy support for the standard library handlers is added through `ProxyMiddleware`.

::: code-group

```python [Async]
from zapros import AsyncClient, AsyncStdNetworkHandler, ProxyMiddleware

client = AsyncClient(
    handler=ProxyMiddleware(AsyncStdNetworkHandler())
)
```

```python [Sync]
from zapros import Client, ProxyMiddleware, StdNetworkHandler

client = Client(
    handler=ProxyMiddleware(StdNetworkHandler())
)
```

:::

Environment-driven proxy configuration is supported through `http_proxy`, `https_proxy`, `all_proxy`, and their uppercase variants.

Use `NO_PROXY` to bypass the proxy for specific hosts:

```bash
export https_proxy="http://proxy.example.com:8080"
export NO_PROXY="localhost,127.0.0.1,.internal.corp"
```

You can also override the proxy per request:

```python
response = await client.get(
    "https://api.example.com/data",
    context={
        "network": {
            "proxy": {
                "url": "http://special-proxy.example.com:8080"
            }
        }
    },
)
```

Authenticated proxies use the same `url` field with credentials embedded in the proxy URL:

```bash
export https_proxy="http://username:password@proxy.example.com:8080"
```

SOCKS5 proxies are also supported. To use SOCKS5 proxies, install Zapros with the `socks` feature:

```bash
pip install zapros[socks]
```

## SSL Configuration

To set a custom SSL context, pass it to the transport:

::: code-group

```python [Async]
import ssl

from zapros import AsyncClient, AsyncIOTransport, AsyncStdNetworkHandler

custom_ssl_context = ssl.create_default_context()

async with AsyncClient(
    handler=AsyncStdNetworkHandler(
        transport=AsyncIOTransport(ssl_context=custom_ssl_context)
    )
) as client:
    ...
```

```python [Sync]
import ssl

from zapros import Client, StdNetworkHandler, SyncTransport

custom_ssl_context = ssl.create_default_context()

with Client(
    handler=StdNetworkHandler(
        transport=SyncTransport(ssl_context=custom_ssl_context)
    )
) as client:
    ...
```

:::

