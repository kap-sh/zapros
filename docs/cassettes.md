---
title: HTTP Cassettes
description: Record and replay HTTP interactions for deterministic testing and offline development.
---

# HTTP Cassettes

Cassettes record HTTP request/response interactions to disk and replay them later without hitting the network.

## Quickstart

Record an interaction once, then replay it without network access:

::: code-group

```python [Async]
import asyncio
from zapros import (
    AsyncClient,
    AsyncStdNetworkHandler,
)
from zapros import CassetteMiddleware


async def main():
    handler = CassetteMiddleware(
        AsyncStdNetworkHandler(),
        cassette_name="github_api",
    )

    async with AsyncClient(handler=handler) as client:
         response = await client.get(
             "https://api.github.com/users/octocat",
         )
         print(response.json)


asyncio.run(main())
```

```python [Sync]
from zapros import (
    Client,
    StdNetworkHandler,
)
from zapros import CassetteMiddleware

handler = CassetteMiddleware(
    StdNetworkHandler(),
    cassette_name="github_api",
)

with Client(handler=handler) as client:
    response = client.get(
        "https://api.github.com/users/octocat",
    )
    print(response.json)
```

:::

The first run hits the network and writes `cassettes/github_api.json`. Subsequent runs replay from disk.

---

## Cassette Modes

The `mode` parameter controls recording behavior:

### `mode=CassetteMode.ONCE`

The default mode. Records only if the cassette file doesn't exist yet. Useful for initial recording:

```python
handler = CassetteMiddleware(
    network_handler,
    mode=CassetteMode.ONCE,
    cassette_name="api",
)
```

- First run: records to `cassettes/api.json`
- Later runs: replays from cassette, raises error for unmatched requests

### `mode=CassetteMode.NEW_EPISODES`

Replays existing interactions, records new ones:

```python
handler = CassetteMiddleware(
    network_handler,
    mode=CassetteMode.NEW_EPISODES,
    cassette_name="api",
)
```

- Matched requests: served from cassette
- Unmatched requests: hit network, get appended to cassette

### `mode=CassetteMode.ALL`

Always hits the network, always records (even duplicates):

```python
handler = CassetteMiddleware(
    network_handler,
    mode=CassetteMode.ALL,
    cassette_name="api",
)
```

Use for regenerating cassettes or debugging.

### `mode=CassetteMode.NONE`

Replay-only mode. Raises error if no match found:

```python
handler = CassetteMiddleware(
    None,  # no network handler needed
    mode=CassetteMode.NONE,
    cassette_name="api",
)
```

Use in CI to ensure tests never hit the network.

### Overriding the mode via environment

If `mode` is not passed to `CassetteMiddleware`, the default is read from the `ZAPROS_CASSETTE_MODE` environment variable. This lets the same code record or replay depending on how it's run:

```python
handler = CassetteMiddleware(
    network_handler,
    cassette_name="api",
)
```

```bash
# record new interactions on first run, replay after
ZAPROS_CASSETTE_MODE=once pytest

# always hit the network and regenerate cassettes
ZAPROS_CASSETTE_MODE=all pytest

# append new interactions to existing cassettes
ZAPROS_CASSETTE_MODE=new_episodes pytest

# replay-only; fail on any unmatched request
ZAPROS_CASSETTE_MODE=none pytest
```

Valid values match the `CassetteMode` names (case-insensitive): `all`, `new_episodes`, `once`, `none`. An invalid value raises `ValueError` at middleware init. If both `mode=` and the environment variable are set, the explicit `mode=` argument wins. If neither is set, the default is `once`.

---

## Playback Repeats

By default, each cassette interaction can be played back once. Requesting the same URL again raises an error:

```python
handler = CassetteMiddleware(
    None,
    mode=CassetteMode.NONE,
    cassette_dir=".",
    cassette_name="test",
)

async with AsyncClient(handler=handler) as client:
    await client.get(
        "https://api.example.com/data",
    )  # OK
    await client.get(
        "https://api.example.com/data",
    )  # UnhandledRequestError
```

To allow repeated playback:

```python
handler = CassetteMiddleware(
    None,
    mode=CassetteMode.NONE,
    cassette_dir=".",
    cassette_name="test",
    allow_playback_repeats=True,
)

async with AsyncClient(handler=handler) as client:
    await client.get(
        "https://api.example.com/data",
    )  # OK
    await client.get(
        "https://api.example.com/data",
    )  # OK
```

---

## Request Matching

Requests are matched by **method** and **normalized URL**. Query parameters are sorted before matching:

```python
# These match the same cassette entry:
await client.get(
    "https://api.example.com/search?a=1&b=2",
)
await client.get(
    "https://api.example.com/search?b=2&a=1",
)
```

Headers and request bodies are **not** part of the match key by default.

---

## Modifiers

Modifiers transform requests or responses before they're recorded. Useful for:

- Stripping authentication tokens from cassettes
- Normalizing dynamic URLs
- Redacting sensitive data

### Transform Request Keys

Map the request before it becomes a cassette key:

::: code-group

```python [Async]
import asyncio
from zapros import AsyncClient, Request
from zapros import (
    CassetteMiddleware,
    CassetteMode,
    ModifierRouter,
)
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path


async def main():
    router = MockRouter()
    Mock.given(path("/api")).respond(
        status=200, text="ok"
    ).mount(router)

    router = ModifierRouter()

    def strip_query(
        req: Request,
    ) -> Request:
        return Request(
            req.url.without_query(),
            req.method,
        )

    router.modifier(path("/api")).map_network_request(
        strip_query
    )

    handler = CassetteMiddleware(
        MockMiddleware(router),
        router=router,
        mode=CassetteMode.ALL,
        cassette_name="test",
    )

    async with AsyncClient(handler=handler) as client:
        await client.get(
            "https://api.example.com/api?token=secret123",
        )


asyncio.run(main())
```

```python [Sync]
from zapros import Client, Request
from zapros import (
    CassetteMiddleware,
    CassetteMode,
    ModifierRouter,
)
from zapros.mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros.matchers import path

router = MockRouter()
Mock.given(path("/api")).respond(
    status=200, text="ok"
).mount(router)

router = ModifierRouter()


def strip_query(
    req: Request,
) -> Request:
    return Request(
        req.url.without_query(),
        req.method,
    )


router.modifier(path("/api")).map_network_request(
    strip_query
)

handler = CassetteMiddleware(
    MockMiddleware(router),
    router=router,
    mode=CassetteMode.ALL,
    cassette_name="test",
)

with Client(handler=handler) as client:
    client.get(
        "https://api.example.com/api?token=secret123",
    )
```

:::

The cassette stores `https://api.example.com/api` without the query parameter.

### Transform Response Data

Map the response before it's saved to the cassette:

```python
from zapros import Response


def redact_headers(
    resp: Response,
) -> Response:
    headers = dict(resp.headers)
    headers.pop("set-cookie", None)
    return Response(
        status=resp.status,
        headers=headers,
        content=resp.read(),
    )


router.modifier(path("/login")).map_network_response(
    redact_headers
)
```

Recorded responses won't include `Set-Cookie` headers.

---

## Cassette File Format

Cassettes are stored as JSON:

```json
[
  {
    "request": {
      "method": "GET",
      "uri": "https://api.example.com/users"
    },
    "response": {
      "status": 200,
      "headers": {
        "content-type": "application/json"
      },
      "body": [
        { "id": 1, "name": "Alice" }
      ]
    }
  }
]
```

Bodies are stored based on the response `content-type`:

- `application/json` (or `*/*+json`): inlined as a JSON value (object, array, number, etc.) so diffs stay readable.
- `text/*`: inlined as a string, decoded with the charset from `content-type` (default `utf-8`).
- Anything else (binary): base64-encoded string.

---

