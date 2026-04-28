from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import unquote

from zapros._constants import DEFAULT_PORTS

from .._models import Request, Response
from ._async_base import AsyncBaseHandler


@dataclass(slots=True)
class LifespanSession:
    state: dict[str, Any]
    receive_queue: "asyncio.Queue[dict[str, Any]]"
    send_queue: "asyncio.Queue[dict[str, Any]]"
    task: "asyncio.Task[None]"


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

        self._lifespan_lock = asyncio.Lock()
        self._lifespan_started = False
        self._lifespan_supported = True
        self._lifespan_state: dict[str, Any] = {}
        self._lifespan_session: LifespanSession | None = None

    @staticmethod
    async def _wait_for_lifespan_message(
        session: LifespanSession,
        *,
        timeout: float | None,
    ) -> dict[str, Any] | None:
        """Wait for next message from the lifespan app, or None if it exits."""
        get_task = asyncio.create_task(session.send_queue.get())
        try:
            done, _ = await asyncio.wait(
                {get_task, session.task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise asyncio.TimeoutError
            if get_task in done:
                return get_task.result()
            return None
        finally:
            if not get_task.done():
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await get_task

    @staticmethod
    async def _cancel_task(task: "asyncio.Task[Any]") -> None:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    @staticmethod
    async def _await_task(
        task: "asyncio.Task[Any]",
        *,
        timeout: float | None,
        timeout_message: str,
    ) -> None:
        try:
            if timeout is None:
                await task
            else:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await AsgiHandler._cancel_task(task)
            raise RuntimeError(timeout_message) from exc

    def _raise_if_lifespan_task_exited(self) -> None:
        session = self._lifespan_session
        if not self._lifespan_started or session is None or not session.task.done():
            return

        self._lifespan_started = False
        self._lifespan_state = {}
        self._lifespan_session = None

        exc = session.task.exception()
        if exc is None:
            raise RuntimeError("ASGI lifespan task exited unexpectedly before shutdown")
        raise RuntimeError("ASGI lifespan task crashed after startup") from exc

    async def _run_lifespan(self) -> None:
        if not self.enable_lifespan or self._lifespan_started or not self._lifespan_supported:
            return

        async with self._lifespan_lock:
            if self._lifespan_started or not self.enable_lifespan or not self._lifespan_supported:
                return

            state: dict[str, Any] = {}
            receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def receive() -> dict[str, Any]:
                return await receive_queue.get()

            async def send(message: dict[str, Any]) -> None:
                await send_queue.put(message)

            scope = {
                "type": "lifespan",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "state": state,
            }

            task = asyncio.create_task(self.app(scope, receive, send))
            session = LifespanSession(
                state=state,
                receive_queue=receive_queue,
                send_queue=send_queue,
                task=task,
            )
            self._lifespan_session = session

            await receive_queue.put({"type": "lifespan.startup"})

            try:
                message = await self._wait_for_lifespan_message(
                    session,
                    timeout=self.startup_timeout,
                )
            except asyncio.TimeoutError as exc:
                self._lifespan_session = None
                self._lifespan_state = {}
                await self._cancel_task(task)
                raise RuntimeError("ASGI lifespan startup timed out") from exc

            if message is None:
                # App exited without sending startup.complete -> assume lifespan unsupported.
                self._lifespan_supported = False
                self._lifespan_session = None
                self._lifespan_state = {}
                return

            msg_type = message["type"]

            if msg_type == "lifespan.startup.complete":
                self._lifespan_state = state
                self._lifespan_started = True
                return

            self._lifespan_session = None
            self._lifespan_state = {}
            await self._cancel_task(task)

            if msg_type == "lifespan.startup.failed":
                detail = message.get("message", "")
                raise RuntimeError(f"ASGI lifespan startup failed: {detail}")

            raise RuntimeError(f"Unexpected ASGI lifespan startup message: {msg_type!r}")

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

        if self._lifespan_supported:
            scope["state"] = self._lifespan_state.copy()

        return scope

    async def ahandle(self, request: Request) -> Response:
        await self._run_lifespan()
        self._raise_if_lifespan_task_exited()

        scope = self._build_scope(request)

        # Buffer the request body up front so receive() is trivial.
        assert not isinstance(request.body, Iterator)
        request_body = (
            request.body
            if isinstance(request.body, bytes)
            else b"".join([chunk async for chunk in request.body])
            if request.body is not None
            else b""
        )
        body_sent = False
        disconnected = asyncio.Event()

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": request_body,
                    "more_body": False,
                }
            # After the body has been delivered there's no more input;
            # block until disconnect (which only happens if the response
            # is fully sent or the caller closes us).
            await disconnected.wait()
            return {"type": "http.disconnect"}

        # Buffer the response. The app runs to completion before we
        # return, so no background task / queue / stream wrapper is needed.
        response_started = False
        response_status: int | None = None
        response_headers: list[tuple[str, str]] = []
        body_chunks: list[bytes] = []
        response_complete = False

        async def send(message: dict[str, Any]) -> None:
            nonlocal response_started, response_status, response_headers, response_complete

            msg_type = message["type"]

            if msg_type == "http.response.start":
                if response_started:
                    raise RuntimeError("ASGI application sent multiple http.response.start messages")
                if message.get("trailers", False):
                    raise NotImplementedError("ASGI response trailers are not supported by AsgiHandler")
                response_status = int(message["status"])
                response_headers = [
                    (bytes(k).decode("ascii"), bytes(v).decode("latin-1")) for k, v in message.get("headers", [])
                ]
                response_started = True
                return

            if msg_type == "http.response.body":
                if not response_started:
                    raise RuntimeError("ASGI application sent http.response.body before http.response.start")
                if response_complete:
                    # Extra body messages after end-of-response are ignored.
                    return
                body = message.get("body", b"")
                if body:
                    body_chunks.append(bytes(body))
                if not message.get("more_body", False):
                    response_complete = True
                    disconnected.set()
                return

            if msg_type == "http.response.trailers":
                raise NotImplementedError("ASGI response trailers are not supported by AsgiHandler")

            raise RuntimeError(f"Unsupported ASGI send message type: {msg_type!r}")

        try:
            await self.app(scope, receive, send)
        finally:
            disconnected.set()

        if not response_started or response_status is None:
            raise RuntimeError("ASGI application returned without sending http.response.start")

        return Response(
            status=response_status,
            headers=response_headers,
            content=b"".join(body_chunks),
        )

    async def aclose(self) -> None:
        if not self.enable_lifespan:
            return
        if not self._lifespan_started or not self._lifespan_supported:
            return

        async with self._lifespan_lock:
            if not self._lifespan_started or not self._lifespan_supported:
                return

            session = self._lifespan_session
            if session is None:
                self._lifespan_started = False
                self._lifespan_state = {}
                return

            await session.receive_queue.put({"type": "lifespan.shutdown"})

            try:
                message = await self._wait_for_lifespan_message(
                    session,
                    timeout=self.shutdown_timeout,
                )
            except asyncio.TimeoutError as exc:
                self._lifespan_started = False
                self._lifespan_state = {}
                self._lifespan_session = None
                await self._cancel_task(session.task)
                raise RuntimeError("ASGI lifespan shutdown timed out") from exc

            self._lifespan_started = False
            self._lifespan_state = {}
            self._lifespan_session = None

            if message is None:
                exc = session.task.exception()
                if exc is None:
                    raise RuntimeError("ASGI lifespan task exited during shutdown without a completion message")
                raise RuntimeError("ASGI lifespan task crashed during shutdown") from exc

            msg_type = message["type"]

            if msg_type == "lifespan.shutdown.complete":
                await self._await_task(
                    session.task,
                    timeout=self.shutdown_timeout,
                    timeout_message="ASGI lifespan app did not exit after shutdown.complete",
                )
                return

            await self._cancel_task(session.task)

            if msg_type == "lifespan.shutdown.failed":
                detail = message.get("message", "")
                raise RuntimeError(f"ASGI lifespan shutdown failed: {detail}")

            raise RuntimeError(f"Unexpected ASGI lifespan shutdown message: {msg_type!r}")
