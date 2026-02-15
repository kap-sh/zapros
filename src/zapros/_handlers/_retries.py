from __future__ import annotations

import asyncio
import random
import time
from abc import abstractmethod
from typing import (
    Protocol,
    cast,
    runtime_checkable,
)

from zapros._handlers._common import (
    ensure_async_handler,
    ensure_sync_handler,
)

from .._errors import (
    ConnectionError,
    TimeoutError,
)
from .._models import Request, Response
from ._async_base import (
    AsyncBaseMiddleware,
)
from ._sync_base import BaseHandler

DEFAULT_RETRY_STATUS_CODES = frozenset(
    {
        429,
        500,
        502,
        503,
        504,
    }
)
SAFE_RETRY_METHODS = frozenset(
    {
        "GET",
        "HEAD",
        "PUT",
        "DELETE",
        "OPTIONS",
        "TRACE",
    }
)
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_BACKOFF_MAX = 60.0
DEFAULT_BACKOFF_JITTER = 1.0


@runtime_checkable
class RetryPolicy(Protocol):
    @abstractmethod
    def should_retry(
        self,
        *,
        request: Request,
        response: Response | None,
        error: Exception | None,
        attempt: int,
    ) -> bool:
        raise NotImplementedError()


class DefaultRetryPolicy:
    def __init__(
        self,
        *,
        retry_status_codes: frozenset[int] | None = None,
        safe_methods: frozenset[str] | None = None,
    ) -> None:
        self._retry_status_codes = retry_status_codes or DEFAULT_RETRY_STATUS_CODES
        self._safe_methods = safe_methods or SAFE_RETRY_METHODS

    def should_retry(
        self,
        *,
        request: Request,
        response: Response | None,
        error: Exception | None,
        attempt: int,
    ) -> bool:
        if error is not None:
            if self._is_pre_transmission_error(error):
                return True
            if request.method not in self._safe_methods:
                return False
            if request.is_replayable() and self._is_retryable_exception(error):
                return True
            return False

        if response is not None:
            if request.method not in self._safe_methods:
                return False
            if not request.is_replayable():
                return False
            return response.status in self._retry_status_codes

        return False

    def _is_pre_transmission_error(self, exc: Exception) -> bool:
        exc_name = type(exc).__name__
        pre_transmission_patterns = (
            "ConnectionError",
            "ConnectionRefusedError",
            "ConnectTimeout",
            "ConnectError",
            "DNSError",
            "NameResolutionError",
            "SSLError",
            "CertificateError",
        )
        return any(pattern in exc_name for pattern in pre_transmission_patterns)

    def _is_retryable_exception(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                TimeoutError,
                ConnectionError,
            ),
        )


def _calculate_backoff(
    attempt: int,
    backoff_factor: float,
    backoff_max: float,
    backoff_jitter: float,
) -> float:
    base_delay = backoff_factor * (2**attempt)
    delay = min(base_delay, backoff_max)

    if backoff_jitter > 0:
        jitter_range = delay * backoff_jitter
        delay = delay - jitter_range + (random.random() * 2 * jitter_range)
        delay = max(0.0, delay)

    return delay


class RetryHandler(AsyncBaseMiddleware, BaseHandler):
    def __init__(
        self,
        next_handler: AsyncBaseMiddleware | BaseHandler,
        *,
        policy: RetryPolicy | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
        backoff_jitter: float = DEFAULT_BACKOFF_JITTER,
    ) -> None:
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseMiddleware,
            next_handler,
        )
        self._policy = policy if policy is not None else DefaultRetryPolicy()
        self._max_attempts = max_attempts
        self._backoff_factor = backoff_factor
        self._backoff_max = backoff_max
        self._backoff_jitter = backoff_jitter

    async def ahandle(self, request: Request) -> Response:
        handler = ensure_async_handler(self.async_next)

        attempt = 0
        while attempt < self._max_attempts:
            try:
                response = await handler.ahandle(request)

                if not self._policy.should_retry(
                    request=request,
                    response=response,
                    error=None,
                    attempt=attempt,
                ):
                    return response

                if attempt + 1 >= self._max_attempts:
                    return response

                await response.aclose()

                wait = _calculate_backoff(
                    attempt,
                    self._backoff_factor,
                    self._backoff_max,
                    self._backoff_jitter,
                )
                if wait > 0:
                    await asyncio.sleep(wait)

                attempt += 1

            except Exception as exc:
                if not self._policy.should_retry(
                    request=request,
                    response=None,
                    error=exc,
                    attempt=attempt,
                ):
                    raise

                if attempt + 1 >= self._max_attempts:
                    raise

                wait = _calculate_backoff(
                    attempt,
                    self._backoff_factor,
                    self._backoff_max,
                    self._backoff_jitter,
                )
                if wait > 0:
                    await asyncio.sleep(wait)

                attempt += 1

        raise RuntimeError("Unreachable code")

    def handle(self, request: Request) -> Response:
        handler = ensure_sync_handler(self.next)

        attempt = 0
        while attempt < self._max_attempts:
            try:
                response = handler.handle(request)

                if not self._policy.should_retry(
                    request=request,
                    response=response,
                    error=None,
                    attempt=attempt,
                ):
                    return response

                if attempt + 1 >= self._max_attempts:
                    return response

                response.close()

                wait = _calculate_backoff(
                    attempt,
                    self._backoff_factor,
                    self._backoff_max,
                    self._backoff_jitter,
                )
                if wait > 0:
                    time.sleep(wait)

                attempt += 1

            except Exception as exc:
                if not self._policy.should_retry(
                    request=request,
                    response=None,
                    error=exc,
                    attempt=attempt,
                ):
                    raise

                if attempt + 1 >= self._max_attempts:
                    raise

                wait = _calculate_backoff(
                    attempt,
                    self._backoff_factor,
                    self._backoff_max,
                    self._backoff_jitter,
                )
                if wait > 0:
                    time.sleep(wait)

                attempt += 1

        raise RuntimeError("Unreachable code")
