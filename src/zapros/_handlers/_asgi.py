from __future__ import annotations

import asyncio
import contextlib
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Generator,
    Iterator as ABCIterator,
)
from dataclasses import dataclass
from typing import Any

from typing_extensions import override

from zapros._constants import (
    DEFAULT_PORTS,
)

from .._models import (
    AsyncClosableStream,
    Request,
    Response,
)
from ._async_base import (
    AsyncBaseHandler,
)


@dataclass(slots=True)
class _QueuedBodyChunk:
    body: bytes
    more_body: bool


@dataclass(slots=True)
class _LifespanSession:
    state: dict[str, Any]
    receive_queue: "asyncio.Queue[dict[str, Any]]"
    send_queue: "asyncio.Queue[dict[str, Any]]"
    task: "asyncio.Task[None]"


class _RequestBodySource:
    def __init__(
        self,
        source: bytes | ABCIterator[bytes] | AsyncIterator[bytes] | None,
    ) -> None:
        self._source = source
        self._done = False
        self._closed = False

    @property
    def done(self) -> bool:
        return self._done

    async def next_event(
        self,
    ) -> dict[str, Any]:
        if self._done:
            raise RuntimeError("Request body source is already exhausted")

        source = self._source

        if source is None:
            self._done = True
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        if isinstance(source, bytes):
            self._done = True
            self._source = None
            return {
                "type": "http.request",
                "body": source,
                "more_body": False,
            }

        if isinstance(source, ABCIterator):
            raise RuntimeError("Synchronous iterators are not supported as request body sources by AsgiHandler")

        async_iter = source
        try:
            chunk = await anext(async_iter)
        except StopAsyncIteration:
            self._done = True
            self._source = None
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        return {
            "type": "http.request",
            "body": bytes(chunk),
            "more_body": True,
        }

    async def aclose(self) -> None:
        if self._closed:
            return

        self._closed = True
        source = self._source
        self._source = None
        self._done = True

        if source is None or isinstance(source, bytes):
            return

        if isinstance(source, AsyncGenerator):
            await source.aclose()
            return

        if isinstance(source, Generator):
            source.close()


class _ResponseStream(AsyncClosableStream):
    def __init__(
        self,
        body_queue: "asyncio.Queue[_QueuedBodyChunk | BaseException | None]",
        app_task: "asyncio.Task[None]",
        disconnect_event: "asyncio.Event",
    ) -> None:
        self._body_queue = body_queue
        self._app_task = app_task
        self._disconnect_event = disconnect_event
        self._closed = False

    def __aiter__(
        self,
    ) -> AsyncIterator[bytes]:
        return self

    async def _finalize(self, *, abort: bool) -> BaseException | None:
        if self._closed:
            return None

        self._closed = True
        self._disconnect_event.set()

        if abort:
            if not self._app_task.done():
                self._app_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await self._app_task
            return None

        try:
            await self._app_task
        except BaseException as exc:
            return exc

        return None

    async def __anext__(self) -> bytes:
        while True:
            if self._closed:
                raise StopAsyncIteration

            item = await self._body_queue.get()

            if item is None:
                task_error = await self._finalize(abort=False)
                if task_error is not None:
                    raise task_error
                raise StopAsyncIteration

            if isinstance(item, BaseException):
                task_error = await self._finalize(abort=False)
                raise task_error or item

            if item.body:
                return item.body

            if not item.more_body:
                task_error = await self._finalize(abort=False)
                if task_error is not None:
                    raise task_error
                raise StopAsyncIteration

    @override
    async def aclose(self) -> None:
        await self._finalize(abort=True)


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
        self._lifespan_session: _LifespanSession | None = None

    @staticmethod
    def _iter_request_body(
        request: Request,
    ) -> bytes | ABCIterator[bytes] | AsyncIterator[bytes] | None:
        if request.body is None:
            return None
        if isinstance(request.body, bytes):
            return request.body
        if isinstance(request.body, ABCIterator):
            return request.body
        return request.body

    @staticmethod
    def _get_raw_path_bytes(
        request: Request,
    ) -> bytes | None:
        raw_path = getattr(request, "raw_path", None)
        if raw_path is None:
            raw_path = getattr(
                request.url,
                "raw_path",
                None,
            )

        if isinstance(raw_path, memoryview):
            return raw_path.tobytes()
        if isinstance(raw_path, (bytes, bytearray)):
            return bytes(raw_path)

        return None

    @staticmethod
    def _get_query_string_bytes(
        request: Request,
    ) -> bytes:
        raw_query = getattr(
            request,
            "raw_query_string",
            None,
        )
        if raw_query is None:
            raw_query = getattr(
                request.url,
                "raw_query",
                None,
            )
        if raw_query is None:
            raw_query = request.url.search

        if raw_query in (None, ""):
            return b""

        if isinstance(raw_query, memoryview):
            raw_query_bytes = raw_query.tobytes()
            return raw_query_bytes[1:] if raw_query_bytes.startswith(b"?") else raw_query_bytes
        if isinstance(
            raw_query,
            (bytes, bytearray),
        ):
            raw_query_bytes = bytes(raw_query)
            return raw_query_bytes[1:] if raw_query_bytes.startswith(b"?") else raw_query_bytes

        query_string = str(raw_query)
        if query_string.startswith("?"):
            query_string = query_string[1:]
        return query_string.encode("ascii")

    @staticmethod
    async def _wait_for_lifespan_message(
        session: _LifespanSession,
        *,
        timeout: float | None,
    ) -> dict[str, Any] | None:
        message_task = asyncio.create_task(session.send_queue.get())
        try:
            (
                done,
                _,
            ) = await asyncio.wait(
                {
                    message_task,
                    session.task,
                },
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise asyncio.TimeoutError

            if message_task in done:
                return message_task.result()

            if not session.send_queue.empty():
                return session.send_queue.get_nowait()

            return None
        finally:
            if not message_task.done():
                message_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await message_task

    @staticmethod
    async def _cancel_task(
        task: "asyncio.Task[Any]",
    ) -> None:
        if not task.done():
            task.cancel()
        with contextlib.suppress(
            asyncio.CancelledError,
            Exception,
        ):
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
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=timeout,
                )
        except asyncio.TimeoutError as exc:
            if not task.done():
                task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    Exception,
                ):
                    await task
            raise RuntimeError(timeout_message) from exc

    def _build_scope(self, request: Request) -> dict[str, Any]:
        headers = [
            (
                k.lower().encode("ascii"),
                v.encode("latin-1"),
            )
            for k, v in request.headers.list()
        ]

        raw_path = self._get_raw_path_bytes(request)
        query_string = self._get_query_string_bytes(request)
        server_port = request.url.port or DEFAULT_PORTS.get(
            request.url.protocol[:-1],
            80,
        )

        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {
                "version": "3.0",
                "spec_version": "2.4",
            },
            "http_version": self.http_version,
            "method": request.method.upper(),
            "scheme": request.url.protocol[:-1],
            "path": request.url.pathname or "/",
            "query_string": query_string,
            "root_path": self.root_path,
            "headers": headers,
            "client": self.client,
            "server": (
                request.url.hostname,
                server_port,
            ),
        }

        if raw_path is not None:
            scope["raw_path"] = raw_path

        if self._lifespan_supported:
            scope["state"] = self._lifespan_state.copy()

        return scope

    def _raise_if_lifespan_task_exited(
        self,
    ) -> None:
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

    async def _run_lifespan(
        self,
    ) -> None:
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

            async def send(
                message: dict[str, Any],
            ) -> None:
                await send_queue.put(message)

            scope = {
                "type": "lifespan",
                "asgi": {
                    "version": "3.0",
                    "spec_version": "2.0",
                },
                "state": state,
            }

            task = asyncio.create_task(self.app(scope, receive, send))
            session = _LifespanSession(
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

    async def ahandle(self, request: Request) -> Response:
        await self._run_lifespan()
        self._raise_if_lifespan_task_exited()

        scope = self._build_scope(request)
        request_body = _RequestBodySource(self._iter_request_body(request))

        response_started = asyncio.Event()
        response_complete = asyncio.Event()
        disconnect_event = asyncio.Event()

        response_status: int | None = None
        response_headers: list[tuple[str, str]] | None = None
        body_queue: asyncio.Queue[_QueuedBodyChunk | BaseException | None] = asyncio.Queue()
        app_error: BaseException | None = None

        receive_lock = asyncio.Lock()
        send_lock = asyncio.Lock()

        async def receive() -> dict[str, Any]:
            async with receive_lock:
                if response_complete.is_set() or disconnect_event.is_set():
                    return {"type": "http.disconnect"}

                if not request_body.done:
                    return await request_body.next_event()

            waiter1 = asyncio.create_task(response_complete.wait())
            waiter2 = asyncio.create_task(disconnect_event.wait())
            try:
                await asyncio.wait(
                    {waiter1, waiter2},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                waiter1.cancel()
                waiter2.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter1
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter2

            return {"type": "http.disconnect"}

        async def send(
            message: dict[str, Any],
        ) -> None:
            nonlocal response_status, response_headers

            msg_type = message["type"]

            async with send_lock:
                if response_complete.is_set():
                    return

                if disconnect_event.is_set():
                    raise OSError("Connection closed")

                if msg_type == "http.response.start":
                    if response_started.is_set():
                        raise RuntimeError("ASGI application sent multiple http.response.start messages")

                    if bool(
                        message.get(
                            "trailers",
                            False,
                        )
                    ):
                        raise NotImplementedError("ASGI response trailers are not supported by AsgiHandler")

                    response_status = int(message["status"])
                    raw_headers = message.get(
                        "headers",
                        [],
                    )
                    response_headers = [
                        (
                            bytes(k).decode("ascii"),
                            bytes(v).decode("latin-1"),
                        )
                        for k, v in raw_headers
                    ]
                    response_started.set()
                    return

                if msg_type == "http.response.body":
                    if not response_started.is_set():
                        raise RuntimeError("ASGI application sent http.response.body before http.response.start")

                    body = bytes(message.get("body", b""))
                    more_body = bool(
                        message.get(
                            "more_body",
                            False,
                        )
                    )
                    await body_queue.put(
                        _QueuedBodyChunk(
                            body=body,
                            more_body=more_body,
                        )
                    )

                    if not more_body:
                        response_complete.set()
                        await body_queue.put(None)
                    return

                if msg_type == "http.response.trailers":
                    raise NotImplementedError("ASGI response trailers are not supported by AsgiHandler")

                raise RuntimeError(f"Unsupported ASGI send message type: {msg_type!r}")

        async def run_app() -> None:
            nonlocal app_error
            try:
                await self.app(scope, receive, send)

                if not response_started.is_set():
                    raise RuntimeError("ASGI application returned without sending http.response.start")

                if not response_complete.is_set():
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"",
                            "more_body": False,
                        }
                    )
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                app_error = exc
                if not response_started.is_set():
                    response_started.set()
                    return

                if not response_complete.is_set():
                    await body_queue.put(exc)
                    response_complete.set()
                    await body_queue.put(None)
                    return

                raise
            finally:
                with contextlib.suppress(Exception):
                    await request_body.aclose()

        app_task = asyncio.create_task(run_app())

        await response_started.wait()

        if response_status is None or response_headers is None:
            with contextlib.suppress(asyncio.CancelledError):
                await app_task
            assert app_error is not None
            raise app_error

        return Response(
            status=response_status,
            headers=response_headers,
            content=_ResponseStream(
                body_queue=body_queue,
                app_task=app_task,
                disconnect_event=disconnect_event,
            ),
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
