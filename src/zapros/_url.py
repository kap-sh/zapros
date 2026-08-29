from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Union, cast
from urllib.parse import urlencode

if TYPE_CHECKING:
    from ada_url import URL as _BaseURL, URLSearchParams as URLSearchParams
else:
    try:
        from ada_url import URL as _BaseURL, URLSearchParams as URLSearchParams
    except ImportError:
        from pywhatwgurl import URL as _BaseURL, URLSearchParams as URLSearchParams

__all__ = ["URL", "URLSearchParams", "QueryParams", "encode_search_params", "iter_search_params"]

QueryParams = Union[
    str,
    Iterable[Sequence[str]],
    Mapping[str, Union[str, Sequence[str]]],
    URLSearchParams,
]


def iter_search_params(params: QueryParams | None) -> Iterator[tuple[str, str]]:
    """Yield key-value pairs from any accepted query-parameter value."""
    match params:
        case None:
            return
        case str():
            yield from URLSearchParams(params).items()
        case URLSearchParams():
            yield from params.items()
        case Mapping():
            mapping = cast(Mapping[str, Union[str, Sequence[str]]], params)
            for key, values in mapping.items():
                match values:
                    case str():
                        yield key, values
                    case _:
                        for value in values:
                            yield key, value
        case _:
            for key, value in params:
                yield key, value


def encode_search_params(params: QueryParams | None) -> str:
    """Serialize query parameters to an ``application/x-www-form-urlencoded`` string."""
    return urlencode(list(iter_search_params(params)))


class URL(_BaseURL):
    """``ada_url.URL`` with the accessors the rest of zapros relies on."""

    @property
    def search_params(self) -> URLSearchParams:
        """The query string as URLSearchParams."""
        return URLSearchParams(self.search)

    def to_string(self) -> str:
        return self.href
