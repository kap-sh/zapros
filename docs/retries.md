# Retries

Retries in Zapros are implemented as a [handler](/handlers) — wrapping another handler to automatically retry failed requests with exponential backoff.

## Setup

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    RetryMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=RetryMiddleware(AsyncStdNetworkHandler())
)
```

```python [Sync]
from zapros import (
    Client,
    RetryMiddleware,
    StdNetworkHandler,
)

client = Client(handler=RetryMiddleware(StdNetworkHandler()))
```

:::

## Basic usage

By default, `RetryMiddleware` retries requests that fail with specific status codes or network errors:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    RetryMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=RetryMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.get(
        "https://api.example.com/data",
    )
```

```python [Sync]
from zapros import (
    Client,
    RetryMiddleware,
    StdNetworkHandler,
)

client = Client(handler=RetryMiddleware(StdNetworkHandler()))

with client:
    response = client.get(
        "https://api.example.com/data",
    )
```

:::

## Default behavior

### Status codes

The following status codes are retried automatically:

- `429` - Too Many Requests (rate limit)
- `500` - Internal Server Error
- `502` - Bad Gateway
- `503` - Service Unavailable
- `504` - Gateway Timeout

### Safe HTTP methods

Only idempotent methods are retried by default:

- `GET`, `HEAD`, `PUT`, `DELETE`, `OPTIONS`, `TRACE`

Non-idempotent methods like `POST` and `PATCH` are **not** retried on status codes to avoid duplicate operations.

### Network errors

Pre-transmission errors are always retried, regardless of HTTP method:

- `ConnectionError`, `ConnectionRefusedError`
- Connection timeouts and DNS errors
- SSL/Certificate errors

```python
client = AsyncClient(
    handler=RetryMiddleware(AsyncStdNetworkHandler())
)

async with client:
    response = await client.post(
        "https://api.example.com/create",
        json={"name": "test"},
    )
```

## Configuration

Customize retry behavior with these parameters:

```python
from zapros import (
    AsyncClient,
    RetryMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=RetryMiddleware(
        AsyncStdNetworkHandler(),
        max_attempts=5,
        backoff_factor=1.0,
        backoff_max=120.0,
        backoff_jitter=0.5,
    )
)
```

### Parameters

- `max_attempts` (default: `4`) - Maximum number of attempts (including the initial request)
- `backoff_factor` (default: `0.5`) - Base delay multiplier for exponential backoff
- `backoff_max` (default: `60.0`) - Maximum delay between retries in seconds
- `backoff_jitter` (default: `1.0`) - Jitter factor to randomize delays (0.0 to 1.0)

### Backoff calculation

Delay between retries follows exponential backoff:

```
delay = min(backoff_factor * (2 ** attempt), backoff_max)
```

With jitter applied to prevent thundering herd:

```
jitter_range = delay * backoff_jitter
delay = delay ± random(jitter_range)
```

## Custom retry policy

Implement your own retry logic using the `RetryPolicy` protocol:

```python
from zapros import (
    Request,
    Response,
    RetryMiddleware,
    AsyncStdNetworkHandler,
    AsyncClient,
)


class CustomRetryPolicy:
    def should_retry(
        self,
        *,
        request: Request,
        response: Response | None,
        error: Exception | None,
        attempt: int,
    ) -> bool:
        if error is not None:
            return True

        if response and response.status == 418:
            return True

        return False


client = AsyncClient(
    handler=RetryMiddleware(
        AsyncStdNetworkHandler(),
        policy=CustomRetryPolicy(),
        max_attempts=3,
    )
)
```

### Retry on specific errors

```python
from zapros import TimeoutError


class TimeoutRetryPolicy:
    def should_retry(
        self,
        *,
        request: Request,
        response: Response | None,
        error: Exception | None,
        attempt: int,
    ) -> bool:
        if error and isinstance(error, TimeoutError):
            return True
        return False
```

### Retry POST requests

```python
class AlwaysRetryPolicy:
    def should_retry(
        self,
        *,
        request: Request,
        response: Response | None,
        error: Exception | None,
        attempt: int,
    ) -> bool:
        if error:
            return True
        if response and response.status >= 500:
            return True
        return False


client = AsyncClient(
    handler=RetryMiddleware(
        AsyncStdNetworkHandler(),
        policy=AlwaysRetryPolicy(),
    )
)

async with client:
    response = await client.post(
        "https://api.example.com/create",
        json={"data": "value"},
    )
```

## Combining with other handlers

Chain `RetryMiddleware` with other handlers like cookies or auth:

```python
from zapros import (
    AsyncClient,
    RetryMiddleware,
    CookieMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=RetryMiddleware(
        CookieMiddleware(AsyncStdNetworkHandler()),
        max_attempts=3,
    )
)
```
