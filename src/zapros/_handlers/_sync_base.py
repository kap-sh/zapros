from __future__ import annotations

from abc import abstractmethod
from typing import (
    Callable,
    Protocol,
    runtime_checkable,
)

from .._models import Request, Response


@runtime_checkable
class BaseHandler(Protocol):
    @abstractmethod
    def handle(self, request: Request) -> Response:
        raise NotImplementedError()

    def close(self) -> None:
        return None

    def wrap_with_middleware(
        self,
        factory: Callable[
            [BaseHandler],
            BaseMiddleware,
        ],
    ) -> BaseMiddleware:
        return factory(self)


@runtime_checkable
class BaseMiddleware(BaseHandler, Protocol):
    next: BaseHandler
