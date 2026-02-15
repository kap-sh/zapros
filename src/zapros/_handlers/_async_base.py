from __future__ import annotations

from abc import abstractmethod
from typing import (
    Callable,
    Protocol,
    runtime_checkable,
)

from .._models import Request, Response


@runtime_checkable
class AsyncBaseHandler(Protocol):
    @abstractmethod
    async def ahandle(self, request: Request) -> Response:
        raise NotImplementedError()

    async def aclose(self) -> None:
        pass

    def wrap_with_async_middleware(
        self,
        factory: Callable[
            [AsyncBaseHandler],
            AsyncBaseMiddleware,
        ],
    ) -> AsyncBaseMiddleware:
        return factory(self)


@runtime_checkable
class AsyncBaseMiddleware(AsyncBaseHandler, Protocol):
    async_next: AsyncBaseHandler
