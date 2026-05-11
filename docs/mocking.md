---
title: Mocking HTTP Requests
description: Use Zapros's mock router + mock handler to test code without hitting the network.
---

# Mocking HTTP Requests

Zapros includes a small, *[WireMock-style](https://docs.rs/wiremock/latest/wiremock/)* mocking layer you can use in tests to match outgoing requests and return deterministic responses—no real network calls required.

## Quickstart

Mocking is implemented with [handlers](/handlers) and ensures that all outgoing requests are intercepted and matched against the mock router. It blocks I/O for unmatched requests by default, but you can also configure it to allow unmatched requests to pass through to the network.

Here is a simple example of how you can mock a request with the `MockMiddleware`:

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/api")).respond(Response(status=200))
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        response = await client.get(
            "https://api.example.com/api",
        )
        print(response.status)  # 200


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/api")).respond(Response(status=200))
)

with Client(handler=MockMiddleware(router)) as client:
    response = client.get(
        "https://api.example.com/api",
    )
    print(response.status)  # 200
```

:::

or, if you don't have access to the `Client` and can't easily inject a handler, you can use the `mock_http` context manager to patch `zapros`'s default HTTP handling:

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockRouter,
    mock_http,
)
from zapros.matchers import path


async def main():
    async with AsyncClient() as client:
        with mock_http() as router:
            router.add(
                Mock.given(path("/api")).respond(
                    Response(status=200)
                )
            )
            response = await client.get(
                "https://api.example.com/api",
            )
            assert response.status == 200


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockRouter,
    mock_http,
)
from zapros.matchers import path

with Client() as client:
    with mock_http() as router:
        router.add(
            Mock.given(path("/api")).respond(
                Response(status=200)
            )
        )
        response = client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200
```

:::

## Avoid `mock_http`

Whenever you can pass a handler into your `Client`, prefer `MockMiddleware` over `mock_http`. Injecting a middleware is far more reliable than globally patching `zapros`'s default network handlers, and it composes naturally with the way you already wire up clients in tests.

For example, in `pytest` you typically have a fixture that builds the `Client` your code under test uses. You can write a small fixture that wires `MockMiddleware` into that same `Client` and yields the router, so each test only has to register the mocks it cares about:

```python
from typing import Iterator

import pytest

import zapros
from zapros.mock import Mock, MockMiddleware, MockRouter


@pytest.fixture
def mock_client() -> Iterator[
    tuple[zapros.Client, MockRouter]
]:
    mock_middleware = MockMiddleware()
    with zapros.Client(mock_middleware) as client:
        yield client, mock_middleware.router


def test_client(
    mock_client: tuple[zapros.Client, MockRouter],
) -> None:
    client, router = mock_client

    router.add(Mock().respond(zapros.Response(200)))

    response = client.get("https://example.com")
    assert response.status == 200
```

Reach for `mock_http` only when you genuinely can't reach the `Client` to pass a handler in (for example, when testing third-party code that constructs its own client internally).

## Matching Requests

Mocks match requests using **[matchers](/matchers)**. A matcher inspects some part of the request (method, path, headers, etc.) and returns `True` if it matches.

Available matchers include `path`, `method`, `host`, `header`, `query`, and `json`. They can be combined with `and_`, `or_`, and `not_`, or chained fluently. See the [Matchers documentation](/matchers) for full details and examples.

## Returning Responses

## JSON Response

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/data")).respond(
        Response(status=200, json={"key": "value"})
    )
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        response = await client.get(
            "https://api.example.com/data",
        )
         assert response.json == {"key": "value"}


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/data")).respond(
        Response(status=200, json={"key": "value"})
    )
)

with Client(handler=MockMiddleware(router)) as client:
    response = client.get(
        "https://api.example.com/data",
    )
    assert response.json == {"key": "value"}
```

:::

## Text Response

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/hello")).respond(
        Response(status=200, text="Hello World")
    )
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        response = await client.get(
            "https://api.example.com/hello",
        )
         assert response.text == "Hello World"


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/hello")).respond(
        Response(status=200, text="Hello World")
    )
)

with Client(handler=MockMiddleware(router)) as client:
    response = client.get(
        "https://api.example.com/hello",
    )
    assert response.text == "Hello World"
```

:::

## Custom Headers

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/custom")).respond(
        Response(
            status=201,
            text="Created",
            headers={"x-custom": "header"},
        )
    )
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        response = await client.get(
            "https://api.example.com/custom",
        )
        assert response.status == 201
        assert response.headers["x-custom"] == "header"


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/custom")).respond(
        Response(
            status=201,
            text="Created",
            headers={"x-custom": "header"},
        )
    )
)

with Client(handler=MockMiddleware(router)) as client:
    response = client.get(
        "https://api.example.com/custom",
    )
    assert response.status == 201
    assert response.headers["x-custom"] == "header"
```

:::

## Dynamic Responses

You can generate responses dynamically using a callback:

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import method

router = MockRouter()


def handler(req):
    if req.url.pathname == "/notfound":
        return Response(status=404)
    return Response(status=200)


router.add(Mock.given(method("GET")).callback(handler))


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        assert (
            await client.get(
                "https://api.example.com/notfound",
            )
        ).status == 404
        assert (
            await client.get(
                "https://api.example.com/anything",
            )
        ).status == 200


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import method

router = MockRouter()


def handler(req):
    if req.url.pathname == "/notfound":
        return Response(status=404)
    return Response(status=200)


router.add(Mock.given(method("GET")).callback(handler))

with Client(handler=MockMiddleware(router)) as client:
    assert (
        client.get(
            "https://api.example.com/notfound",
        ).status
        == 404
    )
    assert (
        client.get(
            "https://api.example.com/anything",
        ).status
        == 200
    )
```

:::

## Expectations

Mocks can verify how many times they were called.

## Exact Count

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .expect(2)
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        await client.get(
            "https://api.example.com/api",
        )
        await client.get(
            "https://api.example.com/api",
        )


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .expect(2)
)

with Client(handler=MockMiddleware(router)) as client:
    client.get(
        "https://api.example.com/api",
    )
    client.get(
        "https://api.example.com/api",
    )
```

:::

You can also make post-hoc assertions on a mock after the code under test runs. These assertions inspect recorded calls and do not change matching or exhaustion behavior.

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

mock = Mock.given(path("/api")).respond(
    Response(status=200)
)
router.add(mock)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        await client.get(
            "https://api.example.com/api",
        )

    mock.assert_called_once()
    assert mock.called
    assert mock.call_count == 1
    assert mock.calls[0].method == "GET"


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

mock = Mock.given(path("/api")).respond(
    Response(status=200)
)
router.add(mock)

with Client(handler=MockMiddleware(router)) as client:
    client.get(
        "https://api.example.com/api",
    )

mock.assert_called_once()
assert mock.called
assert mock.call_count == 1
assert mock.calls[0].method == "GET"
```

:::

## Once

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .once()
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        await client.get(
            "https://api.example.com/api",
        )


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .once()
)

with Client(handler=MockMiddleware(router)) as client:
    client.get(
        "https://api.example.com/api",
    )
```

:::

## Never

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .never()
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        pass  # no requests made


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .never()
)

with Client(handler=MockMiddleware(router)) as client:
    pass  # no requests made
```

:::

## Sequences

When a mock has an expected call count set via `expect(n)`, `once()`, or `never()`, it stops matching once that count is reached. This lets you register multiple mocks for the same path that fire in order.

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .once()
)
router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=500))
    .once()
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        assert (
            await client.get(
                "https://api.example.com/api",
            )
        ).status == 200
        assert (
            await client.get(
                "https://api.example.com/api",
            )
        ).status == 500


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=200))
    .once()
)
router.add(
    Mock
    .given(path("/api"))
    .respond(Response(status=500))
    .once()
)

with Client(handler=MockMiddleware(router)) as client:
    assert (
        client.get(
            "https://api.example.com/api",
        ).status
        == 200
    )
    assert (
        client.get(
            "https://api.example.com/api",
        ).status
        == 500
    )
```

:::

Mocks are matched in registration order. Once a mock is exhausted it is skipped, so the next registered mock with matching matchers takes over.

## MockRouter

The `MockRouter` stores mocks and dispatches requests to the first matching mock.

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/health")).respond(
        Response(status=200)
    )
)
router.add(
    Mock.given(path("/status")).respond(
        Response(status=204)
    )
)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        assert (
            await client.get(
                "https://api.example.com/health",
            )
        ).status == 200
        assert (
            await client.get(
                "https://api.example.com/status",
            )
        ).status == 204


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()

router.add(
    Mock.given(path("/health")).respond(
        Response(status=200)
    )
)
router.add(
    Mock.given(path("/status")).respond(
        Response(status=204)
    )
)

with Client(handler=MockMiddleware(router)) as client:
    assert (
        client.get(
            "https://api.example.com/health",
        ).status
        == 200
    )
    assert (
        client.get(
            "https://api.example.com/status",
        ).status
        == 204
    )
```

:::

`router.add(mock)` registers a `Mock` with the router.

Dispatching happens automatically when used with `MockMiddleware`.

## Verifying and Resetting Mocks

Most of the time you don't need to call `router.verify()` or `router.reset()` yourself — closing the `MockMiddleware` does both for you. When you use `MockMiddleware` inside a `Client` (or `AsyncClient`) context manager, the client closes the middleware on exit, which calls `router.verify()` followed by `router.reset()`. If any expectation is unmet, `verify()` raises `AssertionError` from the `__exit__`.

If you build the `MockMiddleware` without a surrounding `with` block, you can run them manually:

```python
router.verify()
router.reset()
```

## Async Support

`MockMiddleware` also works with async handlers.

```python
handler = MockMiddleware(router)

response = await handler.ahandle(request)
```

If no mock matches and no fallback handler is configured, a `ValueError` is raised.

You can optionally provide a fallback handler:

```python
handler = MockMiddleware(router, fallback=my_handler)
```

## Example Test

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path


async def test_api():
    router = MockRouter()

    router.add(
        Mock
        .given(path("/users").method("GET"))
        .respond(Response(status=200, json=[]))
        .once()
    )

    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        response = await client.get(
            "https://example.com/users",
        )
        assert response.status == 200


asyncio.run(test_api())
```

```python [Sync]
from zapros import Client, Response
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path


def test_api():
    router = MockRouter()

    router.add(
        Mock
        .given(path("/users").method("GET"))
        .respond(Response(status=200, json=[]))
        .once()
    )

    with Client(handler=MockMiddleware(router)) as client:
        response = client.get(
            "https://example.com/users",
        )
        assert response.status == 200
```

:::

This approach lets you build deterministic HTTP tests without network access.
