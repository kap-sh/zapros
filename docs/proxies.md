# Proxies

Zapros support HTTP and HTTPS proxies, and can respect the environment variables like curl-style proxy configurations

## Using environment variables

Set proxy environment variables before running your application:

```bash
export http_proxy="http://proxy.example.com:8080"
export https_proxy="http://proxy.example.com:8080"
```

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    ProxyMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=ProxyMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get("https://api.example.com/data")
```

```python [Sync]
from zapros import (
    Client,
    ProxyMiddleware,
    StdNetworkHandler,
)

client = Client(
    handler=ProxyMiddleware(StdNetworkHandler())
)

with client:
    response = client.get("https://api.example.com/data")
```

:::

Supported environment variables: `http_proxy`, `https_proxy`, `all_proxy` (and uppercase variants).

## Excluding hosts from proxy

Use `NO_PROXY` to bypass the proxy for specific hosts:

```bash
export https_proxy="http://proxy.example.com:8080"
export NO_PROXY="localhost,127.0.0.1,.internal.corp"
```

::: code-group

```python [Async]
async with client:
    await client.get("https://internal.corp/api")
```

```python [Sync]
with client:
    client.get("https://internal.corp/api")
```

:::

The `.internal.corp` pattern matches all subdomains like `api.internal.corp`.

## Per-request proxy

Override the proxy for individual requests:

::: code-group

```python [Async]
async with client:
    response = await client.get(
        "https://api.example.com/data",
        context={
            "network": {
                "proxy": {"url": "http://special-proxy.example.com:8080"}
            }
        },
    )
```

```python [Sync]
with client:
    response = client.get(
        "https://api.example.com/data",
        context={
            "network": {
                "proxy": {"url": "http://special-proxy.example.com:8080"}
            }
        },
    )
```

:::

## Authenticated proxies

Include credentials in the proxy URL:

::: code-group

```python [Async]
async with client:
    response = await client.get(
        "https://api.example.com/data",
        context={
            "network": {
                "proxy": {
                    "url": "http://username:password@proxy.example.com:8080"
                }
            }
        },
    )
```

```python [Sync]
with client:
    response = client.get(
        "https://api.example.com/data",
        context={
            "network": {
                "proxy": {
                    "url": "http://username:password@proxy.example.com:8080"
                }
            }
        },
    )
```

:::

Or set it via environment variable:

```bash
export https_proxy="http://username:password@proxy.example.com:8080"
```
