from __future__ import annotations

import ssl
from typing import TYPE_CHECKING, cast

from zapros._constants import DEFAULT_SSL_CONTEXT

from .._handlers._exc_map import (
    map_trio_connect_exceptions,
    map_trio_read_exceptions,
    map_trio_write_exceptions,
)
from ._base import AsyncBaseNetworkStream, AsyncBaseTransport

if TYPE_CHECKING:
    import trio
else:
    try:
        import trio
    except ImportError:
        trio = None


class TrioStream(AsyncBaseNetworkStream):
    def __init__(
        self,
        stream: trio.abc.Stream,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._stream = stream
        self._closed = False
        self._ssl_context = ssl_context or DEFAULT_SSL_CONTEXT

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        with map_trio_read_exceptions():
            if timeout is None:
                return cast(bytes, await self._stream.receive_some(max_bytes))

            with trio.fail_after(timeout):
                return cast(
                    bytes,
                    await self._stream.receive_some(max_bytes),
                )

    async def write_all(self, data: bytes, timeout: float | None = None) -> int:
        with map_trio_write_exceptions():
            if timeout is None:
                await self._stream.send_all(data)
            else:
                with trio.fail_after(timeout):
                    await self._stream.send_all(data)

            return len(data)

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        try:
            await self._stream.aclose()
        except Exception:
            pass

    async def start_tls(
        self,
        *,
        server_hostname: str | None = None,
    ) -> AsyncBaseNetworkStream:
        hostname = server_hostname

        ssl_stream = trio.SSLStream(
            self._stream,
            ssl_context=self._ssl_context,
            server_side=False,
            server_hostname=hostname,
            https_compatible=True,
        )

        with map_trio_connect_exceptions():
            await ssl_stream.do_handshake()

        self._stream = ssl_stream
        self._server_hostname = hostname
        return self


class TrioTransport(AsyncBaseTransport):
    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.ssl_context = DEFAULT_SSL_CONTEXT if ssl_context is None else ssl_context

    async def aconnect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        timeout: float | None = None,
    ) -> AsyncBaseNetworkStream:
        with map_trio_connect_exceptions():
            if timeout is None:
                stream = await trio.open_tcp_stream(host, port)
            else:
                with trio.fail_after(timeout):
                    stream = await trio.open_tcp_stream(host, port)

            if tls:
                ssl_stream = trio.SSLStream(
                    stream,
                    ssl_context=self.ssl_context,
                    server_side=False,
                    server_hostname=server_hostname,
                    https_compatible=True,
                )

                if timeout is None:
                    await ssl_stream.do_handshake()
                else:
                    with trio.fail_after(timeout):
                        await ssl_stream.do_handshake()

                stream = ssl_stream

        return TrioStream(
            stream,
            ssl_context=self.ssl_context,
        )
