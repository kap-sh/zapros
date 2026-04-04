# Rust

Zapros can use **Rust's reqwest** library as the underlying HTTP transport layer through [pyreqwest](https://github.com/MarkusSintonen/pyreqwest), a Python binding that exposes Rust's high-performance HTTP client to Python.

This provides access to reqwest's battle-tested implementation, including connection pooling, TLS, HTTP/2 support, and efficient async I/O powered by Tokio.

::: info Python Version Requirement
The Rust runtime is only supported on **Python 3.11 and above**.
:::

## Installation

Install zapros with pyreqwest feature:

```bash
pip install zapros[pyreqwest]
```

## Usage

Use `AsyncPyreqwestHandler` or `PyreqwestHandler` with Zapros to leverage Rust's reqwest via Python:

::: code-group

```python [Async]
from pyreqwest.client import ClientBuilder
from zapros import AsyncClient, AsyncPyreqwestHandler

async with AsyncClient(handler=AsyncPyreqwestHandler()) as client:
    response = await client.get("https://api.example.com/users")
    print(response.status)
    print(response.text)
```

```python [Sync]
from pyreqwest.client import SyncClientBuilder
from zapros import Client, PyreqwestHandler

with Client(handler=PyreqwestHandler()) as client:
    response = client.get("https://api.example.com/users")
    print(response.status)
    print(response.text)
```

:::

## Configuring reqwest

You can configure the underlying reqwest client using pyreqwest's builder pattern:

::: code-group

```python [Async]
from datetime import timedelta

from pyreqwest.client import ClientBuilder
from zapros import AsyncClient, AsyncPyreqwestHandler

rust_handler = AsyncPyreqwestHandler(
    client=ClientBuilder()
        .pool_max_idle_per_host(10)
        .timeout(timedelta(seconds=30))
        .user_agent("MyApp/1.0")
)

async with AsyncClient(handler=rust_handler) as client:
    response = await client.get("https://api.example.com/data")
```

```python [Sync]
from datetime import timedelta

from pyreqwest.client import SyncClientBuilder
from zapros import Client, PyreqwestHandler

rust_handler = PyreqwestHandler(
    client=SyncClientBuilder()
        .pool_max_idle_per_host(10)
        .timeout(timedelta(seconds=30))
        .user_agent("MyApp/1.0")
)

with Client(handler=rust_handler) as client:
    response = client.get("https://api.example.com/data")
```

:::

## Learn More

- [pyreqwest on GitHub](https://github.com/MarkusSintonen/pyreqwest)
- [Rust reqwest documentation](https://docs.rs/reqwest/)
