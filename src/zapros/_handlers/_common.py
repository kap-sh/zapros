import time

from zapros._errors import (
    AsyncSyncMismatchError,
)
from zapros._handlers._async_base import (
    AsyncBaseHandler,
)
from zapros._handlers._sync_base import (
    BaseHandler,
)
from zapros._models import Request


def min_with_optionals(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def remaining_timeout(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return deadline - time.monotonic()


def resolve_timeouts(
    request: Request,
    *,
    total_timeout: float | None,
    connect_timeout: float | None,
    read_timeout: float | None,
    write_timeout: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return (total, connect, read, write) timeouts.

    Per-request values from request.context["timeouts"] take priority over
    handler defaults.
    """
    timeouts_context = request.context.get("timeouts", {})
    req_total = timeouts_context.get("total")
    req_connect = timeouts_context.get("connect")
    req_read = timeouts_context.get("read")
    req_write = timeouts_context.get("write")
    return (
        req_total if req_total is not None else total_timeout,
        req_connect if req_connect is not None else connect_timeout,
        req_read if req_read is not None else read_timeout,
        req_write if req_write is not None else write_timeout,
    )


def ensure_async_handler(
    handler: AsyncBaseHandler | BaseHandler,
) -> AsyncBaseHandler:
    if isinstance(handler, AsyncBaseHandler):
        return handler
    raise AsyncSyncMismatchError("Handler was expected to be an AsyncBaseHandler, but it is not.")


def ensure_sync_handler(
    handler: AsyncBaseHandler | BaseHandler,
) -> BaseHandler:
    if isinstance(handler, BaseHandler):
        return handler
    raise AsyncSyncMismatchError("Handler was expected to be a BaseHandler, but it is not.")
