import pytest

from zapros._async_pool import AsyncConnPool
from zapros._compat import anysleep


class MockAsyncConnection:
    def __init__(self, conn_id: int, reusable: bool = True, fail_on_close: bool = False):
        self.conn_id = conn_id
        self._closed = False
        self._reusable = reusable
        self._fail_on_close = fail_on_close
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1
        self._closed = True
        if self._fail_on_close:
            raise RuntimeError(f"Connection {self.conn_id} failed to close")
        await anysleep(0)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def can_handle_request(self) -> bool:
        return self._reusable and not self._closed


@pytest.fixture
def pool():
    return AsyncConnPool(
        max_connections_per_host=10,
        max_idle_per_host=5,
        max_idle_seconds=30.0,
    )


async def get_state(pool: AsyncConnPool, key):
    async with pool._lock:
        return pool._states.get(key)


async def test_acquire_with_no_idle_returns_none(pool):
    key = ("http", "example.com", 80)
    conn = await pool.acquire(key)
    assert conn is None


async def test_release_and_reacquire_connection(pool):
    key = ("http", "example.com", 80)
    mock_conn = MockAsyncConnection(conn_id=1)

    await pool.release(key, mock_conn, reuse=True)

    conn = await pool.acquire(key)
    assert conn is mock_conn
    assert conn.close_count == 0


async def test_release_without_reuse_closes_connection(pool):
    key = ("http", "example.com", 80)
    mock_conn = MockAsyncConnection(conn_id=1)

    await pool.release(key, mock_conn, reuse=False)

    conn = await pool.acquire(key)
    assert conn is None
    assert mock_conn.is_closed


async def test_expired_connection_not_reused(pool):
    pool._max_age = 0.1
    key = ("http", "example.com", 80)
    mock_conn = MockAsyncConnection(conn_id=1)

    await pool.release(key, mock_conn, reuse=True)
    await anysleep(0.15)

    conn = await pool.acquire(key)
    assert conn is None
    assert mock_conn.is_closed


async def test_non_reusable_connection_discarded(pool):
    key = ("http", "example.com", 80)
    mock_conn = MockAsyncConnection(conn_id=1, reusable=False)

    await pool.release(key, mock_conn, reuse=True)

    conn = await pool.acquire(key)
    assert conn is None
    assert mock_conn.is_closed


async def test_stale_connections_closed_before_returning_reusable(pool):
    pool._max_age = 0.05
    key = ("http", "example.com", 80)

    reusable_conn = MockAsyncConnection(conn_id=1)
    stale_conn = MockAsyncConnection(conn_id=2, reusable=False)

    await pool.release(key, reusable_conn, reuse=True)
    await pool.release(key, stale_conn, reuse=True)

    acquired = await pool.acquire(key)

    assert acquired is reusable_conn
    assert stale_conn.is_closed
    assert stale_conn.close_count == 1


async def test_max_idle_connections_enforced(pool):
    key = ("http", "example.com", 80)
    connections = [MockAsyncConnection(conn_id=i) for i in range(10)]

    for conn in connections:
        await pool.release(key, conn, reuse=True)

    remaining_conns = []
    for _ in range(10):
        conn = await pool.acquire(key)
        if conn:
            remaining_conns.append(conn)

    assert len(remaining_conns) == pool._max_idle_per_host

    closed_count = sum(1 for c in connections if c.is_closed)
    assert closed_count == 5


#
# async def test_acquire_semaphore_limits_concurrent_connections():
#     pool = AsyncConnPool(max_connections_per_host=2)
#     key = ("http", "example.com", 80)

#     state = await pool._get_state(key)
#     assert state.semaphore._value == 2
#     await pool._release_state_ref(key, state)

#     conn1 = await pool.acquire(key)
#     assert conn1 is None
#     state = await get_state(pool, key)
#     assert state is not None
#     assert state.semaphore._value == 1

#     conn2 = await pool.acquire(key)
#     assert conn2 is None
#     state = await get_state(pool, key)
#     assert state is not None
#     assert state.semaphore._value == 0

#     acquire_task = asyncio.create_task(pool.acquire(key))
#     await sleep(0.01)
#     assert not acquire_task.done()

#     await pool.release_reservation(key)
#     await sleep(0.01)
#     assert acquire_task.done()

#     acquire_task.cancel()


async def test_semaphore_per_key():
    pool = AsyncConnPool(max_connections_per_host=2)
    key1 = ("http", "example.com", 80)
    key2 = ("http", "other.com", 80)

    await pool.acquire(key1)
    await pool.acquire(key1)

    conn = await pool.acquire(key2)
    assert conn is None


async def test_close_all_closes_idle_connections(pool):
    key = ("http", "example.com", 80)
    connections = [MockAsyncConnection(conn_id=i) for i in range(5)]

    for conn in connections:
        await pool.release(key, conn, reuse=True)

    await pool.close_all()

    assert all(conn.is_closed for conn in connections)
    assert pool._closed
    assert len(pool._states) == 0


async def test_acquire_when_closed_raises_error(pool):
    key = ("http", "example.com", 80)
    await pool.close_all()

    with pytest.raises(RuntimeError, match="Pool is closed"):
        await pool.acquire(key)


async def test_release_when_closed_discards_connection(pool):
    key = ("http", "example.com", 80)
    mock_conn = MockAsyncConnection(conn_id=1)

    await pool.close_all()
    await pool.release(key, mock_conn, reuse=True)

    assert mock_conn.is_closed


async def test_close_all_idempotent(pool):
    await pool.close_all()
    await pool.close_all()
    assert pool._closed


async def test_connection_close_failure_handled_gracefully(pool):
    key = ("http", "example.com", 80)
    failing_conn = MockAsyncConnection(conn_id=1, fail_on_close=True)

    await pool.release(key, failing_conn, reuse=False)
    assert failing_conn.close_count == 1


async def test_multiple_keys_isolated(pool):
    key1 = ("http", "example.com", 80)
    key2 = ("https", "example.com", 443)
    key3 = ("http", "other.com", 80)

    conn1 = MockAsyncConnection(conn_id=1)
    conn2 = MockAsyncConnection(conn_id=2)
    conn3 = MockAsyncConnection(conn_id=3)

    await pool.release(key1, conn1, reuse=True)
    await pool.release(key2, conn2, reuse=True)
    await pool.release(key3, conn3, reuse=True)

    acquired1 = await pool.acquire(key1)
    acquired2 = await pool.acquire(key2)
    acquired3 = await pool.acquire(key3)

    assert acquired1 is conn1
    assert acquired2 is conn2
    assert acquired3 is conn3


async def test_lifo_order_for_idle_connections(pool):
    key = ("http", "example.com", 80)
    connections = [MockAsyncConnection(conn_id=i) for i in range(3)]

    for conn in connections:
        await pool.release(key, conn, reuse=True)

    acquired_connections = []
    for _ in range(3):
        conn = await pool.acquire(key)
        if conn:
            acquired_connections.append(conn)

    assert acquired_connections == list(reversed(connections))


#
# async def test_concurrent_acquire_release_stress():
#     pool = AsyncConnPool(max_connections_per_host=20, max_idle_per_host=10)
#     key = ("http", "example.com", 80)

#     async def worker(worker_id: int):
#         for iteration in range(10):
#             conn = await pool.acquire(key)
#             if conn is None:
#                 conn = MockAsyncConnection(conn_id=worker_id * 1000 + iteration)
#             else:
#                 await pool.release_reservation(key)

#             await sleep(0.001)
#             await pool.release(key, conn, reuse=True)

#     tasks = [asyncio.create_task(worker(i)) for i in range(50)]
#     await asyncio.gather(*tasks)

#     await pool.close_all()


async def test_connection_expiry_during_mixed_operations():
    pool = AsyncConnPool(max_connections_per_host=5, max_idle_seconds=0.1)
    key = ("http", "example.com", 80)

    old_conn = MockAsyncConnection(conn_id=1)
    await pool.release(key, old_conn, reuse=True)

    await anysleep(0.15)

    new_conn = MockAsyncConnection(conn_id=2)
    await pool.release(key, new_conn, reuse=True)

    acquired = await pool.acquire(key)
    assert acquired is new_conn

    second_acquired = await pool.acquire(key)
    assert second_acquired is None
    assert old_conn.is_closed


async def test_partial_reusable_connections():
    pool = AsyncConnPool()
    key = ("http", "example.com", 80)

    connections = [
        MockAsyncConnection(conn_id=1, reusable=False),
        MockAsyncConnection(conn_id=2, reusable=True),
        MockAsyncConnection(conn_id=3, reusable=False),
    ]

    for conn in connections:
        await pool.release(key, conn, reuse=True)

    acquired = await pool.acquire(key)
    assert acquired is connections[1]
    assert connections[2].is_closed
    assert not connections[0].is_closed

    second_acquired = await pool.acquire(key)
    assert second_acquired is None
    assert connections[0].is_closed


async def test_semaphore_release_on_acquire_failure(pool):
    key = ("http", "example.com", 80)

    state = await pool._get_state(key)
    await pool._release_state_ref(key, state)

    await pool.close_all()

    try:
        await pool.acquire(key)
    except RuntimeError:
        pass

    assert len(pool._states) == 0


#
# async def test_many_keys_concurrent_operations():
#     pool = AsyncConnPool(max_connections_per_host=5)
#     keys = [("http", f"host{i}.com", 80) for i in range(20)]

#     async def work_on_key(key):
#         for _ in range(5):
#             conn = await pool.acquire(key)
#             if conn is None:
#                 conn = MockAsyncConnection(conn_id=hash(key))
#             else:
#                 await pool.release_reservation(key)

#             await sleep(0.001)
#             await pool.release(key, conn, reuse=True)

#     tasks = [asyncio.create_task(work_on_key(key)) for key in keys]
#     await asyncio.gather(*tasks)

#     await pool.close_all()


async def test_rapid_acquire_release_same_connection():
    pool = AsyncConnPool()
    key = ("http", "example.com", 80)
    conn = MockAsyncConnection(conn_id=1)

    for _ in range(100):
        await pool.release(key, conn, reuse=True)
        acquired = await pool.acquire(key)
        assert acquired is conn


async def test_empty_idle_queue_after_stale_connections(pool):
    pool._max_age = 0.05
    key = ("http", "example.com", 80)

    connections = [MockAsyncConnection(conn_id=i) for i in range(3)]
    for conn in connections:
        await pool.release(key, conn, reuse=True)

    await anysleep(0.1)

    acquired = await pool.acquire(key)
    assert acquired is None
    assert all(c.is_closed for c in connections)
    assert key not in pool._states


async def test_release_reservation_for_nonexistent_key():
    pool = AsyncConnPool()
    key = ("http", "example.com", 80)

    await pool.release_reservation(key)

    assert key not in pool._states


async def test_close_all_clears_semaphores(pool):
    keys = [("http", f"host{i}.com", 80) for i in range(5)]

    for key in keys:
        await pool.acquire(key)

    assert len(pool._states) == 5

    await pool.close_all()

    assert len(pool._states) == 0


async def test_semaphore_entry_removed_after_reservation_released():
    pool = AsyncConnPool()
    key = ("http", "example.com", 80)

    acquired = await pool.acquire(key)

    assert acquired is None
    assert key in pool._states

    await pool.release_reservation(key)

    assert key not in pool._states


#
# async def test_high_load_no_deadlock():
#     pool = AsyncConnPool(max_connections_per_host=10, max_idle_per_host=5)
#     key = ("http", "example.com", 80)
#     results = []

#     async def heavy_worker(worker_id: int):
#         for i in range(20):
#             conn = await pool.acquire(key)
#             if conn is None:
#                 conn = MockAsyncConnection(conn_id=worker_id * 100 + i)
#             else:
#                 await pool.release_reservation(key)

#             await sleep(0.0001)
#             results.append((worker_id, i))
#             await pool.release(key, conn, reuse=(i % 2 == 0))

#     tasks = [asyncio.create_task(heavy_worker(i)) for i in range(30)]

#     await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)

#     assert len(results) == 600
#     await pool.close_all()


async def test_acquire_all_connections_then_release():
    pool = AsyncConnPool(max_connections_per_host=3)
    key = ("http", "example.com", 80)

    state = await pool._get_state(key)
    assert state.semaphore._value == 3
    await pool._release_state_ref(key, state)

    acquired = []
    for _ in range(3):
        conn = await pool.acquire(key)
        acquired.append(conn)

    state = await get_state(pool, key)
    assert state is not None
    assert state.semaphore._value == 0

    for _ in range(3):
        await pool.release_reservation(key)

    assert key not in pool._states
