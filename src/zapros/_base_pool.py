from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

PoolKey = tuple[str, str, int] | tuple[str, str, int, str, str, int]


class PoolConnection(Protocol):
    def close(self) -> None: ...

    @property
    def is_closed(self) -> bool: ...

    def can_handle_request(self) -> bool: ...


class AsyncPoolConnection(Protocol):
    async def close(self) -> None: ...

    @property
    def is_closed(self) -> bool: ...

    def can_handle_request(self) -> bool: ...


@dataclass
class IdlePoolConnection:
    conn: PoolConnection
    last_used: float = field(default_factory=time.monotonic)


@dataclass
class AsyncIdlePoolConnection:
    conn: AsyncPoolConnection
    last_used: float = field(default_factory=time.monotonic)
