from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

import pytest

from zapros._async_pool import AsyncConnPool, AsyncPoolConnection


@dataclass
class FakeConn(AsyncPoolConnection):
    id: int
    reusable: bool = True
    _closed: bool = False
    close_calls: int = 0

    @property
    def is_closed(self) -> bool:
        return self._closed

    def can_handle_request(self) -> bool:
        return self.reusable and not self._closed

    async def close(self) -> None:
        self.close_calls += 1
        self._closed = True


@pytest.mark.asyncio
async def test_pool_stress() -> None:
    MAX_PER_HOST = 4
    HOSTS: list[tuple[str, str, int]] = [
        ("https", "a.example.com", 443),
        ("https", "b.example.com", 443),
        ("https", "c.example.com", 443),
    ]

    pool = AsyncConnPool(
        max_connections_per_host=MAX_PER_HOST,
        max_idle_per_host=3,
        max_idle_seconds=0.05,
    )

    rng = random.Random(0)
    created: list[FakeConn] = []
    in_flight: dict[tuple[str, str, int], int] = {k: 0 for k in HOSTS}
    max_seen: dict[tuple[str, str, int], int] = {k: 0 for k in HOSTS}

    async def worker() -> None:
        for _ in range(50):
            key = rng.choice(HOSTS)
            conn = await pool.acquire(key)
            if conn is None:
                conn = FakeConn(id=len(created), reusable=rng.random() < 0.9)
                created.append(conn)

            in_flight[key] += 1
            max_seen[key] = max(max_seen[key], in_flight[key])

            await asyncio.sleep(rng.uniform(0.0005, 0.003))

            in_flight[key] -= 1
            await pool.release(key, conn, reuse=conn.can_handle_request())

    await asyncio.gather(*(worker() for _ in range(200)))

    # Per-host limit was respected throughout.
    for key, peak in max_seen.items():
        assert peak <= MAX_PER_HOST, f"{key}: peak {peak} > limit {MAX_PER_HOST}"

    # No leaked acquires.
    assert all(v == 0 for v in in_flight.values())

    # Pool drains cleanly and never double-closes.
    await pool.close_all()
    assert pool._states == {}  # type: ignore[reportPrivateUsage]
    for c in created:
        assert c.close_calls <= 1, f"conn {c.id} closed {c.close_calls} times"
