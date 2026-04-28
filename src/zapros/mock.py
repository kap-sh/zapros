from types import TracebackType
from unittest.mock import patch

from zapros import (
    AsyncStdNetworkHandler,
    StdNetworkHandler,
)

from ._handlers._mock import (
    Mock,
    MockHandler,  # type: ignore[reportDeprecated]
    MockMiddleware,
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
    "MockMiddleware",
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
    """Context manager that intercepts HTTP requests and routes them to mock responses.

    Patches both the synchronous and asynchronous network handlers
    (``StdNetworkHandler.handle`` and ``AsyncStdNetworkHandler.ahandle``) so that
    any HTTP traffic made within the ``with`` block is dispatched to a
    :class:`MockRouter` instead of hitting the network. The router is yielded
    from ``__enter__``, allowing the caller to register expected requests and
    canned responses inline.

    On clean exit (no exception propagating through the block), the router's
    ``verify()`` method is called to assert that all registered expectations
    were met. The router is then reset regardless of exit status, so the
    instance can be reused across multiple ``with`` blocks without leaking
    state.

    Args:
        mock_handler: The middleware used to intercept and respond to requests.
            If omitted, a fresh ``MockMiddleware`` wrapping a new ``MockRouter``
            is created. Pass an explicit handler when you need to share routing
            state across contexts or customize middleware behavior.

    Raises:
        AssertionError: If the block exits without an exception but the
            router's expectations were not satisfied (raised by
            ``router.verify()``).

    Example:
        >>> with mock_http() as router:
        ...     router.add(Mock.given(path("/api")).respond(Response(status=200)))
        ...     response = client.get("https://api.example.com/api")
        ...     assert response.status == 200
    """

    def __init__(
        self,
        mock_handler: MockMiddleware | None = None,
    ) -> None:
        self._mock_handler = mock_handler if mock_handler is not None else MockMiddleware(router=MockRouter())
        self._router = self._mock_handler.router  # type: ignore

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
