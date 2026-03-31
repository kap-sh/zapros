# Cookies

Cookies in Zapros are implemented as a [handler](/handlers) — wrapping another handler to automatically store and send cookies.

## Setup

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CookieMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CookieMiddleware(AsyncStdNetworkHandler())
)
```

```python [Sync]
from zapros import (
    Client,
    CookieMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CookieMiddleware(StdNetworkHandler()))
```

:::

## Basic usage

Cookies from `Set-Cookie` headers are automatically stored and sent with subsequent requests:

::: code-group

```python [Async]
from zapros import (
    AsyncClient,
    CookieMiddleware,
    AsyncStdNetworkHandler,
)

client = AsyncClient(
    handler=CookieMiddleware(AsyncStdNetworkHandler())
)

async with client:
    await client.get(
        "https://api.example.com/login",
    )
    # session cookie stored

    response = await client.get(
        "https://api.example.com/profile",
    )
    # session cookie sent automatically
```

```python [Sync]
from zapros import (
    Client,
    CookieMiddleware,
    StdNetworkHandler,
)

client = Client(handler=CookieMiddleware(StdNetworkHandler()))

with client:
    client.get(
        "https://api.example.com/login",
    )
    # session cookie stored

    response = client.get(
        "https://api.example.com/profile",
    )
    # session cookie sent automatically
```

:::

## Custom CookieJar

Share cookies across clients:

```python
from http.cookiejar import CookieJar
from zapros import (
    AsyncClient,
    CookieMiddleware,
    AsyncStdNetworkHandler,
)

shared_jar = CookieJar()

client1 = AsyncClient(
    handler=CookieMiddleware(
        AsyncStdNetworkHandler(),
        jar=shared_jar,
    )
)
client2 = AsyncClient(
    handler=CookieMiddleware(
        AsyncStdNetworkHandler(),
        jar=shared_jar,
    )
)
```

## Custom cookie handling

If you need custom cookie logic (e.g., encrypted cookies, JWT in cookies, cookie signing), write your own handler:

```python
from zapros import (
    AsyncBaseHandler,
    BaseHandler,
    Request,
    Response,
)


class MyCookieMiddleware(AsyncBaseHandler, BaseHandler):
    def __init__(self, handler):
        self._handler = handler

    async def ahandle(self, request: Request) -> Response:
        request.headers.add(
            "Cookie",
            "mycookie=signedvalue",
        )
        return await self._handler.ahandle(request)

    def handle(self, request: Request) -> Response:
        request.headers.add(
            "Cookie",
            "mycookie=signedvalue",
        )
        return self._handler.handle(request)
```

See [Handlers](/handlers) for the full protocol.
