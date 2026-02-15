# pyright: reportUnknownVariableType=false
from __future__ import annotations

import asyncio
from collections.abc import (
    AsyncIterable as ABCAsyncIterable,
)
from typing import Any, AsyncIterator

from .._errors import (
    ConnectionError,
    ConnectTimeoutError,
    ReadTimeoutError,
    WriteTimeoutError,
)
from .._models import (
    AsyncClosableStream,
    Request,
    Response,
)
from ._async_base import (
    AsyncBaseMiddleware,
)


def _deadline_after(
    timeout: float | None,
) -> float | None:
    if timeout is None:
        return None
    return asyncio.get_running_loop().time() + timeout


def _remaining_time(
    deadline: float | None,
) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - asyncio.get_running_loop().time()
    return max(0.0, remaining)


def _combine_timeouts(
    *timeouts: float | None,
) -> float | None:
    values = [t for t in timeouts if t is not None]
    if not values:
        return None
    return min(values)


def _is_async_iterable(
    value: object,
) -> bool:
    return hasattr(value, "__aiter__")


def _js_error_name(
    exc: BaseException,
) -> str | None:
    name = getattr(exc, "name", None)
    if isinstance(name, str):
        return name

    js_error = getattr(exc, "js_error", None)
    if js_error is not None:
        js_name = getattr(js_error, "name", None)
        if isinstance(js_name, str):
            return js_name

    return None


async def _await_with_timeout(
    awaitable: Any,
    timeout: float | None,
) -> Any:
    if timeout is None:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout=timeout)


class _JSTimeoutAbort:
    def __init__(self, timeout: float | None) -> None:
        self._controller = AbortController.new()  # type: ignore
        self._timeout_id: Any | None = None

        if timeout is not None:
            timeout_ms = max(0, int(timeout * 1000))
            self._timeout_id = setTimeout(
                lambda: self._controller.abort(),  # type: ignore
                timeout_ms,
            )

    @property
    def signal(self) -> Any:
        return self._controller.signal  # type: ignore

    def abort(self) -> None:
        try:
            self._controller.abort()  # type: ignore
        except Exception:
            pass

    def clear(self) -> None:
        if self._timeout_id is not None:
            clearTimeout(self._timeout_id)
            self._timeout_id = None


try:
    from js import (  # type: ignore
        AbortController,
        Object,
        clearTimeout,
        fetch,
        setTimeout,
    )
    from pyodide.ffi import to_js  # type: ignore

    class PyodideAsyncClosableStream(AsyncClosableStream):  # type: ignore[reportRedeclaration]
        def __init__(
            self,
            js_response: Any,
            *,
            read_timeout: float | None = None,
            total_deadline: float | None = None,
            total_abort: _JSTimeoutAbort | None = None,
        ) -> None:
            self._js_response = js_response
            self._reader = js_response.body.getReader() if js_response.body is not None else None
            self._read_timeout = read_timeout
            self._total_deadline = total_deadline
            self._total_abort = total_abort
            self._closed = False

        def __aiter__(
            self,
        ) -> AsyncIterator[bytes]:
            return self

        def _next_read_timeout(
            self,
        ) -> float | None:
            total_remaining = _remaining_time(self._total_deadline)
            if total_remaining == 0:
                return 0.0
            return _combine_timeouts(
                self._read_timeout,
                total_remaining,
            )

        async def __anext__(
            self,
        ) -> bytes:
            if self._closed:
                raise StopAsyncIteration

            if self._reader is None:
                await self.aclose()
                raise StopAsyncIteration

            try:
                result = await _await_with_timeout(
                    self._reader.read(),
                    self._next_read_timeout(),
                )

                if result.done:
                    await self.aclose()
                    raise StopAsyncIteration

                return bytes(result.value.to_py())

            except asyncio.TimeoutError as e:
                await self.aclose()
                raise ReadTimeoutError("Read operation timed out") from e
            except Exception:
                await self.aclose()
                raise

        async def aclose(self) -> None:
            if self._closed:
                return

            self._closed = True

            try:
                if self._reader is not None:
                    await self._reader.cancel()
            except Exception:
                pass
            finally:
                if self._total_abort is not None:
                    self._total_abort.clear()

    class AsyncPyodideHandler(AsyncBaseMiddleware):  # type: ignore[reportRedeclaration]
        def __init__(
            self,
            *,
            total_timeout: float | None = None,
            connect_timeout: float | None = None,
            read_timeout: float | None = None,
            write_timeout: float | None = None,
        ) -> None:
            self.total_timeout = total_timeout
            self.connect_timeout = connect_timeout
            self.read_timeout = read_timeout
            self.write_timeout = write_timeout

        def _resolve_timeouts(
            self,
            request: Request,
        ) -> tuple[
            float | None,
            float | None,
            float | None,
            float | None,
        ]:
            timeouts_context = request.context.get("timeouts", {})

            req_total = timeouts_context.get("total")
            req_connect = timeouts_context.get("connect")
            req_read = timeouts_context.get("read")
            req_write = timeouts_context.get("write")

            total_timeout = req_total if req_total is not None else self.total_timeout
            connect_timeout = req_connect if req_connect is not None else self.connect_timeout
            read_timeout = req_read if req_read is not None else self.read_timeout
            write_timeout = req_write if req_write is not None else self.write_timeout

            return (
                total_timeout,
                connect_timeout,
                read_timeout,
                write_timeout,
            )

        async def _buffer_async_body(
            self,
            body: ABCAsyncIterable[bytes],
            *,
            write_timeout: float | None,
            total_deadline: float | None,
        ) -> bytes:
            chunks: list[bytes] = []
            iterator = body.__aiter__()

            while True:
                next_timeout = _combine_timeouts(
                    write_timeout,
                    _remaining_time(total_deadline),
                )
                try:
                    chunk = await _await_with_timeout(
                        iterator.__anext__(),
                        next_timeout,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as e:
                    raise WriteTimeoutError("Write operation timed out") from e

                chunks.append(bytes(chunk))

            return b"".join(chunks)

        def _build_headers(self, js_response: Any) -> list[tuple[str, str]]:
            headers_list: list[tuple[str, str]] = []
            entries_iterator = js_response.headers.entries()

            while True:
                entry = entries_iterator.next()
                if entry.done:
                    break
                key, value = entry.value.to_py()
                headers_list.append(
                    (
                        str(key),
                        str(value),
                    )
                )

            return headers_list

        async def ahandle(self, request: Request) -> Response:
            (
                total_timeout,
                connect_timeout,
                read_timeout,
                write_timeout,
            ) = self._resolve_timeouts(request)

            total_deadline = _deadline_after(total_timeout)

            body_js = None
            if request.body is not None:
                if isinstance(
                    request.body,
                    (
                        bytes,
                        bytearray,
                        memoryview,
                    ),
                ):
                    body_js = to_js(bytes(request.body))
                elif _is_async_iterable(request.body):
                    buffered = await self._buffer_async_body(
                        request.body,  # type: ignore
                        write_timeout=write_timeout,
                        total_deadline=total_deadline,
                    )
                    body_js = to_js(buffered)
                else:
                    raise NotImplementedError("Sync iterators are not supported by AsyncPyodideHandler")

            total_remaining = _remaining_time(total_deadline)
            fetch_timeout = _combine_timeouts(
                connect_timeout,
                total_remaining,
            )

            total_abort = _JSTimeoutAbort(total_remaining)
            if fetch_timeout == total_remaining:
                fetch_abort = total_abort
            else:
                fetch_abort = _JSTimeoutAbort(fetch_timeout)

            fetch_options: dict[str, Any] = {
                "method": request.method,
                "headers": Object.fromEntries(  # type: ignore
                    to_js([[k, v] for k, v in request.headers.list()])  # type: ignore
                ),
                "signal": fetch_abort.signal,
            }

            if body_js is not None:
                fetch_options["body"] = body_js

            fetch_options_js = to_js(
                fetch_options,
                dict_converter=Object.fromEntries,  # type: ignore
            )

            try:
                js_response = await fetch(
                    str(request.url),
                    fetch_options_js,
                )  # type: ignore
            except Exception as e:
                fetch_abort.clear()
                if fetch_abort is not total_abort:
                    total_abort.clear()

                error_name = _js_error_name(e)
                if error_name == "AbortError":
                    raise ConnectTimeoutError(f"Network request failed: {e}") from e
                if error_name in (
                    "TypeError",
                    "NetworkError",
                ):
                    raise ConnectionError(f"Network request failed: {e}") from e
                raise
            else:
                if fetch_abort is not total_abort:
                    fetch_abort.clear()

            headers_list = self._build_headers(js_response)
            status = int(js_response.status)  # type: ignore

            stream = PyodideAsyncClosableStream(
                js_response,
                read_timeout=read_timeout,
                total_deadline=total_deadline,
                total_abort=total_abort,
            )

            return Response(
                status=status,
                headers=headers_list,
                content=stream,
            )

        async def aclose(self) -> None:
            pass

except ImportError:
    # If the js module is not available, we are likely not running in Pyodide.
    # In that case, we can define a dummy AsyncPyodideHandler that raises an error if used.

    class PyodideAsyncClosableStream(AsyncClosableStream):
        def __init__(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            raise RuntimeError("PyodideAsyncClosableStream can only be used in a Pyodide environment")

        def __aiter__(
            self,
        ) -> AsyncIterator[bytes]:
            raise RuntimeError("PyodideAsyncClosableStream can only be used in a Pyodide environment")

        async def __anext__(
            self,
        ) -> bytes:
            raise RuntimeError("PyodideAsyncClosableStream can only be used in a Pyodide environment")

        async def aclose(self) -> None:
            pass

    class AsyncPyodideHandler(AsyncBaseMiddleware):
        async def ahandle(self, request: Request) -> Response:
            raise RuntimeError("AsyncPyodideHandler can only be used in a Pyodide environment")

        async def aclose(self) -> None:
            pass
