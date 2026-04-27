from __future__ import annotations

from typing import (
    Callable,
    cast,
)

import typing_extensions

from zapros._handlers._common import (
    ensure_async_handler,
    ensure_sync_handler,
)
from zapros._handlers._sync_base import (
    BaseHandler,
    BaseMiddleware,
)
from zapros.matchers import Matcher

from .._models import (
    Request,
    Response,
)
from ._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)


class Mock:
    def __init__(self) -> None:
        self.matchers: list[Matcher] = []
        self.calls: list[Request] = []
        self._response: Response | None = None
        self._callback: Callable[[Request], Response] | BaseException | type[BaseException] | None = None
        self._expected_calls: int | None = None
        self._actual_calls: int = 0
        self._name: str | None = None

    @staticmethod
    def given(matcher: Matcher) -> Mock:
        mock = Mock()
        mock.matchers.append(matcher)
        return mock

    def and_(self, matcher: Matcher) -> Mock:
        self.matchers.append(matcher)
        return self

    def mount(self, router: MockRouter) -> Mock:
        router.add(self)
        return self

    def respond(self, response: Response) -> Mock:
        self._response = response
        return self

    def callback(
        self,
        fn: Callable[[Request], Response] | BaseException | type[BaseException],
    ) -> Mock:
        self._callback = fn
        return self

    def expect(self, n: int) -> Mock:
        self._expected_calls = n
        return self

    def once(self) -> Mock:
        return self.expect(1)

    def never(self) -> Mock:
        return self.expect(0)

    def name(self, name: str) -> Mock:
        self._name = name
        return self

    @property
    def called(self) -> bool:
        return bool(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _is_exhausted(self) -> bool:
        return (
            self._expected_calls is not None and self._actual_calls >= self._expected_calls and self._expected_calls > 0
        )

    def matches(self, request: Request) -> bool:
        if self._is_exhausted():
            return False
        return all(m.match(request) for m in self.matchers)

    def handle(self, request: Request) -> Response:
        self.calls.append(request)
        self._actual_calls += 1

        if self._callback:
            if isinstance(
                self._callback,
                BaseException,
            ):
                raise self._callback
            if isinstance(self._callback, type) and issubclass(
                self._callback,
                BaseException,
            ):
                raise self._callback()
            return self._callback(request)  # type: ignore

        if self._response is not None:
            return self._response

        return Response(status=200)

    def verify(self) -> None:
        if self._expected_calls is None:
            return

        if self._actual_calls != self._expected_calls:
            name = self._name or "Mock"
            raise AssertionError(f"{name}: expected {self._expected_calls} calls, got {self._actual_calls}")

    def assert_called(self) -> None:
        if not self.called:
            raise AssertionError(f"{self._name or 'Mock'} was not called")

    def assert_not_called(self) -> None:
        if self.called:
            raise AssertionError(f"{self._name or 'Mock'} was unexpectedly called")

    def assert_called_once(self) -> None:
        if self.call_count != 1:
            raise AssertionError(f"{self._name or 'Mock'} expected 1 call, got {self.call_count}")

    def reset(self) -> None:
        self.calls.clear()
        self._actual_calls = 0


class MockRouter:
    def __init__(self) -> None:
        self.mocks: list[Mock] = []

    def add(self, mock: Mock) -> MockRouter:
        self.mocks.append(mock)
        return self

    def dispatch(self, request: Request) -> Response | None:
        for mock in self.mocks:
            if mock.matches(request):
                return mock.handle(request)
        return None

    def verify(self) -> None:
        for mock in self.mocks:
            mock.verify()

    def reset(self) -> None:
        for mock in self.mocks:
            mock.reset()


class MockMiddleware(AsyncBaseMiddleware, BaseMiddleware):
    def __init__(
        self,
        router: MockRouter,
        next_handler: AsyncBaseHandler | BaseHandler | None = None,
    ) -> None:
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseHandler,
            next_handler,
        )
        self._router = router
        self._fallback = next_handler
        self._passthrough = next_handler is not None

    async def ahandle(self, request: Request) -> Response:  # unasync: generate
        response = self._router.dispatch(request)
        if response is not None:
            return response

        if not self._passthrough:
            raise ValueError(f"No mock matched request: {request.method} {request.url.pathname}")

        handler = ensure_async_handler(self.async_next)
        return await handler.ahandle(request)

    def handle(self, request: Request) -> Response:  # unasync: generated
        response = self._router.dispatch(request)
        if response is not None:
            return response

        if not self._passthrough:
            raise ValueError(f"No mock matched request: {request.method} {request.url.pathname}")

        handler = ensure_sync_handler(self.next)
        return handler.handle(request)

    async def aclose(self) -> None:
        self._router.verify()
        self._router.reset()

    def close(self) -> None:
        self._router.verify()
        self._router.reset()


@typing_extensions.deprecated(
    "MockHandler is deprecated, use MockMiddleware instead. "
    "The name 'Handler' was misleading as this is a middleware, not a terminal handler."
)
class MockHandler(MockMiddleware):
    pass
