from __future__ import annotations

from collections.abc import (
    Iterable,
    Iterator,
    Mapping,
)
from typing import (
    Generic,
    MutableMapping,
    Protocol,
    TypeVar,
    cast,
)

_VT = TypeVar("_VT")
_T = TypeVar("_T")
_KT = TypeVar("_KT")
_VT_co = TypeVar("_VT_co", covariant=True)


class SupportsKeysAndGetItem(Protocol[_KT, _VT_co]):
    def keys(self) -> Iterable[_KT]: ...
    def __getitem__(self, __key: _KT, /) -> _VT_co: ...


class CIMultiDict(MutableMapping[str, _VT], Generic[_VT]):
    __slots__ = ("_items", "_index")

    def __init__(
        self,
        arg: Mapping[str, _VT] | Iterable[tuple[str, _VT]] | None = None,
    ) -> None:
        self._items: list[tuple[str, _VT]] = []
        self._index: dict[str, list[int]] = {}

        if arg is not None:
            self.extend(arg)

    @staticmethod
    def _norm_key(key: str) -> str:
        return key.casefold()

    def _reindex(self) -> None:
        index: dict[str, list[int]] = {}
        for i, (key, _) in enumerate(self._items):
            norm: str = self._norm_key(key)
            index.setdefault(norm, []).append(i)
        self._index = index

    def __getitem__(self, key: str) -> _VT:
        norm: str = self._norm_key(key)
        try:
            first_pos: int = self._index[norm][0]
        except KeyError:
            raise KeyError(key) from None
        return self._items[first_pos][1]

    def __setitem__(self, key: str, value: _VT) -> None:
        norm: str = self._norm_key(key)
        self._items = [(k, v) for k, v in self._items if self._norm_key(k) != norm]
        self._items.append((key, value))
        self._reindex()

    def __delitem__(self, key: str) -> None:
        norm: str = self._norm_key(key)
        items: list[tuple[str, _VT]] = [(k, v) for k, v in self._items if self._norm_key(k) != norm]
        if len(items) == len(self._items):
            raise KeyError(key)
        self._items = items
        self._reindex()

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._norm_key(key) in self._index

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for key, _ in self._items:
            norm: str = self._norm_key(key)
            if norm not in seen:
                seen.add(norm)
                yield key

    def __len__(self) -> int:
        return len(self._index)

    def __repr__(self) -> str:
        return f"<CIMultiDict({self._items!r})>"

    def getall(self, key: str) -> list[_VT]:
        norm: str = self._norm_key(key)
        positions: list[int] | None = self._index.get(norm)
        if not positions:
            return []
        return [self._items[pos][1] for pos in positions]

    def allitems(self) -> Iterator[tuple[str, _VT]]:
        yield from self._items

    def add(self, key: str, value: _VT) -> None:
        pos: int = len(self._items)
        self._items.append((key, value))
        norm: str = self._norm_key(key)
        self._index.setdefault(norm, []).append(pos)

    def extend(
        self,
        arg: SupportsKeysAndGetItem[str, _VT] | Iterable[tuple[str, _VT]],
    ) -> None:
        items: Iterable[tuple[str, _VT]]
        if isinstance(arg, Mapping):
            items = cast(Iterable[tuple[str, _VT]], arg.items())
        elif hasattr(arg, "keys"):
            arg_keyed: SupportsKeysAndGetItem[str, _VT] = cast(
                SupportsKeysAndGetItem[str, _VT],
                arg,
            )
            items = [(k, arg_keyed[k]) for k in arg_keyed.keys()]
        else:
            items = cast(Iterable[tuple[str, _VT]], arg)

        for key, value in items:
            self.add(key, value)

    def popitem(self) -> tuple[str, _VT]:
        if not self._items:
            raise KeyError("popitem(): dictionary is empty")
        key: str
        value: _VT
        key, value = self._items[-1]
        del self[key]
        return key, value

    def copy(self) -> CIMultiDict[_VT]:
        new: CIMultiDict[_VT] = type(self)()
        new._items = self._items.copy()
        new._index = {k: v.copy() for k, v in self._index.items()}
        return new
