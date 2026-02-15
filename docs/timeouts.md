# Timeouts

Timeouts in Zapros can be configured at the handler level or per-request to control connection, read, write, and total operation timeouts.

## Setup

Configure timeouts when creating your handler:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=AsyncStdNetworkHandler(
        timeout=30.0,
        connect_timeout=5.0,
        read_timeout=10.0,
        write_timeout=10.0,
    )
)
```

```python [Sync]
from zapros import (
    Client,
    StdNetworkHandler,
)

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

## Timeout types

Zapros supports four types of timeouts:

- **`total` / `total_timeout`** - Maximum time from request start until response headers are received
- **`connect_timeout`** - Maximum time to establish a connection
- **`read_timeout`** - Maximum time per individual socket read operation
- **`write_timeout`** - Maximum time per individual socket write operation

All timeout values are in seconds and can be `None` (no timeout) or a positive float.

::: tip Per-operation timeouts
`read_timeout` and `write_timeout` are per-operation, not accumulative. They apply to each individual socket read/write operation. For large downloads or uploads, these timeouts won't accumulate across all operations, so you can keep them reasonably low while disabling the `total` timeout.
:::

## Handler-level timeouts

Set default timeouts for all requests made by the handler:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
)

handler = AsyncStdNetworkHandler(
    timeout=30.0,
    read_timeout=10.0,
)

client = AsyncClient(handler=handler)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import (
    Client,
    StdNetworkHandler,
)

handler = StdNetworkHandler(
    total_timeout=30.0,
    read_timeout=10.0,
)

client = Client(handler=handler)

with client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

## Per-request timeouts

Override handler defaults for specific requests using request context:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
)

client = AsyncClient(handler=AsyncStdNetworkHandler())

async with client:
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

```python [Sync]
from zapros import (
    Client,
    StdNetworkHandler,
)

client = Client(handler=StdNetworkHandler())

with client:
    response = client.get(
        "https://api.example.com/data",
        context={
            "timeouts": {
                "total": 15.0,
                "read": 5.0,
            }
        },
    )
```

:::

Per-request timeouts override handler defaults. Unspecified timeout types fall back to handler defaults.

## Total timeout behavior

The `total` timeout (or `total_timeout` for sync) applies from the start of the request until response headers are received. It includes:

- Time waiting for an available connection from the pool
- Connection establishment (if creating a new connection)
- Writing the request
- Reading response headers

When a `total` timeout is set, it takes precedence over individual phase timeouts. For example:

```python
handler = StdNetworkHandler(
    total_timeout=5.0,
    connect_timeout=10.0,
)
```

The connection will timeout after 5 seconds total, even though `connect_timeout` is set to 10 seconds.

## No timeout

Set a timeout to `None` to disable it:

```python
handler = StdNetworkHandler(
    total_timeout=None,
    read_timeout=30.0,
)
```

## Timeout errors

When a timeout occurs, Zapros raises a subclass of `TimeoutError`:

| Exception | Raised when |
|---|---|
| `ConnectTimeoutError` | Connection establishment times out |
| `ReadTimeoutError` | A socket read operation times out |
| `WriteTimeoutError` | A socket write operation times out |
| `TotalTimeoutError` | The total request deadline is exceeded |
| `PoolTimeoutError` | Waiting for a connection pool slot times out |

Catch `TimeoutError` to handle any timeout:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
    TimeoutError,
)

client = AsyncClient(
    handler=AsyncStdNetworkHandler(total_timeout=1.0)
)

async with client:
    try:
        response = await client.get(
            "https://slow-api.example.com",
        )
    except TimeoutError:
        print("Request timed out")
```

```python [Sync]
from zapros import (
    Client,
    StdNetworkHandler,
    TimeoutError,
)

client = Client(
    handler=StdNetworkHandler(total_timeout=1.0)
)

with client:
    try:
        response = client.get(
            "https://slow-api.example.com",
        )
    except TimeoutError:
        print("Request timed out")
```

:::

Or catch a specific subclass for more granular handling:

```python
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
    ConnectTimeoutError,
    ReadTimeoutError,
)

async with AsyncClient(
    handler=AsyncStdNetworkHandler(
        connect_timeout=2.0,
        read_timeout=5.0,
    )
) as client:
    try:
        response = await client.get(
            "https://api.example.com/data",
        )
    except ConnectTimeoutError:
        print("Could not connect")
    except ReadTimeoutError:
        print("Server stopped responding")
```
