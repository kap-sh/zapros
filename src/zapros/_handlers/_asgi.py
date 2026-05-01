from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, Literal, Optional, cast
from urllib.parse import unquote

from typing_extensions import Self

from zapros._compat import AnyEvent, AnyEventTimeoutError, AnyQueue, in_trio_run
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

    async def ahandle(self, request: Request) -> Response:
        if in_trio_run() and self._trio_nursery is None:
            raise RuntimeError(
                "When using `AsgiHandler` with Trio, you must use it as an async "
                "context manager (i.e. `async with AsgiHandler(...) as handler:`)"
            )
        if self.enable_lifespan:
            if self._asyncio_task is None and not in_trio_run():
                self._asyncio_task = asyncio.create_task(self._run_lifespan())

            try:
                logger.debug("Waiting for ASGI application lifespan startup to complete...")
                await self._lifespan_startup_event.wait(self.startup_timeout)
                logger.debug(
                    "ASGI application lifespan startup completed with status: %s", self._lifespan_startup_status
                )
            except AnyEventTimeoutError:
                raise AsgiLifespanStartupTimeoutError(
                    f"ASGI application lifespan startup did not complete within {self.startup_timeout} seconds"
                )

            if self._lifespan_startup_status == "failed":
                # Per the specification, if the lifespan startup fails, server should the exit with an error.
                raise RuntimeError(
                    "ASGI application lifespan startup failed: "
                    f"{self._lifespan_startup_failure_message or 'no message provided'}"
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

        try:
            logger.debug("Waiting for ASGI application lifespan startup to complete before triggering shutdown...")
            await self._lifespan_startup_event.wait(self.startup_timeout)
            logger.debug(
                "ASGI application lifespan startup completed with status: %s, "
                "proceeding to trigger shutdown if supported",
                self._lifespan_startup_status,
            )
        except AnyEventTimeoutError:
            raise AsgiLifespanStartupTimeoutError(
                f"ASGI application lifespan startup did not complete within {self.startup_timeout} seconds"
            )

        # Per spec, we only need to trigger the shutdown sequence if the startup completed successfully.
        if self._lifespan_startup_status == "complete":
            # Signal the lifespan task to start the shutdown sequence.
            self._lifespan_close_event.set()

            try:
                logger.debug("Waiting for ASGI application lifespan shutdown to complete...")
                # Wait for the shutdown sequence to complete (either successfully or with failure).
                await self._lifespan_shutdown_event.wait(self.shutdown_timeout)
                logger.debug(
                    "ASGI application lifespan shutdown completed with status: %s", self._lifespan_shutdown_status
                )
            except AnyEventTimeoutError:
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
