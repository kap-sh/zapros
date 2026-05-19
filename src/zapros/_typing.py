from collections.abc import Iterator
from typing import Any, AsyncIterator

from typing_extensions import TypeIs


def is_sync_iterator(obj: object) -> TypeIs[Iterator[Any]]:
    return isinstance(obj, Iterator)


def is_async_iterator(obj: object) -> TypeIs[AsyncIterator[Any]]:
    return isinstance(obj, AsyncIterator)
