from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, Literal, Optional, cast
from urllib.parse import unquote

from typing_extensions import Self

from zapros._compat import AnyEvent, AnyQueue, in_trio_run
from zapros._constants import DEFAULT_PORTS
from zapros._errors import AsgiLifespanShutdownTimeoutError, AsgiLifespanStartupTimeoutError

from .._models import AsyncClosableStream, Headers, Request, Response
from ._async_base import AsyncBaseHandler

if TYPE_CHECKING:
    import trio
else:
    try:
        import trio
    except ImportError:
        trio = None

logger = logging.getLogger(__name__)

LifespanStatus = Literal["pending", "complete", "failed"]
LifespanStartupStatus = Literal["pending", "complete", "failed", "not_supported"]

ResponseHeadersAndStatus = tuple[int, list[tuple[str, str]]]

# WebSocket stream lifecycle states.
WebSocketState = Literal["connecting", "connected", "disconnected"]


class AsgiStream(AsyncClosableStream):
    def __init__(
        self,
        send_queue: AnyQueue[dict[str, Any]],
        client_disconnected_event: AnyEvent,
        asyncio_task: Optional[asyncio.Task[None]] = None,
    ) -> None:
        # The queue from which we can read the response body chunks that the ASGI application sends us.
        self._send_queue: AnyQueue[dict[str, Any]] = send_queue

        # Set when the consumer of this stream is done reading and the ASGI
        # application's `receive()` callable should report `http.disconnect`.
        self._client_disconnected_event = client_disconnected_event

        # The task which responsible for sending single request to the
        # ASGI application and putting response body chunks into `send_queue`.
        self._asyncio_task = asyncio_task

        # Set to True when the ASGI application indicates there are no more body chunks to send.
        self._stop_reading = False

    @classmethod
    async def _create_response_with_stream(
        cls,
        app: Any,
        scope: dict[str, Any],
        request_body: bytes | AsyncIterator[bytes] | None,
        trio_nursery: Optional["trio.Nursery"] = None,
    ) -> Response:
        send_queue = AnyQueue[dict[str, Any]]()

        response_headers_and_status_received_event = AnyEvent()
        client_disconnected_event = AnyEvent()
        response_headers_and_status: Optional[ResponseHeadersAndStatus] = None
        app_raised = False

        async def _run() -> None:
            """
            Sends the ASGI HTTP request to the application and receives
            the response, putting response body chunks into `send_queue`.
            Request body is streamed from `request_body` if it's an async iterator, or one-shot if it's bytes or None.
            """
            nonlocal response_headers_and_status
            request_complete = False

            async def receive() -> dict[str, Any]:
                nonlocal request_complete

                if request_complete:
                    # Per ASGI spec, after the request body is fully delivered,
                    # `receive()` must block until the client actually disconnects.
                    # Returning `http.disconnect` immediately would make ASGI apps
                    # (e.g. Litestar's streaming responses listening for disconnects)
                    # cancel themselves before they can finish sending the response.
                    await client_disconnected_event.wait()
                    return {"type": "http.disconnect"}

                if isinstance(request_body, bytes):
                    # One-shot the body if it's already fully available as bytes.
                    body = request_body
                    request_complete = True
                    return {"type": "http.request", "body": body, "more_body": False}
                elif request_body is None:
                    request_complete = True
                    return {"type": "http.request", "more_body": False}
                else:
                    assert not isinstance(request_body, Iterator)

                    try:
                        chunk = await request_body.__anext__()
                        return {"type": "http.request", "body": chunk, "more_body": True}
                    except StopAsyncIteration:
                        request_complete = True
                        return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: dict[str, Any]) -> None:
                nonlocal response_headers_and_status

                msg_type = message["type"]
                if msg_type == "http.response.start":
                    status = message["status"]
                    headers = [(k.decode("ascii"), v.decode("latin-1")) for k, v in message.get("headers", [])]

                    response_headers_and_status = (status, headers)
                    response_headers_and_status_received_event.set()

                elif msg_type == "http.response.body":
                    await send_queue.put(message)

                else:
                    raise RuntimeError(f"Unexpected ASGI HTTP message type: {msg_type!r}")

            try:
                await app(
                    scope,
                    receive,
                    send,
                )
            except BaseException:
                # If the app raised before sending response headers, surface a
                # static 500 response (per ASGI spec recommendations) and exit
                # cleanly so the awaiting caller can return without ever
                # creating a stream. If headers were already sent, the response
                # has already started streaming and we can't change the status,
                # so just exit and let any in-flight body chunks finish.
                if not response_headers_and_status_received_event.is_set():
                    nonlocal app_raised
                    app_raised = True
                    response_headers_and_status = (500, [])
                    response_headers_and_status_received_event.set()

        task: Optional[asyncio.Task[None]] = None
        if trio_nursery is not None:
            trio_nursery.start_soon(_run)
        else:
            task = asyncio.create_task(_run())

        logger.debug("Waiting for ASGI application to send response headers and status...")
        await response_headers_and_status_received_event.wait()
        logger.debug("Received ASGI application response headers and status")

        response_headers_and_status = cast(ResponseHeadersAndStatus, response_headers_and_status)

        if app_raised:
            return Response(
                status=response_headers_and_status[0],
                headers=Headers(response_headers_and_status[1]),
                content=b"Internal Server Error",
            )
        stream = cls(
            send_queue=send_queue,
            client_disconnected_event=client_disconnected_event,
            asyncio_task=task,
        )

        return Response(
            status=response_headers_and_status[0],
            headers=Headers(response_headers_and_status[1]),
            content=stream,
        )

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        if self._stop_reading:
            raise StopAsyncIteration

        logging.debug("Waiting for next response body chunk from ASGI application...")
        message = await self._send_queue.get()
        logging.debug("Received response body chunk from ASGI application: %s", message)

        body = message.get("body", b"")
        more_body = message.get("more_body", False)

        if not more_body:
            self._stop_reading = True
            self._client_disconnected_event.set()
        return body

    async def aclose(self) -> None:
        # Signal the ASGI application that the client has disconnected so any
        # `receive()` call still pending in the application can return.
        self._client_disconnected_event.set()
        if self._asyncio_task is not None:
            self._asyncio_task.cancel()
            try:
                await self._asyncio_task
            except asyncio.CancelledError:
                pass
        await self._send_queue.aclose()


class AsgiWebSocketStream:
    """
    A bidirectional handle to an ASGI WebSocket connection.

    This object is exposed to upstream code via `Response(context={"handoff": {"_asgi_websocket_stream": ...}})`
    once the handshake has completed successfully. The application is driven by a background
    task that:
      * delivers `websocket.connect` / `websocket.receive` / `websocket.disconnect` events
        to the app via `receive()`, by reading from `_client_to_app_queue`
      * collects `websocket.accept` / `websocket.send` / `websocket.close` events from the app
        via `send()`, by writing to `_app_to_client_queue`

    Upstream usage:
        await stream.asend(text="hello")
        msg = await stream.areceive()   # raises
        await stream.aclose(code=1000, reason="bye")
    """

    def __init__(
        self,
        client_to_app_queue: AnyQueue[dict[str, Any]],
        app_to_client_queue: AnyQueue[dict[str, Any]],
        accept_subprotocol: Optional[str],
        accept_headers: list[tuple[str, str]],
        asyncio_task: Optional[asyncio.Task[None]] = None,
    ) -> None:
        # Queue we put `websocket.receive` / `websocket.disconnect` events into
        # for the ASGI application to consume.
        self._client_to_app_queue: AnyQueue[dict[str, Any]] = client_to_app_queue

        # Queue the ASGI application puts `websocket.send` / `websocket.close` events into
        # for upstream code to consume via `areceive()`.
        self._app_to_client_queue: AnyQueue[dict[str, Any]] = app_to_client_queue

        # Subprotocol & extra headers chosen by the application during accept;
        # exposed so upstream code (e.g. a real WS proxy) can mirror them on the
        # wire when completing the handshake with the actual client.
        self.accept_subprotocol = accept_subprotocol
        self.accept_headers = accept_headers

        self._asyncio_task = asyncio_task

        self._state: WebSocketState = "connected"

    @property
    def state(self) -> WebSocketState:
        return self._state

    @classmethod
    async def _create_response_with_stream(
        cls,
        app: Any,
        scope: dict[str, Any],
        trio_nursery: Optional["trio.Nursery"] = None,
    ) -> Response:
        """
        Drive the ASGI websocket handshake and, once completed, return an
        HTTP-shaped `Response` that carries the live `AsgiWebSocketStream` in
        `context["handoff"]["_asgi_websocket_stream"]`.

        On accept: returns a 101 response with the stream in context.
        On reject (close before accept, or app raised before accept): returns a
        403 response with no stream in context.
        """
        client_to_app_queue = AnyQueue[dict[str, Any]]()
        app_to_client_queue = AnyQueue[dict[str, Any]]()

        # Fired once the app has either accepted or closed the handshake;
        # `handshake_result` carries the outcome.
        handshake_done_event = AnyEvent()
        handshake_result: dict[str, Any] = {}

        close_was_received = False

        # Pre-load the `websocket.connect` event so the very first
        # `receive()` call from the app returns it without blocking.
        await client_to_app_queue.put({"type": "websocket.connect"})

        async def _run() -> None:
            async def receive() -> dict[str, Any]:
                msg = await client_to_app_queue.get()
                logger.debug("ASGI websocket app receive(): %s", msg.get("type"))
                return msg

            async def send(message: dict[str, Any]) -> None:
                msg_type = message["type"]
                logger.debug("ASGI websocket app send(): %s", msg_type)
                if msg_type == "websocket.accept":
                    if handshake_done_event.is_set():
                        # Spec: accept after accept (or after close) is invalid.
                        raise RuntimeError("websocket.accept sent after handshake already completed")
                    subprotocol = message.get("subprotocol")
                    raw_headers: list[tuple[bytes, bytes]] = message.get("headers", []) or []
                    headers = [(k.decode("ascii"), v.decode("latin-1")) for k, v in raw_headers]
                    handshake_result["accepted"] = True
                    handshake_result["subprotocol"] = subprotocol
                    handshake_result["headers"] = headers
                    handshake_done_event.set()

                elif msg_type == "websocket.close":
                    code = message.get("code", 1000)
                    reason = message.get("reason", "") or ""
                    if not handshake_done_event.is_set():
                        # Close before accept = reject; per spec this is HTTP 403.
                        handshake_result["accepted"] = False
                        handshake_result["code"] = code
                        handshake_result["reason"] = reason
                        handshake_done_event.set()
                    else:
                        nonlocal close_was_received
                        # Close after accept = normal end-of-stream; deliver to consumer.
                        close_was_received = True
                        await app_to_client_queue.put(message)

                elif msg_type == "websocket.send":
                    if not handshake_done_event.is_set():
                        raise RuntimeError("websocket.send sent before websocket.accept")
                    await app_to_client_queue.put(message)

                else:
                    raise RuntimeError(f"Unexpected ASGI websocket message type: {msg_type!r}")

            try:
                await app(scope, receive, send)
            except BaseException:
                # If the app dies before completing the handshake, treat as a
                # rejection (HTTP 403). If it dies after accept, push a synthetic
                # close into the consumer queue so `areceive()` raises a clean
                # disconnect rather than hanging.
                if not handshake_done_event.is_set():
                    handshake_result["accepted"] = False
                    handshake_result["code"] = 1011  # internal error
                    handshake_result["reason"] = "ASGI application raised before accept"
                    handshake_done_event.set()
                elif not close_was_received:
                    await app_to_client_queue.put(
                        {"type": "websocket.close", "code": 1011, "reason": "ASGI application raised"}
                    )
                return

            # App returned without explicit close. If accept happened, that's an
            # implicit graceful close; if not, it's a rejection.
            if not handshake_done_event.is_set():
                handshake_result["accepted"] = False
                handshake_result["code"] = 1006
                handshake_result["reason"] = "ASGI application returned before accept"
                handshake_done_event.set()
            elif not close_was_received:
                await app_to_client_queue.put({"type": "websocket.close", "code": 1000, "reason": ""})

        task: Optional[asyncio.Task[None]] = None
        if trio_nursery is not None:
            trio_nursery.start_soon(_run)
        else:
            task = asyncio.create_task(_run())

        logger.debug("Waiting for ASGI application to complete websocket handshake...")
        await handshake_done_event.wait()
        logger.debug("ASGI websocket handshake completed: %s", handshake_result)

        if not handshake_result.get("accepted"):
            # Rejected handshake: surface as HTTP 403, no stream handoff.
            # Cancel the background task — there is no further work for it to do.
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, BaseException):
                    pass
            return Response(
                status=403,
                headers=Headers([]),
                content=b"",
            )

        stream = cls(
            client_to_app_queue=client_to_app_queue,
            app_to_client_queue=app_to_client_queue,
            accept_subprotocol=handshake_result.get("subprotocol"),
            accept_headers=handshake_result.get("headers", []),
            asyncio_task=task,
        )

        # Build the accept-time HTTP response. Status 101 is the on-the-wire
        # equivalent of a successful WS handshake; upstream code that's
        # bridging to a real socket can use this together with `accept_headers`
        # / `accept_subprotocol` to complete the wire handshake.
        return Response(
            status=101,
            headers=Headers(handshake_result.get("headers", [])),
            content=b"",
            context={"handoff": {"_asgi_websocket_stream": stream}},
        )

    async def asend(
        self,
        *,
        text: Optional[str] = None,
        bytes: Optional[bytes] = None,  # noqa: A002 - matches ASGI spec key name
    ) -> None:
        """
        Send a `websocket.receive` event to the ASGI application. Per spec,
        exactly one of `text` or `bytes` must be non-None.
        """
        if self._state != "connected":
            raise RuntimeError(f"Cannot send on websocket in state {self._state!r}")
        if (text is None) == (bytes is None):
            raise ValueError("Exactly one of `text` or `bytes` must be provided")

        message: dict[str, Any] = {"type": "websocket.receive"}
        if text is not None:
            message["text"] = text
        else:
            message["bytes"] = bytes
        await self._client_to_app_queue.put(message)

    async def areceive(self) -> dict[str, Any]:
        """
        Read the next event the ASGI application has sent to the client.

        Returns the raw ASGI message dict for `websocket.send` events
        (`{"type": "websocket.send", "text"/"bytes": ...}`).

        Raises `ConnectionClosed` when the application closes the
        connection (either via an explicit `websocket.close` or by returning).
        """
        from zapros.websocket._errors import ConnectionClosed

        if self._state == "disconnected":
            raise ConnectionClosed(code=1006, reason="")

        message = await self._app_to_client_queue.get()
        msg_type = message.get("type")

        if msg_type == "websocket.close":
            self._state = "disconnected"
            raise ConnectionClosed(
                code=message.get("code", 1000),
                reason=message.get("reason", "") or "",
            )

        return message

    async def aclose(self, code: int = 1000, reason: str = "") -> None:
        """
        Tell the ASGI application that the client has disconnected, then tear
        down the background task. Idempotent.
        """
        if self._state != "disconnected":
            self._state = "disconnected"
            # Best-effort: notify the app. If the app has already exited, the
            # queue put still succeeds — no one will read it, but that's fine.
            try:
                await self._client_to_app_queue.put({"type": "websocket.disconnect", "code": code, "reason": reason})
            except Exception:
                # Queue may already be closed if the app exited first; ignore.
                pass

        if self._asyncio_task is not None and not self._asyncio_task.done():
            self._asyncio_task.cancel()
            try:
                await self._asyncio_task
            except asyncio.CancelledError:
                pass

        await self._client_to_app_queue.aclose()
        await self._app_to_client_queue.aclose()


class AsgiHandler(AsyncBaseHandler):
    def __init__(
        self,
        app: Any,
        *,
        client: tuple[str, int] | None = ("127.0.0.1", 123),
        root_path: str = "",
        http_version: str = "1.1",
        enable_lifespan: bool = True,
        startup_timeout: float | None = 10.0,
        shutdown_timeout: float | None = 10.0,
    ) -> None:
        self.app = app
        self.client = client
        self.root_path = root_path
        self.http_version = http_version
        self.enable_lifespan = enable_lifespan
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout

        # event fired to signal the lifespan task to start shutdown sequence
        self._lifespan_close_event = AnyEvent()

        # fired when the lifespan startup sequence has finished, regardless of outcome;
        # check self._lifespan_startup_status to know whether it completed or failed.
        # see https://asgi.readthedocs.io/en/latest/specs/lifespan.html#startup
        self._lifespan_startup_event = AnyEvent()
        self._lifespan_startup_status: LifespanStartupStatus = "pending"
        self._lifespan_startup_failure_message: Optional[str] = None

        # fired when the lifespan shutdown sequence has finished, regardless of outcome;
        # check self._lifespan_shutdown_status to know whether it completed or failed.
        # see https://asgi.readthedocs.io/en/latest/specs/lifespan.html#shutdown
        self._lifespan_shutdown_event = AnyEvent()
        self._lifespan_shutdown_status: LifespanStatus = "pending"
        self._lifespan_shutdown_failure_message: Optional[str] = None

        # the state dict passed to the ASGI lifespan scope; application can store arbitrary data here
        self._lifespan_state: dict[str, Any] = {}

        # background setup
        self._trio_nursery_cm: Optional[AbstractAsyncContextManager["trio.Nursery"]] = None
        self._trio_nursery: Optional["trio.Nursery"] = None

        self._asyncio_task: asyncio.Task[None] | None = None

    def _is_websocket_request(self, request: Request) -> bool:
        scheme = request.url.protocol[:-1].lower()
        if scheme in ("ws", "wss"):
            return True
        # Also detect HTTP requests that are upgrading to WebSocket.
        upgrade = request.headers.get("upgrade", "")
        return upgrade.lower() == "websocket"

    def _build_scope(self, request: Request) -> dict[str, Any]:
        headers = [(k.lower().encode("ascii"), v.encode("latin-1")) for k, v in request.headers.list()]

        scheme = request.url.protocol[:-1]
        server_port = request.url.port or DEFAULT_PORTS.get(scheme, 80)
        raw_path = request.url.pathname.encode("utf-8")

        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": self.http_version,
            "method": request.method.upper(),
            "scheme": scheme,
            "path": unquote(request.url.pathname) or "/",
            "raw_path": raw_path or b"/",
            "query_string": request.url.search[1:].encode("utf-8"),
            "root_path": self.root_path,
            "headers": headers,
            "client": self.client,
            "server": (request.url.hostname, server_port),
        }

        if self.enable_lifespan:
            scope["state"] = self._lifespan_state.copy()

        return scope

    def _build_websocket_scope(self, request: Request) -> dict[str, Any]:
        headers = [(k.lower().encode("ascii"), v.encode("latin-1")) for k, v in request.headers.list()]

        # Map http(s) -> ws(s) when caller routed an upgrading HTTP request here.
        scheme = request.url.protocol[:-1].lower()
        ws_scheme_map = {"http": "ws", "https": "wss"}
        scheme = ws_scheme_map.get(scheme, scheme) if scheme not in ("ws", "wss") else scheme

        server_port = request.url.port or DEFAULT_PORTS.get(scheme, 80)
        raw_path = request.url.pathname.encode("utf-8")

        # Subprotocols come from the Sec-WebSocket-Protocol request header,
        # comma-separated per RFC 6455.
        subprotocols_header = request.headers.get("sec-websocket-protocol", "")
        subprotocols = [p.strip() for p in subprotocols_header.split(",") if p.strip()] if subprotocols_header else []

        scope: dict[str, Any] = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.5"},
            "http_version": self.http_version,
            "scheme": scheme,
            "path": unquote(request.url.pathname) or "/",
            "raw_path": raw_path or b"/",
            "query_string": request.url.search[1:].encode("utf-8"),
            "root_path": self.root_path,
            "headers": headers,
            "client": self.client,
            "server": (request.url.hostname, server_port),
            "subprotocols": subprotocols,
        }

        if self.enable_lifespan:
            scope["state"] = self._lifespan_state.copy()

        return scope

    async def _run_lifespan(self) -> None:
        lifespan_startup_sent = False

        async def lifespan_receive() -> dict[str, Any]:
            nonlocal lifespan_startup_sent
            if not lifespan_startup_sent:
                lifespan_startup_sent = True
                return {"type": "lifespan.startup"}

            logger.debug("Lifespan shutdown sequence initiated, waiting for shutdown signal...")
            await self._lifespan_close_event.wait()
            logger.debug("Lifespan shutdown signal received, sending shutdown message to application...")
            return {"type": "lifespan.shutdown"}

        async def lifespan_send(message: dict[str, Any]) -> None:
            msg_type = message["type"]
            if msg_type == "lifespan.startup.complete":
                self._lifespan_startup_status = "complete"
                self._lifespan_startup_event.set()
            elif msg_type == "lifespan.startup.failed":
                self._lifespan_startup_status = "failed"
                self._lifespan_startup_failure_message = message.get("message")
                self._lifespan_startup_event.set()
            elif msg_type == "lifespan.shutdown.complete":
                self._lifespan_shutdown_status = "complete"
                self._lifespan_shutdown_event.set()
            elif msg_type == "lifespan.shutdown.failed":
                self._lifespan_shutdown_status = "failed"
                self._lifespan_shutdown_failure_message = message.get("message")
                self._lifespan_shutdown_event.set()
            else:
                raise RuntimeError(f"Unexpected ASGI lifespan message type: {msg_type!r}")

        scope = {
            "type": "lifespan",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "state": self._lifespan_state,
        }

        try:
            await self.app(
                scope,
                lifespan_receive,
                lifespan_send,
            )
        except Exception:
            # Per the specification, if the application throws an exception
            # here we can continue without the lifespan protocol.
            # If the application wants to stop the server
            # (zapros's handler in our case) from starting up, it should instead
            # respond with a `lifespan.startup.failed` event.
            self._lifespan_startup_event.set()
            self._lifespan_startup_status = "not_supported"

    async def _ensure_lifespan_started(self) -> None:
        """Block until lifespan startup is done (or raise on timeout/failure)."""
        if not self.enable_lifespan:
            return

        if self._asyncio_task is None and not in_trio_run():
            self._asyncio_task = asyncio.create_task(self._run_lifespan())

        logger.debug("Waiting for ASGI application lifespan startup to complete...")
        was_set = await self._lifespan_startup_event.wait(self.startup_timeout)
        logger.debug("ASGI application lifespan startup completed with status: %s", self._lifespan_startup_status)

        if not was_set:
            raise AsgiLifespanStartupTimeoutError(
                f"ASGI application lifespan startup did not complete within {self.startup_timeout} seconds"
            )

        if self._lifespan_startup_status == "failed":
            # Per the specification, if the lifespan startup fails, server should the exit with an error.
            raise RuntimeError(
                "ASGI application lifespan startup failed: "
                f"{self._lifespan_startup_failure_message or 'no message provided'}"
            )

    async def ahandle(self, request: Request) -> Response:
        if in_trio_run() and self._trio_nursery is None:
            raise RuntimeError(
                "When using `AsgiHandler` with Trio, you must use it as an async "
                "context manager (i.e. `async with AsgiHandler(...) as handler:`)"
            )

        await self._ensure_lifespan_started()

        if self._is_websocket_request(request):
            return await AsgiWebSocketStream._create_response_with_stream(  # type: ignore[reportPrivateUsage]
                app=self.app,
                scope=self._build_websocket_scope(request),
                trio_nursery=self._trio_nursery,
            )

        assert not isinstance(request.body, Iterator)
        response = await AsgiStream._create_response_with_stream(  # type: ignore[reportPrivateUsage]
            app=self.app,
            scope=self._build_scope(request),
            request_body=request.body,
            trio_nursery=self._trio_nursery,
        )
        return response

    async def __aenter__(self) -> Self:
        """
        Trio's phylosophy is that you shouldn't have background tasks
        running if you're not inside a nursery, so to respect that,
        we require users to use `AsgiHandler` as an async context manager when using with Trio.
        It's not required when using with asyncio, but it
        doesn't hurt to use it as a context manager in that case either.
        """

        if in_trio_run():
            self._trio_nursery_cm = trio.open_nursery()
            self._trio_nursery = await self._trio_nursery_cm.__aenter__()

            if self.enable_lifespan:
                self._trio_nursery.start_soon(self._run_lifespan)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if in_trio_run() and self._trio_nursery_cm is not None:
            await self._trio_nursery_cm.__aexit__(exc_type, exc, tb)

    async def aclose(self) -> None:
        """
        Ensures that the ASGI application's lifespan shutdown sequence is triggered (if supported by the application)
        and waits for it to complete before returning. If the application does not support the lifespan protocol, this
        method does nothing.
        """
        if not self.enable_lifespan:
            return

        logger.debug("Waiting for ASGI application lifespan startup to complete before triggering shutdown...")
        was_set = await self._lifespan_startup_event.wait(self.startup_timeout)
        logger.debug(
            "ASGI application lifespan startup completed with status: %s, proceeding to trigger shutdown if supported",
            self._lifespan_startup_status,
        )

        if not was_set:
            raise AsgiLifespanStartupTimeoutError(
                f"ASGI application lifespan startup did not complete within {self.startup_timeout} seconds"
            )

        # Per spec, we only need to trigger the shutdown sequence if the startup completed successfully.
        if self._lifespan_startup_status == "complete":
            # Signal the lifespan task to start the shutdown sequence.
            self._lifespan_close_event.set()

            logger.debug("Waiting for ASGI application lifespan shutdown to complete...")
            # Wait for the shutdown sequence to complete (either successfully or with failure).
            was_set = await self._lifespan_shutdown_event.wait(self.shutdown_timeout)
            logger.debug("ASGI application lifespan shutdown completed with status: %s", self._lifespan_shutdown_status)

            if not was_set:
                raise AsgiLifespanShutdownTimeoutError(
                    f"ASGI application lifespan shutdown did not complete within {self.shutdown_timeout} seconds"
                )

            # Per the specification, if the shutdown sequence fails,
            # we should log/throw an exception
            if self._lifespan_shutdown_status == "failed":
                raise RuntimeError(
                    "ASGI application lifespan shutdown failed: "
                    f"{self._lifespan_shutdown_failure_message or 'no message provided'}"
                )

        if self._asyncio_task is not None:
            self._asyncio_task.cancel()
