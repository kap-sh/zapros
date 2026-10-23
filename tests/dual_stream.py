from __future__ import annotations


class DualStream:
    """Both a sync and an async iterator, so it's usable in either context."""

    def __init__(self, data: bytes) -> None:
        self._chunks = [data]

    def __iter__(self) -> DualStream:
        return self

    def __next__(self) -> bytes:
        if not self._chunks:
            raise StopIteration
        return self._chunks.pop()

    def __aiter__(self) -> DualStream:
        return self

    async def __anext__(self) -> bytes:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop()
