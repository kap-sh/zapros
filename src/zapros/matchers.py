import json as json_module
from abc import abstractmethod
from typing import (
    Any,
    Callable,
    Protocol,
    runtime_checkable,
)

from zapros._models import Request

__all__ = [
    "AndMatcher",
    "HeaderMatcher",
    "HostMatcher",
    "JsonMatcher",
    "Matcher",
    "MethodMatcher",
    "NotMatcher",
    "OrMatcher",
    "PathMatcher",
    "QueryMatcher",
    "and_",
    "header",
    "host",
    "json",
    "method",
    "not_",
    "or_",
    "path",
    "query",
]


@runtime_checkable
class Matcher(Protocol):
    @abstractmethod
    def match(self, request: Request) -> bool:
        raise NotImplementedError

    def and_(self, other: "Matcher") -> "AndMatcher":
        return AndMatcher(self, other)

    def or_(self, other: "Matcher") -> "OrMatcher":
        return OrMatcher(self, other)

    def method(self, method: str) -> "AndMatcher":
        return AndMatcher(self, MethodMatcher(method))

    def path(self, path: str) -> "AndMatcher":
        return AndMatcher(self, PathMatcher(path))

    def host(self, host: str) -> "AndMatcher":
        return AndMatcher(self, HostMatcher(host))

    def header(self, name: str, value: str) -> "AndMatcher":
        return AndMatcher(
            self,
            HeaderMatcher(name, value),
        )

    def query(self, **params: str) -> "AndMatcher":
        return AndMatcher(self, QueryMatcher(**params))

    def json(
        self,
        predicate: Callable[[Any], bool],
    ) -> "AndMatcher":
        return AndMatcher(self, JsonMatcher(predicate))


class AndMatcher(Matcher):
    def __init__(self, *matchers: Matcher) -> None:
        self.matchers = matchers

    def match(self, request: Request) -> bool:
        return all(m.match(request) for m in self.matchers)


class OrMatcher(Matcher):
    def __init__(self, *matchers: Matcher) -> None:
        self.matchers = matchers

    def match(self, request: Request) -> bool:
        return any(m.match(request) for m in self.matchers)


class MethodMatcher(Matcher):
    def __init__(self, method: str) -> None:
        self._method = method.upper()

    def match(self, request: Request) -> bool:
        return request.method.upper() == self._method


class PathMatcher(Matcher):
    def __init__(self, path: str) -> None:
        self._path = path

    def match(self, request: Request) -> bool:
        return request.url.pathname == self._path


class HostMatcher(Matcher):
    def __init__(self, host: str) -> None:
        self._host = host

    def match(self, request: Request) -> bool:
        return request.url.hostname == self._host


class HeaderMatcher(Matcher):
    def __init__(self, name: str, value: str) -> None:
        self._name = name
        self._value = value

    def match(self, request: Request) -> bool:
        return request.headers.get(self._name) == self._value


class QueryMatcher(Matcher):
    def __init__(self, **params: str) -> None:
        self._params = params

    def match(self, request: Request) -> bool:
        query_dict = request.url.search_params
        return all(query_dict.get(key) == value for key, value in self._params.items())


class JsonMatcher(Matcher):
    def __init__(
        self,
        predicate: Callable[[Any], bool],
    ) -> None:
        self._predicate = predicate

    def match(self, request: Request) -> bool:
        if not isinstance(request.body, bytes):
            return False
        try:
            data = json_module.loads(request.body.decode("utf-8"))
            return self._predicate(data)
        except (
            ValueError,
            UnicodeDecodeError,
        ):
            return False


class NotMatcher(Matcher):
    def __init__(self, matcher: Matcher) -> None:
        self.matcher = matcher

    def match(self, request: Request) -> bool:
        return not self.matcher.match(request)


def and_(
    *matchers: Matcher,
) -> AndMatcher:
    return AndMatcher(*matchers)


def or_(
    *matchers: Matcher,
) -> OrMatcher:
    return OrMatcher(*matchers)


def not_(
    matcher: Matcher,
) -> NotMatcher:
    return NotMatcher(matcher)


def method(
    method: str,
) -> MethodMatcher:
    return MethodMatcher(method)


def path(path: str) -> PathMatcher:
    return PathMatcher(path)


def host(host: str) -> HostMatcher:
    return HostMatcher(host)


def header(name: str, value: str) -> HeaderMatcher:
    return HeaderMatcher(name, value)


def query(
    **params: str,
) -> QueryMatcher:
    return QueryMatcher(**params)


def json(
    predicate: Callable[[Any], bool],
) -> JsonMatcher:
    return JsonMatcher(predicate)
