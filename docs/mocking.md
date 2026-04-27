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

Mock.given(path("/api")).respond(
    Response(status=200)
).mount(router)


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

Mock.given(path("/api")).respond(
    Response(status=200)
).mount(router)

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
            Mock.given(path("/api")).respond(
                Response(status=200)
            ).mount(router)
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
        Mock.given(path("/api")).respond(
            Response(status=200)
        ).mount(router)
        response = client.get(
            "https://api.example.com/api",
        )
        assert response.status == 200
```

:::

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

Mock.given(path("/data")).respond(
    Response(status=200, json={"key": "value"})
).mount(router)


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

Mock.given(path("/data")).respond(
    Response(status=200, json={"key": "value"})
).mount(router)

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

Mock.given(path("/hello")).respond(
    Response(status=200, text="Hello World")
).mount(router)


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

Mock.given(path("/hello")).respond(
    Response(status=200, text="Hello World")
).mount(router)

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

Mock.given(path("/custom")).respond(
    Response(
        status=201,
        text="Created",
        headers={"x-custom": "header"},
    )
).mount(router)


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

Mock.given(path("/custom")).respond(
    Response(
        status=201,
        text="Created",
        headers={"x-custom": "header"},
    )
).mount(router)

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


Mock.given(method("GET")).callback(handler).mount(router)


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


Mock.given(method("GET")).callback(handler).mount(router)

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

Mock.given(path("/api")).respond(
    Response(status=200)
).expect(2).mount(router)


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

    router.verify()


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

Mock.given(path("/api")).respond(
    Response(status=200)
).expect(2).mount(router)

with Client(handler=MockMiddleware(router)) as client:
    client.get(
        "https://api.example.com/api",
    )
    client.get(
        "https://api.example.com/api",
    )

router.verify()
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

Mock.given(path("/api")).respond(
    Response(status=200)
).once().mount(router)


async def main():
    async with AsyncClient(
        handler=MockMiddleware(router)
    ) as client:
        await client.get(
            "https://api.example.com/api",
        )

    router.verify()


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

Mock.given(path("/api")).respond(
    Response(status=200)
).once().mount(router)

with Client(handler=MockMiddleware(router)) as client:
    client.get(
        "https://api.example.com/api",
    )

router.verify()
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

Mock.given(path("/api")).respond(
    Response(status=200)
).never().mount(router)

# No requests made

router.verify()
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

Mock.given(path("/api")).respond(
    Response(status=200)
).never().mount(router)

router.verify()
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

Mock.given(path("/api")).respond(
    Response(status=200)
).once().mount(router)
Mock.given(path("/api")).respond(
    Response(status=500)
).once().mount(router)


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

Mock.given(path("/api")).respond(
    Response(status=200)
).once().mount(router)
Mock.given(path("/api")).respond(
    Response(status=500)
).once().mount(router)

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

Mock.given(path("/health")).respond(
    Response(status=200)
).mount(router)
Mock.given(path("/status")).respond(
    Response(status=204)
).mount(router)


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

Mock.given(path("/health")).respond(
    Response(status=200)
).mount(router)
Mock.given(path("/status")).respond(
    Response(status=204)
).mount(router)

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

`.mount(router)` is the preferred way to register a mock. If you need to add a pre-built `Mock` object directly, `router.add(mock)` is also available.

Dispatching happens automatically when used with `MockMiddleware`.

## Verifying Mocks

At the end of a test you can verify all expectations:

```python
router.verify()
```

If expectations are not met, an `AssertionError` is raised.

## Resetting Mocks

Reset call counts between tests:

```python
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

    Mock.given(path("/users").method("GET")).respond(
        Response(status=200, json=[])
    ).once().mount(router)

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

    Mock.given(path("/users").method("GET")).respond(
        Response(status=200, json=[])
    ).once().mount(router)

    with Client(handler=MockMiddleware(router)) as client:
        response = client.get(
            "https://example.com/users",
        )
        assert response.status == 200
```

:::

This approach lets you build deterministic HTTP tests without network access.
