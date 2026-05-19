from __future__ import annotations

import asyncio
import base64
import threading
from types import TracebackType
from typing import Optional

from pywhatwgurl import URL

from zapros._errors import ConnectionError as _ConnError, TotalTimeoutError
from zapros._handlers._common import remaining_timeout
from zapros._headers import Connection

from ..._models import Headers, Request


class BrokenConnectionError(ConnectionError):
    """
    Raised when a connection from the pool which was expected to be alive is
    found to be closed or otherwise unusable. This can happen when the server
    closes an idle connection, and the client tries to reuse it from the pool.
    When this happens, the connection should not be returned to the pool, and
    the request should be retried with a new connection.
    This should be raised by the connection's send_request() when the first operation on the connection fails.
    """

    pass


class StreamLimiter:
    """
    Thread-safe limiter for concurrent HTTP/2 streams.

    The limit can be updated at runtime to track peer-advertised
    SETTINGS_MAX_CONCURRENT_STREAMS changes. When the limit is lowered,
    existing streams are allowed to complete; new acquirers simply wait
    until active count drops below the new limit.
    """

    def __init__(self, limit: int):
        if limit < 0:
            raise ValueError("limit must be non-negative")
        self._cond = threading.Condition()
        self._limit = limit
        self._active = 0
        self._failed = False

    def acquire(self) -> None:
        with self._cond:
            while not self._failed and self._active >= self._limit:
                self._cond.wait()
            if self._failed:
                raise _ConnError("HTTP/2 connection terminated")
            self._active += 1

    def release(self) -> None:
        with self._cond:
            if self._active <= 0:
                raise RuntimeError("release() called without matching acquire()")
            self._active -= 1
            # Only one slot freed — wake a single waiter.
            self._cond.notify()

    def update_limit(self, new_limit: int) -> None:
        """
        Update the concurrent stream limit.

        Raising the limit may unblock multiple waiters at once, so we
        notify_all. Lowering is safe: existing streams complete normally,
        and new acquirers wait until active < new_limit.
        """
        if new_limit < 0:
            raise ValueError("limit must be non-negative")
        with self._cond:
            self._limit = new_limit
            self._cond.notify_all()

    def fail_all(self) -> None:
        """Wake all waiters with ConnectionError and reject future acquires.

        Idempotent. Does not change `_active`; outstanding permits still need
        to be released by their holders.
        """
        with self._cond:
            self._failed = True
            self._cond.notify_all()

    @property
    def active(self) -> int:
        with self._cond:
            return self._active

    @property
    def limit(self) -> int:
        with self._cond:
            return self._limit

    def __enter__(self) -> None:
        self.acquire()

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.release()


class AsyncStreamLimiter:
    """
    Async limiter for concurrent HTTP/2 streams.

    Same semantics as StreamLimiter, but built on asyncio primitives.
    Uses only Condition.wait() (no wait_for) so the pattern translates
    directly to trio.Condition, anyio.Condition, etc.
    """

    def __init__(self, limit: int):
        if limit < 0:
            raise ValueError("limit must be non-negative")
        self._cond = asyncio.Condition()
        self._limit = limit
        self._active = 0
        self._failed = False

    async def acquire(self) -> None:
        async with self._cond:
            while not self._failed and self._active >= self._limit:
                await self._cond.wait()
            if self._failed:
                raise _ConnError("HTTP/2 connection terminated")
            self._active += 1

    async def release(self) -> None:
        async with self._cond:
            if self._active <= 0:
                raise RuntimeError("release() called without matching acquire()")
            self._active -= 1
            self._cond.notify()

    async def update_limit(self, new_limit: int) -> None:
        if new_limit < 0:
            raise ValueError("limit must be non-negative")
        async with self._cond:
            self._limit = new_limit
            self._cond.notify_all()

    async def fail_all(self) -> None:
        """Wake all waiters with ConnectionError and reject future acquires.

        Idempotent. Does not change `_active`; outstanding permits still need
        to be released by their holders.
        """
        async with self._cond:
            self._failed = True
            self._cond.notify_all()

    @property
    def active(self) -> int:
        return self._active

    @property
    def limit(self) -> int:
        return self._limit

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.release()


def remaining_timeout_or_raise(deadline: float | None) -> float | None:
    remaining = remaining_timeout(deadline)
    if remaining is not None and remaining <= 0:
        raise TotalTimeoutError("Operation timed out")
    return remaining


def connection_wants_close(headers: list[tuple[str, str]]) -> bool:
    connection_values = Headers(headers).getall("connection")

    if not connection_values:
        return False

    return Connection.from_field_lines(connection_values).has("close")


def response_has_no_body(method: str, status: int) -> bool:
    if method.upper() == "HEAD":
        return True
    if 100 <= status < 200:
        return True
    if status in (204, 304):
        return True
    return False


def proxy_basic_auth_header(request: Request) -> tuple[str, str] | None:
    proxy_context = request.context.get("network", {}).get("proxy")
    if proxy_context is None:
        return None
    proxy_url_value = proxy_context.get("url")
    if proxy_url_value is None:
        return None
    proxy_url = URL(proxy_url_value) if isinstance(proxy_url_value, str) else proxy_url_value
    if not (proxy_url.username or proxy_url.password):
        return None
    username = proxy_url.username or ""
    password = proxy_url.password or ""
    credentials = f"{username}:{password}".encode("utf-8")
    auth_value = base64.b64encode(credentials).decode("ascii")
    return ("Proxy-Authorization", f"Basic {auth_value}")
