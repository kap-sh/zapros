from collections import deque
from contextlib import suppress
from typing import Optional

from typing_extensions import Self

from zapros._compat import AnyEvent, AnyLock
from zapros._handlers._asgi import AsgiWebSocketStream
from zapros.websocket._async import AsyncBaseWebSocket
from zapros.websocket._errors import ConnectionClosed

from ._types import (
    BinaryMessage,
    CloseCode,
    CloseMessage,
    Message,
    PingMessage,
    PongMessage,
    TextMessage,
)


class AsgiWebSocket(AsyncBaseWebSocket):
    """
    AsyncBaseWebSocket implementation backed by an in-process ASGI app.

    Unlike AsyncWebSocket, this does not run wsproto over a byte stream — it
    talks directly to AsgiWebSocketStream's queues, so the ASGI spec's framing
    is what we have to honor. The ASGI websocket spec only carries text/bytes
    payloads via websocket.send / websocket.receive: there is no in-band
    representation of Ping/Pong, so sending those message types is silently
    a no-op here.
    """

    def __init__(self, websocket_stream: AsgiWebSocketStream) -> None:
        self._asgi_websocket_stream = websocket_stream

        self._read_lock = AnyLock()
        self._write_lock = AnyLock()

        self._buffer: deque[Message] = deque()

        self.our_close: Optional[CloseMessage] = None
        self.we_sent_close = AnyEvent()

        self.their_close: Optional[CloseMessage] = None
        self.they_sent_close = AnyEvent()

    def _preferred_close(self) -> Optional[CloseMessage]:
        if self.their_close is not None:
            return self.their_close
        return self.our_close

    async def send(self, message: Message) -> None:
        async with self._write_lock:
            close = self._preferred_close()
            if close is not None:
                raise ConnectionClosed(code=close.code, reason=close.reason)

            match message:
                case TextMessage():
                    await self._asgi_websocket_stream.asend(text=message.data)

                case BinaryMessage():
                    await self._asgi_websocket_stream.asend(bytes=message.data)

                case CloseMessage():
                    self.our_close = message
                    self.we_sent_close.set()
                    with suppress(Exception):
                        await self._asgi_websocket_stream.aclose(
                            code=message.code,
                            reason=message.reason or "",
                        )

                case PingMessage() | PongMessage():
                    return

    async def recv(self) -> Message:
        async with self._read_lock:
            if self._buffer:
                return self._buffer.popleft()

            if self.their_close is not None:
                raise ConnectionClosed(
                    code=self.their_close.code,
                    reason=self.their_close.reason,
                )

            try:
                event = await self._asgi_websocket_stream.areceive()
            except ConnectionClosed as exc:
                close = CloseMessage(code=exc.code, reason=exc.reason)
                self.their_close = close
                self.they_sent_close.set()
                return close

            if "text" in event and event["text"] is not None:
                return TextMessage(data=event["text"])

            if "bytes" in event and event["bytes"] is not None:
                return BinaryMessage(data=bytes(event["bytes"]))

            raise RuntimeError(f"unexpected ASGI websocket event: {event!r}")

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Message:
        message = await self.recv()

        match message:
            case CloseMessage():
                raise StopAsyncIteration()
            case _:
                return message

    @property
    def close_code(self) -> int | None:
        close = self._preferred_close()
        return None if close is None else close.code

    @property
    def close_reason(self) -> str | None:
        close = self._preferred_close()
        return None if close is None else close.reason

    async def close(self, code: int = CloseCode.NORMAL, reason: str = "") -> None:
        async with self._write_lock:
            if self.our_close is None:
                self.our_close = CloseMessage(code=code, reason=reason)
                self.we_sent_close.set()

        with suppress(Exception):
            await self._asgi_websocket_stream.aclose(code=code, reason=reason)
