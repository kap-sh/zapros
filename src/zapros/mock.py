from types import TracebackType
from unittest.mock import patch

from zapros import (
    AsyncStdNetworkHandler,
    StdNetworkHandler,
)

from ._handlers._mock import (
    Mock,
    MockHandler,
    MockRouter,
)
from .matchers import (
    AndMatcher,
    HeaderMatcher,
    HostMatcher,
    JsonMatcher,
    Matcher,
    MethodMatcher,
    NotMatcher,
    OrMatcher,
    PathMatcher,
    QueryMatcher,
    and_,
    header,
    host,
    json,
    method,
    not_,
    or_,
    path,
    query,
)

__all__ = [
    "AndMatcher",
    "HeaderMatcher",
    "HostMatcher",
    "JsonMatcher",
    "Matcher",
    "MethodMatcher",
    "Mock",
    "MockHandler",
    "MockRouter",
    "NotMatcher",
    "OrMatcher",
    "PathMatcher",
    "QueryMatcher",
    "and_",
    "header",
    "host",
    "json",
    "method",
    "mock_http",
    "not_",
    "or_",
    "path",
    "query",
]


class mock_http:
    def __init__(
        self,
        mock_handler: MockHandler | None = None,
    ) -> None:
        self._mock_handler = mock_handler if mock_handler is not None else MockHandler(router=MockRouter())
        self._router = self._mock_handler._router  # type: ignore

        self._std_patch = patch.object(
            StdNetworkHandler,
            "handle",
            self._mock_handler.handle,
        )
        self._async_std_patch = patch.object(
            AsyncStdNetworkHandler,
            "ahandle",
            self._mock_handler.ahandle,
        )
        self._patches = [
            self._std_patch,
            self._async_std_patch,
        ]

    def __enter__(self) -> MockRouter:
        for p in self._patches:
            p.__enter__()
        return self._router

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        for p in reversed(self._patches):
            p.__exit__(
                exc_type,
                exc_val,
                exc_tb,
            )
        if exc_type is None:
            self._router.verify()
        self._router.reset()
