import asyncio
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar

if TYPE_CHECKING:
    import sniffio
    import trio
else:
    try:
        import sniffio
        import trio
    except ImportError:
        sniffio = None
        trio = None

T = TypeVar("T")


def in_trio_run() -> bool:
    """Return True if we're currently running inside a trio.run() context."""
    if trio is None:
        return False

    return trio.lowlevel.in_trio_run()


class AnyEventTimeoutError(Exception):
    """Raised when a timeout occurs while waiting for an AnyEvent."""


class AnyEvent:
    """
    An event that can be used in both asyncio and trio contexts.

    Must be constructed inside a running event loop.
    """

    def __init__(self) -> None:
        self._event: Any = None

        if not in_trio_run():
            self._event = asyncio.Event()
        elif in_trio_run():
            self._event = trio.Event()
        else:
            raise RuntimeError("Unsupported async library")

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self, timeout: float | None = None) -> None:

        if timeout is None:
            await self._event.wait()
        elif in_trio_run():
            try:
                with trio.fail_after(timeout):
                    await self._event.wait()
            except trio.TooSlowError:
                raise AnyEventTimeoutError("Timeout while waiting for event") from None
        else:
            try:
                await asyncio.wait_for(self._event.wait(), timeout)
            except asyncio.TimeoutError:
                raise AnyEventTimeoutError("Timeout while waiting for event") from None


class AnyLock:
    """
    A lock that can be used in both asyncio and trio contexts. It is a no-op in synchronous contexts.
    """

    def __init__(self) -> None:
        self._lock = None

    def _ensure_lock(self) -> None:
        if self._lock is not None:
            return

        current_async_library = sniffio.current_async_library() if sniffio is not None else None

        if current_async_library is None or current_async_library == "asyncio":
            self._lock = asyncio.Lock()
        elif current_async_library == "trio":
            self._lock = trio.Lock()
        else:
            raise RuntimeError(f"Unsupported async library: {current_async_library}")

    async def acquire(self) -> None:
        self._ensure_lock()
        assert self._lock is not None
        await self._lock.acquire()

    def release(self) -> None:
        self._ensure_lock()
        assert self._lock is not None
        self._lock.release()

    async def __aenter__(self) -> "AnyLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class AnySemaphore:
    """
    A semaphore that can be used in both asyncio and trio contexts.
    """

    def __init__(self, value: int = 1) -> None:
        self._initial_value = value
        self._semaphore = None

    def _ensure_semaphore(self) -> None:
        if self._semaphore is not None:
            return

        current_async_library = sniffio.current_async_library() if sniffio is not None else None

        if current_async_library is None or current_async_library == "asyncio":
            self._semaphore = asyncio.Semaphore(self._initial_value)
        elif current_async_library == "trio":
            self._semaphore = trio.Semaphore(self._initial_value)
        else:
            raise RuntimeError(f"Unsupported async library: {current_async_library}")

    async def acquire(self) -> None:
        self._ensure_semaphore()
        assert self._semaphore is not None
        await self._semaphore.acquire()

    def release(self) -> None:
        self._ensure_semaphore()
        assert self._semaphore is not None
        self._semaphore.release()

    @property
    def _value(self) -> int:
        self._ensure_semaphore()
        assert self._semaphore is not None
        if hasattr(self._semaphore, "_value"):
            return self._semaphore._value  # type: ignore[reportPrivateUsage]
        return self._semaphore.value  # type: ignore[reportPrivateUsage]

    async def __aenter__(self) -> "AnySemaphore":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


async def anysleep(delay: float) -> None:
    """
    Sleep for the given number of seconds, using the appropriate sleep function for the current async library.
    """
    current_async_library = sniffio.current_async_library() if sniffio is not None else None

    if current_async_library is None or current_async_library == "asyncio":
        await asyncio.sleep(delay)
    elif current_async_library == "trio":
        await trio.sleep(delay)
    else:
        raise RuntimeError(f"Unsupported async library: {current_async_library}")


class AnyQueue(Generic[T]):
    """
    A minimal queue that can be used in both asyncio and trio contexts.
    Backend (asyncio.Queue or trio memory channel) is created lazily
    on first use, so the object can be constructed outside a running loop.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._maxsize = maxsize
        self._queue: Optional[asyncio.Queue[T]] = None  # asyncio.Queue
        self._send: Optional["trio.MemorySendChannel[T]"] = None  # trio send channel
        self._recv: Optional["trio.MemoryReceiveChannel[T]"] = None  # trio receive channel

    def _ensure_initialized(self) -> None:
        if self._queue is not None or (self._send is not None and self._recv is not None):
            return
        if in_trio_run():
            buffer_size = float("inf") if self._maxsize <= 0 else self._maxsize
            self._send, self._recv = trio.open_memory_channel(buffer_size)
        else:
            self._queue = asyncio.Queue(maxsize=self._maxsize)

    async def put(self, item: T) -> None:
        self._ensure_initialized()
        if self._send is not None:
            assert self._send is not None
            await self._send.send(item)
        else:
            assert self._queue is not None
            await self._queue.put(item)

    async def get(self) -> T:
        self._ensure_initialized()
        if self._recv is not None:
            assert self._recv is not None
            return await self._recv.receive()
        else:
            assert self._queue is not None
            return await self._queue.get()

    async def aclose(self) -> None:
        if self._send is not None:
            await self._send.aclose()
        else:
            # No explicit close method for asyncio.Queue, but we can clear it to unblock any waiting getters
            if self._queue is not None:
                while not self._queue.empty():
                    self._queue.get_nowait()
