from zapros._errors import (
    AsyncSyncMismatchError,
)
from zapros._handlers._async_base import (
    AsyncBaseHandler,
)
from zapros._handlers._sync_base import (
    BaseHandler,
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
