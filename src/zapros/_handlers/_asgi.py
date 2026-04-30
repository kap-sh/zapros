from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Iterator, Literal, Optional
from urllib.parse import unquote

from typing_extensions import Self

from zapros._compat import AnyEvent, AnyEventTimeoutError, in_trio_run
from zapros._constants import DEFAULT_PORTS
from zapros._errors import AsgiLifespanShutdownTimeoutError, AsgiLifespanStartupTimeoutError

from .._models import Headers, Request, Response
from ._async_base import AsyncBaseHandler

if TYPE_CHECKING:
    import trio
else:
    try:
        import trio
    except ImportError:
        trio = None


LifespanStatus = Literal["pending", "complete", "failed"]
LifespanStartupStatus = Literal["pending", "complete", "failed", "not_supported"]


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

            await self._lifespan_close_event.wait()
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
        if self.enable_lifespan:
            if in_trio_run() and self._trio_nursery_cm is None:
                raise RuntimeError(
                    "When using `AsgiHandler` with Trio, you must use it as an async "
                    "context manager (i.e. `async with AsgiHandler(...) as handler:`)"
                )
            else:
                if self._asyncio_task is None and not in_trio_run():
                    self._asyncio_task = asyncio.create_task(self._run_lifespan())

                try:
                    await self._lifespan_startup_event.wait(self.startup_timeout)
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

        response_status: int | None = None
        response_headers: list[tuple[str, str]] | None = None
        response_body_chunks: list[bytes] = []
        response_complete = False

        async def receive() -> dict[str, Any]:
            nonlocal response_complete

            if response_complete:
                return {"type": "http.disconnect"}

            if isinstance(request.body, bytes):
                # One-shot the body if it's already fully available as bytes.
                body = request.body
                response_complete = True
                return {"type": "http.request", "body": body, "more_body": False}
            elif request.body is None:
                response_complete = True
                return {"type": "http.request", "more_body": False}
            else:
                assert not isinstance(request.body, Iterator)

                try:
                    chunk = await request.body.__anext__()
                    return {"type": "http.request", "body": chunk, "more_body": True}
                except StopAsyncIteration:
                    response_complete = True
                    return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            nonlocal response_status, response_headers, response_body_chunks

            msg_type = message["type"]
            if msg_type == "http.response.start":
                status = message["status"]
                headers = [(k.decode("ascii"), v.decode("latin-1")) for k, v in message.get("headers", [])]
                response_status = status
                response_headers = headers

            elif msg_type == "http.response.body":
                body = message.get("body", b"")
                response_body_chunks.append(body)
            else:
                raise RuntimeError(f"Unexpected ASGI HTTP message type: {msg_type!r}")

        try:
            await self.app(
                self._build_scope(request),
                receive,
                send,
            )
        except Exception:
            # Treat exceptions as 500 Internal Server Errors, per ASGI spec recommendations.
            response_status = 500
            response_headers = []

        assert response_status is not None
        assert response_headers is not None

        return Response(
            status=response_status,
            headers=Headers([(k, v) for k, v in response_headers]),
            content=b"".join(response_body_chunks),
        )

    async def __aenter__(self) -> Self:
        """
        Trio's phylosophy is that you shouldn't have background tasks
        running if you're not inside a nursery, so to respect that,
        we require users to use `AsgiHandler` as an async context manager when using with Trio.
        It's not required when using with asyncio, but it
        doesn't hurt to use it as a context manager in that case either.
        """

        if in_trio_run() and self.enable_lifespan:
            self._trio_nursery_cm = trio.open_nursery()
            self._trio_nursery = await self._trio_nursery_cm.__aenter__()
            self._trio_nursery.start_soon(self._run_lifespan)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if in_trio_run() and self._trio_nursery_cm is not None and self.enable_lifespan:
            assert self._trio_nursery_cm is not None
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
            await self._lifespan_startup_event.wait(self.startup_timeout)
        except AnyEventTimeoutError:
            raise AsgiLifespanStartupTimeoutError(
                f"ASGI application lifespan startup did not complete within {self.startup_timeout} seconds"
            )

        # Per spec, we only need to trigger the shutdown sequence if the startup completed successfully.
        if self._lifespan_startup_status == "complete":
            # Signal the lifespan task to start the shutdown sequence.
            self._lifespan_close_event.set()

            try:
                # Wait for the shutdown sequence to complete (either successfully or with failure).
                await self._lifespan_shutdown_event.wait(self.shutdown_timeout)
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
