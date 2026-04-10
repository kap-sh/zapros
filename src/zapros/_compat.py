import asyncio
from typing import TYPE_CHECKING, Any

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
            return self._semaphore._value
        return self._semaphore.value

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
