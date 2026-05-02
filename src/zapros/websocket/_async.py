from abc import ABC, abstractmethod
from collections import deque
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from typing_extensions import Self

from zapros._compat import AnyEvent
from zapros._constants import DEFAULT_READ_SIZE
from zapros.websocket._errors import ConnectionClosed

if TYPE_CHECKING:
    from wsproto import WSConnection
    from wsproto.connection import ConnectionType
    from wsproto.events import (
        AcceptConnection,
        BytesMessage as WSBytesMessage,
        CloseConnection,
        Ping,
        Pong,
        Request,
        TextMessage as WSTextMessage,
    )
    from wsproto.extensions import PerMessageDeflate
else:
    try:
        from wsproto import WSConnection
        from wsproto.connection import ConnectionType
        from wsproto.events import (
            AcceptConnection,
            BytesMessage as WSBytesMessage,
            CloseConnection,
            Ping,
            Pong,
            Request,
            TextMessage as WSTextMessage,
        )
        from wsproto.extensions import PerMessageDeflate
    except ImportError:
        WSConnection = None
        ConnectionType = None
        AcceptConnection = None
        WSBytesMessage = None
        CloseConnection = None
        Ping = None
        Pong = None
        Request = None
        WSTextMessage = None
        PerMessageDeflate = None

from zapros import URL, AsyncBaseNetworkStream, AsyncClient, Headers
from zapros._compat import AnyLock

from ._types import (
    BinaryMessage,
    CloseCode,
    CloseMessage,
    Message,
    PerMessageDeflateExtension,
    PingMessage,
    PongMessage,
    TextMessage,
)


def extract_message_headers(message: bytes) -> Headers:
    """Extract headers from a wsproto handshake message."""
    headers = message.split(b"\r\n")[1:]
    parsed_headers = Headers()

    for header in headers:
        if not header:
            break
        key, value = header.split(b":", 1)
        parsed_headers[key.strip().decode()] = value.strip().decode()

    return parsed_headers


class AsyncBaseWebSocket(ABC):
    """
    Base class for WebSocket connections.
    """

    @abstractmethod
    async def send(
        self,
        message: Message,
    ) -> None:
        """
        Send a message over the WebSocket connection.

        Args:
            message: The message to send, which can be a TextMessage,
            BinaryMessage, PingMessage, PongMessage, or CloseMessage.
        """

    @abstractmethod
    async def recv(self) -> Message:
        """
        Receive a message from the WebSocket connection.

        When called on an open connection, this method will block until a message is received.
        If the connection is closed, it will raise a `ConnectionClosed` exception.
        """

    @abstractmethod
    async def close(self, code: int = CloseCode.NORMAL, reason: str = "") -> None:
        """
        Close the WebSocket connection.

        Args:
            code: The close code to send to the peer. Defaults to 1000 (normal closure).
            reason: An optional reason for closing the connection.
        """

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[Message]:
        """Return an asynchronous iterator over incoming messages."""

    @property
    @abstractmethod
    def close_code(self) -> int | None:
        """The close code if the connection has been closed, or None if still open."""

    @property
    @abstractmethod
    def close_reason(self) -> str | None:
        """The close reason if the connection has been closed, or None if still open."""


class AsyncWebSocket(AsyncBaseWebSocket):
    def __init__(self, stream: AsyncBaseNetworkStream, *, wsproto_connection: WSConnection) -> None:
        self._stream = stream
        self._conn = wsproto_connection
        self._buffer: deque[Message] = deque()

        # Fragment accumulators.
        self._text_parts: list[str] = []
        self._bytes_parts: list[bytes] = []

        # Locking rules:
        #
        #   _read_lock:
        #       Protects recv-side user buffers and fragment accumulators.
        #
        #   _conn_lock:
        #       Protects wsproto's mutable state machine and close-state fields.
        #       Never hold this while doing stream I/O.
        #
        #   _wire_lock:
        #       Serializes bytes written to the underlying stream.
        #       This may be held during blocking write_all(), but while it is
        #       held, neither _read_lock nor _conn_lock is held.
        #
        # If _wire_lock and _conn_lock are both needed, acquire:
        #
        #       _wire_lock -> _conn_lock
        #
        # The read path never acquires _wire_lock while holding _conn_lock.
        self._read_lock = AnyLock()
        self._conn_lock = AnyLock()
        self._wire_lock = AnyLock()

        self.we_sent_close = AnyEvent()
        self.our_close: Optional[CloseMessage] = None

        self.they_sent_close = AnyEvent()
        self.their_close: Optional[CloseMessage] = None

        # Control frames generated by the read path.
        #
        # The read path may need to generate Pong frames and Close responses,
        # but it must not write them while holding _read_lock or _conn_lock.
        # So it appends the already-serialized bytes here. Later, recv(),
        # send(), or close() flushes them outside those locks.
        self._pending_control_frames: deque[bytes] = deque()

        # Set when the stream should be closed after all pending control frames
        # have been flushed. This is used after receiving the peer's close.
        self._close_after_pending_control = False

    def _preferred_close_locked(self) -> Optional[CloseMessage]:
        """
        Caller must hold _conn_lock.
        """
        if self.their_close is not None:
            return self.their_close
        return self.our_close

    def _mark_their_close_locked(self, code: int, reason: str | None) -> CloseMessage:
        """
        Caller must hold _conn_lock.
        """
        if self.their_close is None:
            self.their_close = CloseMessage(code=code, reason=reason)
            self.they_sent_close.set()

        return self.their_close

    async def _mark_abnormal_close(self, reason: str) -> CloseMessage:
        async with self._conn_lock:
            return self._mark_their_close_locked(
                code=CloseCode.ABNORMAL,
                reason=reason,
            )

    async def _mark_write_failed(self) -> None:
        await self._mark_abnormal_close("websocket write failed")

        with suppress(Exception):
            await self._stream.close()

    async def _write_frame_to_stream(self, frame: bytes, *, raise_errors: bool) -> bool:
        """
        Write one already-serialized frame.

        Caller must hold _wire_lock.

        Caller must not hold _read_lock or _conn_lock.
        """
        try:
            await self._stream.write_all(frame)
            return True
        except Exception:
            await self._mark_write_failed()
            if raise_errors:
                raise
            return False

    async def _flush_pending_control_frames_already_have_wire_lock(
        self,
        *,
        raise_errors: bool,
    ) -> None:
        """
        Flush pending Pong / Close-response frames.

        Caller must hold _wire_lock.

        Caller must not hold _read_lock or _conn_lock.
        """
        while True:
            async with self._conn_lock:
                if self._pending_control_frames:
                    frames = list(self._pending_control_frames)
                    self._pending_control_frames.clear()
                    close_after = False
                else:
                    frames = []
                    close_after = self._close_after_pending_control
                    self._close_after_pending_control = False

            for frame in frames:
                if not await self._write_frame_to_stream(frame, raise_errors=raise_errors):
                    return

            if close_after:
                with suppress(Exception):
                    await self._stream.close()
                return

            if not frames:
                return

    async def _flush_pending_control_frames(self, *, raise_errors: bool) -> None:
        """
        Flush pending control frames without holding recv or wsproto locks.

        This can still block on write_all(), because this is the no-writer-task
        version. The important part is that it does not block while holding
        _read_lock or _conn_lock.
        """
        async with self._wire_lock:
            await self._flush_pending_control_frames_already_have_wire_lock(
                raise_errors=raise_errors,
            )

    async def send(self, message: Message) -> None:
        sent_close = False

        # Reserve the wire first. This preserves byte ordering among public
        # sends and pending automatic control frames.
        async with self._wire_lock:
            # Drain any control frames whose wsproto send() calls happened
            # before this application send.
            #
            # The loop closes the small gap between "pending queue is empty"
            # and "generate this application frame". We only generate the app
            # frame while holding _conn_lock and after seeing that no older
            # pending control frame exists.
            while True:
                async with self._conn_lock:
                    if self._pending_control_frames:
                        frames = list(self._pending_control_frames)
                        self._pending_control_frames.clear()
                        close_after = False
                        frame = None
                    elif self._close_after_pending_control:
                        frames = []
                        close_after = True
                        self._close_after_pending_control = False
                        frame = None
                    else:
                        close = self._preferred_close_locked()
                        if close is not None:
                            raise ConnectionClosed(
                                code=close.code,
                                reason=close.reason,
                            )

                        match message:
                            case TextMessage():
                                frame = self._conn.send(WSTextMessage(data=message.data))

                            case BinaryMessage():
                                frame = self._conn.send(WSBytesMessage(data=message.data))

                            case PingMessage():
                                frame = self._conn.send(Ping(payload=message.data))

                            case PongMessage():
                                frame = self._conn.send(Pong(payload=message.data))

                            case CloseMessage():
                                frame = self._conn.send(
                                    CloseConnection(
                                        code=message.code,
                                        reason=message.reason,
                                    )
                                )

                                # Prevent later application sends as soon as
                                # the close has been generated in wsproto.
                                self.our_close = message
                                sent_close = True

                            case _:
                                raise TypeError(f"unsupported websocket message type: {type(message)!r}")

                        frames = []
                        close_after = False

                for pending_frame in frames:
                    await self._write_frame_to_stream(
                        pending_frame,
                        raise_errors=True,
                    )

                if close_after:
                    with suppress(Exception):
                        await self._stream.close()
                    continue

                if frame is not None:
                    break

            await self._write_frame_to_stream(frame, raise_errors=True)

            if sent_close:
                self.we_sent_close.set()

    async def recv(self) -> Message:
        while True:
            async with self._read_lock:
                while not self._buffer:
                    async with self._conn_lock:
                        close = self.their_close

                    if close is not None:
                        raise ConnectionClosed(
                            code=close.code,
                            reason=close.reason,
                        )

                    await self._fill_buffer_locked()

                message = self._buffer.popleft()

            # Flush any automatic Pong / Close-response frames generated while
            # reading, but do it after releasing both _read_lock and _conn_lock.
            #
            # This may still block this recv() call on write_all(), but it no
            # longer wedges the websocket state machine or prevents another
            # task from observing close/read state.
            await self._flush_pending_control_frames(raise_errors=False)

            return message

    async def _fill_buffer_locked(self) -> None:
        """
        Fill _buffer with at least one message, or observe connection close.

        Caller must hold _read_lock.

        This method may block in stream.read(), but it never writes to the
        stream and never waits on _wire_lock.
        """
        async with self._conn_lock:
            self._process_events_locked()
            close = self.their_close

        if self._buffer or close is not None:
            if close is not None and not self._buffer:
                self._buffer.append(close)
            return

        try:
            chunk = await self._stream.read(DEFAULT_READ_SIZE)
        except Exception:
            close = await self._mark_abnormal_close("websocket read failed")
            if not self._buffer:
                self._buffer.append(close)
            return

        if not chunk:
            close = await self._mark_abnormal_close("peer closed connection without sending close frame")
            if not self._buffer:
                self._buffer.append(close)
            return

        async with self._conn_lock:
            self._conn.receive_data(chunk)
            self._process_events_locked()
            close = self.their_close

        if close is not None and not self._buffer:
            self._buffer.append(close)

    def _process_events_locked(self) -> None:
        """
        Drain pending wsproto events.

        Caller must hold:
            _read_lock
            _conn_lock

        This method may call _conn.send(), because that only mutates wsproto
        and returns bytes. It must not call stream.write_all().
        """
        for event in self._conn.events():
            match event:
                case WSTextMessage(data=data, message_finished=finished):
                    self._text_parts.append(data)

                    if finished:
                        self._buffer.append(TextMessage(data="".join(self._text_parts)))
                        self._text_parts.clear()

                case WSBytesMessage(data=data, message_finished=finished):
                    self._bytes_parts.append(bytes(data))

                    if finished:
                        self._buffer.append(BinaryMessage(data=b"".join(self._bytes_parts)))
                        self._bytes_parts.clear()

                case Ping(payload=payload):
                    payload = bytes(payload)
                    self._buffer.append(PingMessage(data=payload))

                    # Generate the Pong now while holding _conn_lock, but only
                    # queue the bytes. The actual write happens later outside
                    # _read_lock and _conn_lock.
                    if self.our_close is None and self.their_close is None:
                        with suppress(Exception):
                            frame = self._conn.send(Pong(payload=payload))
                            self._pending_control_frames.append(bytes(frame))

                case Pong(payload=payload):
                    self._buffer.append(PongMessage(data=bytes(payload)))

                case CloseConnection(code=code, reason=reason):
                    was_new_close = self.their_close is None

                    close = self._mark_their_close_locked(
                        code=code,
                        reason=reason,
                    )

                    if was_new_close:
                        self._buffer.append(close)

                    if self.our_close is None:
                        # Generate the close response under _conn_lock, but do
                        # not write it here.
                        with suppress(Exception):
                            response_frame = self._conn.send(event.response())
                            self._pending_control_frames.append(bytes(response_frame))

                            self.our_close = CloseMessage(
                                code=code,
                                reason=reason,
                            )
                            self.we_sent_close.set()

                    # After receiving their close, the transport should be
                    # closed once our pending close response, if any, is flushed.
                    self._close_after_pending_control = True

                case _:
                    pass

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
        close = self._preferred_close_locked()
        return None if close is None else close.code

    @property
    def close_reason(self) -> str | None:
        close = self._preferred_close_locked()
        return None if close is None else close.reason

    async def close(self, code: int = CloseCode.NORMAL, reason: str = "") -> None:
        # Initiate close if we have not already done so.
        #
        # This can still block in write_all(), because this is the no-writer-
        # task version. But send() will not hold _conn_lock or _read_lock
        # while blocked.
        async with self._conn_lock:
            already_sent_close = self.our_close is not None

        if not already_sent_close:
            try:
                await self.send(CloseMessage(code=code, reason=reason))
            except ConnectionClosed:
                # Already closed by either side.
                pass

        # Drain until we observe the peer's close. Preserve any normal messages
        # that arrived before the close frame.
        if not self.they_sent_close.is_set():
            saved_messages: deque[Message] = deque()

            async with self._read_lock:
                try:
                    while not self.they_sent_close.is_set():
                        if self._buffer:
                            saved_messages.append(self._buffer.popleft())
                            continue

                        await self._fill_buffer_locked()

                finally:
                    while saved_messages:
                        self._buffer.appendleft(saved_messages.pop())

        # If reading the peer's close generated a close response, flush it now,
        # outside _read_lock and _conn_lock.
        await self._flush_pending_control_frames(raise_errors=False)

        with suppress(Exception):
            await self._stream.close()


class aconnect_ws:
    """Connect to a WebSocket server.

    Usage::

        async with aconnect_ws("wss://example.com/ws") as ws:
            await ws.send("hello")

            match await ws.recv():
                case TextMessage(data=data):
                    print(f"Received text message: {data}")
                case BinaryMessage(data=data):
                    print(f"Received binary message: {data}")
                case _:
                    print("Received some other kind of message")

    Args:
        url:
            The WebSocket URL to connect to. May be provided as a string
            or ``URL`` instance.

        client:
            Optional ``AsyncClient`` to use for the HTTP handshake. If not
            provided, a new client will be created internally.

        subprotocols:
            Optional list of WebSocket subprotocols to include in the
            handshake.

        permessage_deflate:
            Enable or configure the ``permessage-deflate`` WebSocket
            extension. May be set to ``True`` to enable with default
            settings, ``False`` to disable, or an instance of
            ``PerMessageDeflateExtension`` to customize parameters such
            as context takeover and window sizes.
    """

    def __init__(
        self,
        url: URL | str,
        *,
        client: AsyncClient | None = None,
        subprotocols: list[str] | None = None,
        permessage_deflate: bool | PerMessageDeflateExtension = False,
    ) -> None:
        if WSConnection is None:  # type: ignore[reportUnnecessaryComparison]
            raise RuntimeError(
                "wsproto is required for WebSocket support; install with `pip install zapros[websocket]`"
            )

        self._url = URL(url) if isinstance(url, str) else url
        self._client = client
        self._subprotocols = subprotocols

        if permessage_deflate is True:
            self._permessage_deflate = PerMessageDeflateExtension()
        elif permessage_deflate is False:
            self._permessage_deflate = None
        else:
            self._permessage_deflate = permessage_deflate

        self._cm: AbstractAsyncContextManager[AsyncBaseWebSocket] | None = None

    @asynccontextmanager
    async def _connect_once(self) -> AsyncIterator[AsyncBaseWebSocket]:
        host = self._url.host
        path = self._url.pathname + self._url.search

        conn = WSConnection(ConnectionType.CLIENT)
        client = self._client or AsyncClient()

        data_to_send = conn.send(
            Request(
                host=host,
                target=path,
                subprotocols=self._subprotocols or [],
                extensions=[
                    PerMessageDeflate(
                        client_no_context_takeover=self._permessage_deflate.client_no_context_takeover,
                        server_no_context_takeover=self._permessage_deflate.server_no_context_takeover,
                        client_max_window_bits=self._permessage_deflate.client_max_window_bits,
                        server_max_window_bits=self._permessage_deflate.server_max_window_bits,
                    )
                ]
                if self._permessage_deflate
                else [],
            ),
        )

        # wsproto gives us the raw bytes to send for the handshake request,
        # but we need to extract the headers to pass to AsyncClient.
        request_headers = extract_message_headers(data_to_send)

        async with client.stream("GET", self._url, headers=request_headers) as real_response:
            if real_response.status != 101:
                raise RuntimeError(
                    f"WebSocket handshake failed: expected 101 Switching Protocols, got {real_response.status}"
                )

            handoff = real_response.context.get("handoff", {})

            ws: AsyncBaseWebSocket
            if websocket_stream := handoff.get("_asgi_websocket_stream"):  # no-op for synchronous path
                from zapros.websocket._asgi import AsgiWebSocket

                # ASGI path: the ASGI websocket protocol already validated the
                # handshake at the application layer, so wsproto's HTTP-level
                # validation does not apply. Skip the conn.receive_data() step
                # and hand the message-level stream straight to AsgiWebSocket.
                ws = AsgiWebSocket(websocket_stream)  # type: ignore[reportAssignmentType]
            else:
                conn.receive_data(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        + "\r\n".join(f"{k}: {v}" for k, v in real_response.headers.items())
                        + "\r\n\r\n"
                    ).encode()
                )

                for event in conn.events():
                    if isinstance(event, AcceptConnection):
                        break
                else:
                    raise RuntimeError("WebSocket handshake failed")

                network_stream = handoff.get("network_stream")
                if network_stream is None:
                    raise RuntimeError("WebSocket handshake failed: no network stream in response context")

                # The HTTP layer reads in 64 KB chunks, so any WebSocket frames the
                # server sent immediately after the 101 (e.g. an early close) end
                # up buffered in h11 instead of on the stream. Re-inject them into
                # wsproto here so AsyncWebSocket sees them on the first recv.
                trailing_data = handoff.get("trailing_data") or b""
                if trailing_data:
                    conn.receive_data(trailing_data)

                assert isinstance(network_stream, AsyncBaseNetworkStream)
                ws = AsyncWebSocket(network_stream, wsproto_connection=conn)

            try:
                yield ws
            finally:
                await ws.close()

    async def __aenter__(self) -> AsyncBaseWebSocket:
        self._cm = self._connect_once()
        return await self._cm.__aenter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        cm, self._cm = self._cm, None
        if cm is not None:
            await cm.__aexit__(exc_type, exc, tb)
