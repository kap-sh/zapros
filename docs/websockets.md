# WebSockets

Zapros ships with a WebSocket client built on top of [wsproto](https://python-hyper.org/projects/wsproto/), running on top of your Zapros `Client` / `AsyncClient`. The handshake goes through the client, so authentication, cookies, retries, and any custom handlers apply to WebSocket connections as well.

## Installation

WebSocket support requires the optional `wsproto` dependency:

```bash
pip install zapros[websocket]
```

If `wsproto` is not installed, calling `aconnect_ws` or `connect_ws` raises `RuntimeError`.

## Basic usage

Open a connection with `aconnect_ws` (async) or `connect_ws` (sync). Both are context managers that yield a WebSocket object and close the connection on exit.

::: code-group

```python [Async]
from zapros.websocket import (
    BinaryMessage,
    TextMessage,
    aconnect_ws,
)

async with aconnect_ws("wss://echo.example.com/ws") as ws:
    await ws.send(TextMessage(data="hello"))

    match await ws.recv():
        case TextMessage(data=text):
            print(f"text: {text}")
        case BinaryMessage(data=raw):
            print(f"binary: {len(raw)} bytes")
```

```python [Sync]
from zapros.websocket import (
    BinaryMessage,
    TextMessage,
    connect_ws,
)

with connect_ws("wss://echo.example.com/ws") as ws:
    ws.send(TextMessage(data="hello"))

    match ws.recv():
        case TextMessage(data=text):
            print(f"text: {text}")
        case BinaryMessage(data=raw):
            print(f"binary: {len(raw)} bytes")
```

:::

## Message types

All messages are tagged dataclasses. Use `match` or `isinstance` to discriminate:

| Type            | Payload  | Direction  |
| --------------- | -------- | ---------- |
| `TextMessage`   | `str`    | both       |
| `BinaryMessage` | `bytes`  | both       |
| `PingMessage`   | `bytes`  | both       |
| `PongMessage`   | `bytes`  | both       |
| `CloseMessage`  | code + reason | both  |

Pongs to incoming pings are sent automatically — you only need to handle `PingMessage` if you care about observing them.

## Iterating messages

WebSocket objects are iterable. Iteration yields application messages and stops cleanly when the peer sends a close frame.

::: code-group

```python [Async]
from zapros.websocket import (
    BinaryMessage,
    TextMessage,
    aconnect_ws,
)

async with aconnect_ws("wss://stream.example.com/ws") as ws:
    async for message in ws:
        match message:
            case TextMessage(data=text):
                print(text)
            case BinaryMessage(data=raw):
                print(len(raw))
```

```python [Sync]
from zapros.websocket import (
    BinaryMessage,
    TextMessage,
    connect_ws,
)

with connect_ws("wss://stream.example.com/ws") as ws:
    for message in ws:
        match message:
            case TextMessage(data=text):
                print(text)
            case BinaryMessage(data=raw):
                print(len(raw))
```

:::

## Sending binary data

Wrap `bytes` payloads in `BinaryMessage`:

```python
from zapros.websocket import BinaryMessage, aconnect_ws

async with aconnect_ws("wss://api.example.com/upload") as ws:
    await ws.send(BinaryMessage(data=b"\x00\x01\x02"))
```

## Subprotocols

Pass a list of preferred subprotocols. The server picks one and includes it in the handshake response:

```python
from zapros.websocket import aconnect_ws

async with aconnect_ws(
    "wss://api.example.com/ws",
    subprotocols=["graphql-ws", "json"],
) as ws:
    ...
```

## permessage-deflate

Enable the [permessage-deflate](https://datatracker.ietf.org/doc/html/rfc7692) extension by passing `permessage_deflate=True`, or pass a `PerMessageDeflateExtension` to customize the parameters:

```python
from zapros.websocket import (
    PerMessageDeflateExtension,
    aconnect_ws,
)

async with aconnect_ws(
    "wss://api.example.com/ws",
    permessage_deflate=PerMessageDeflateExtension(
        client_no_context_takeover=True,
        server_no_context_takeover=True,
        client_max_window_bits=12,
        server_max_window_bits=12,
    ),
) as ws:
    ...
```

## Reusing a client

Pass an existing `AsyncClient` / `Client` to share handlers, headers, cookies, and authentication with the rest of your code:

::: code-group

```python [Async]
from zapros import AsyncClient
from zapros.websocket import aconnect_ws

client = AsyncClient(
    headers={"Authorization": "Bearer token"},
)

async with aconnect_ws(
    "wss://api.example.com/ws",
    client=client,
) as ws:
    ...
```

```python [Sync]
from zapros import Client
from zapros.websocket import connect_ws

client = Client(
    headers={"Authorization": "Bearer token"},
)

with connect_ws(
    "wss://api.example.com/ws",
    client=client,
) as ws:
    ...
```

:::

The handshake is a normal `GET` request, so any handler middleware on the client (auth, cookies, custom headers) participates in it.

## Testing ASGI applications

Because the WebSocket handshake goes through the client's handler stack, an `AsyncClient` configured with [`AsgiHandler`](/asgi) lets you drive your ASGI app's WebSocket endpoints directly — no real network, no separate test server.

```python
from litestar import Litestar
from litestar.handlers import websocket_listener

from zapros import AsgiHandler, AsyncClient
from zapros.websocket import TextMessage, aconnect_ws


@websocket_listener("/echo")
async def echo(data: str) -> str:
    return data


app = Litestar(route_handlers=[echo])

async with AsyncClient(handler=AsgiHandler(app)) as client:
    async with aconnect_ws(
        "ws://testserver/echo",
        client=client,
    ) as ws:
        await ws.send(TextMessage(data="hello"))

        match await ws.recv():
            case TextMessage(data=text):
                assert text == "hello"
```

The same `aconnect_ws` API works against the in-process ASGI app exactly as it does against a real server, so test code and production code stay symmetric.

::: tip ASGI WebSocket framing
The ASGI WebSocket spec only carries text and binary payloads — there is no in-band representation of `Ping` / `Pong` frames. Sending `PingMessage` or `PongMessage` over an ASGI-backed connection is a silent no-op, so heartbeat code written against a real network connection still works under test.
:::

## Closing

Leaving the `with` / `async with` block closes the connection with code `1000` (normal closure). To send a specific close code or reason, call `close()` explicitly before exiting:

```python
from zapros.websocket import CloseCode, aconnect_ws

async with aconnect_ws("wss://api.example.com/ws") as ws:
    await ws.close(
        code=CloseCode.GOING_AWAY,
        reason="client shutting down",
    )
```

After the connection closes, `ws.close_code` and `ws.close_reason` expose the negotiated close code and reason.

## Error handling

Calling `send` or `recv` on a closed connection raises `ConnectionClosed`. The exception carries the close code and reason, so you can distinguish a clean close from an abnormal one:

```python
from zapros.websocket import (
    CloseCode,
    ConnectionClosed,
    TextMessage,
    aconnect_ws,
)

async with aconnect_ws("wss://api.example.com/ws") as ws:
    try:
        while True:
            await ws.send(TextMessage(data="ping"))
            await ws.recv()
    except ConnectionClosed as exc:
        if exc.code == CloseCode.NORMAL:
            print("server closed cleanly")
        else:
            print(f"closed with {exc.code}: {exc.reason}")
```

When iterating with `async for` / `for`, a peer-initiated close ends the loop without raising — the loop simply stops at the close frame.
