from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

from zapros._constants import DEFAULT_READ_SIZE, default_ssl_context

from .._handlers._exc_map import (
    map_asyncio_connect_exceptions,
    map_asyncio_read_exceptions,
    map_asyncio_write_exceptions,
    map_socket_read_exceptions,
)
from ._base import AsyncBaseNetworkStream, AsyncBaseTransport

if TYPE_CHECKING:
    import ssl
else:
    try:
        import ssl
    except ImportError:
        ssl = None

T = TypeVar("T")


def is_uvloop() -> bool:
    """Return True if the current event loop is uvloop."""

    try:
        import uvloop

        return isinstance(asyncio.get_running_loop(), uvloop.Loop)
    except (ImportError, AttributeError):
        return False


class _AsyncTLSState:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        ssl_object: ssl.SSLObject,
        incoming_bio: ssl.MemoryBIO,
        outgoing_bio: ssl.MemoryBIO,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.ssl_object = ssl_object
        self.incoming_bio = incoming_bio
        self.outgoing_bio = outgoing_bio
        self.handshake_complete = False


class AsyncIOStream(AsyncBaseNetworkStream):
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        ssl_context: Optional["ssl.SSLContext"] = None,
        upgrade_ssl_context: Optional["ssl.SSLContext"] = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False
        self._ssl_context = ssl_context or default_ssl_context()
        self._upgrade_ssl_context = upgrade_ssl_context or default_ssl_context()
        self._tls_state: _AsyncTLSState | None = None

    async def _flush_outgoing(self, timeout: float | None = None) -> None:
        assert self._tls_state is not None
        pending = self._tls_state.outgoing_bio.read(DEFAULT_READ_SIZE)
        if pending:
            with map_asyncio_write_exceptions():
                self._tls_state.writer.write(pending)
                if timeout is None:
                    await self._tls_state.writer.drain()
                else:
                    await asyncio.wait_for(self._tls_state.writer.drain(), timeout)

    async def _pump_incoming(self, timeout: float | None = None) -> None:
        assert self._tls_state is not None
        with map_socket_read_exceptions():
            if timeout is None:
                data = await self._tls_state.reader.read(DEFAULT_READ_SIZE)
            else:
                data = await asyncio.wait_for(self._tls_state.reader.read(n=DEFAULT_READ_SIZE), timeout)

            if data:
                self._tls_state.incoming_bio.write(data)
            else:
                self._tls_state.incoming_bio.write_eof()

    async def _call_sslobject_method(self, func: Callable[..., T], *args: Any) -> T:
        assert self._tls_state is not None
        while True:
            try:
                result = func(*args)
                await self._flush_outgoing()
                return result
            except ssl.SSLWantReadError:
                await self._flush_outgoing()
                await self._pump_incoming()
            except ssl.SSLWantWriteError:
                await self._flush_outgoing()
            except (ssl.SSLError, ssl.SSLEOFError) as e:
                raise ConnectionError(str(e)) from e

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self._tls_state is not None:
            return await self._call_sslobject_method(self._tls_state.ssl_object.read, max_bytes)

        with map_asyncio_read_exceptions():
            if timeout is None:
                return await self._reader.read(max_bytes)
            return await asyncio.wait_for(self._reader.read(max_bytes), timeout)

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        if self._tls_state is not None:
            await self._call_sslobject_method(self._tls_state.ssl_object.write, data)
            return len(data)

        with map_asyncio_write_exceptions():
            self._writer.write(data)
            if timeout is None:
                await self._writer.drain()
            else:
                await asyncio.wait_for(self._writer.drain(), timeout)
            return len(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._writer.close()
        except Exception:
            pass

    async def start_tls(self, *, server_hostname: str | None = None) -> AsyncBaseNetworkStream:
        assert self._upgrade_ssl_context is not None

        hostname = server_hostname

        incoming = ssl.MemoryBIO()
        outgoing = ssl.MemoryBIO()

        ssl_object = self._upgrade_ssl_context.wrap_bio(incoming, outgoing, server_side=False, server_hostname=hostname)

        self._tls_state = _AsyncTLSState(self._reader, self._writer, ssl_object, incoming, outgoing)

        await self._call_sslobject_method(self._tls_state.ssl_object.do_handshake)
        self._tls_state.handshake_complete = True

        return self


class AsyncIOTransport(AsyncBaseTransport):
    def __init__(
        self,
        *,
        ssl_context: Optional["ssl.SSLContext"] = None,
    ) -> None:
        self.ssl_context = default_ssl_context() if ssl_context is None else ssl_context

    async def aconnect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        timeout: float | None = None,
    ) -> AsyncBaseNetworkStream:
        with map_asyncio_connect_exceptions():
            if timeout is None:
                if is_uvloop():
                    # uvloop's open_connection doesn't support `happy_eyeballs_delay` and `interleave`
                    reader, writer = await asyncio.open_connection(
                        host,
                        port,
                        ssl=self.ssl_context if tls else None,
                        server_hostname=server_hostname if tls else None,
                    )
                else:
                    reader, writer = await asyncio.open_connection(
                        host,
                        port,
                        ssl=self.ssl_context if tls else None,
                        server_hostname=server_hostname if tls else None,
                        happy_eyeballs_delay=0.25,
                        interleave=1,
                    )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        host,
                        port,
                        ssl=self.ssl_context if tls else None,
                        server_hostname=server_hostname if tls else None,
                        happy_eyeballs_delay=0.25,
                        interleave=1,
                        ssl_handshake_timeout=timeout,
                    ),
                    timeout,
                )

        return AsyncIOStream(
            reader,
            writer,
            ssl_context=self.ssl_context,
            upgrade_ssl_context=self.ssl_context,
        )
