from __future__ import annotations

import asyncio
import ssl

from ._base_io import AsyncBaseNetworkStream
from ._handlers._exc_map import map_connect_exceptions, map_read_exceptions, map_write_exceptions


async def aconnect_tcp(
    host: str,
    port: int,
    *,
    ssl_context: ssl.SSLContext | None = None,
    timeout: float | None = None,
    server_hostname: str | None = None,
) -> AsyncStdNetworkStream:
    with map_connect_exceptions():
        if timeout is None:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                ssl=ssl_context,
                server_hostname=server_hostname or host if ssl_context else None,
                happy_eyeballs_delay=0.25,
                interleave=1,
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host,
                    port,
                    ssl=ssl_context,
                    server_hostname=server_hostname or host if ssl_context else None,
                    happy_eyeballs_delay=0.25,
                    interleave=1,
                    ssl_handshake_timeout=timeout,
                ),
                timeout,
            )

    return AsyncStdNetworkStream(reader, writer, server_hostname=server_hostname or host)


class AsyncStdNetworkStream(AsyncBaseNetworkStream):
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        server_hostname: str | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._server_hostname = server_hostname
        self._closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        with map_read_exceptions():
            if timeout is None:
                return await self._reader.read(max_bytes)
            return await asyncio.wait_for(self._reader.read(max_bytes), timeout)

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        with map_write_exceptions():
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
