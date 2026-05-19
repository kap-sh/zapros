from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional, cast

if TYPE_CHECKING:
    import ssl
else:
    try:
        import ssl
    except ImportError:
        ssl = None

from zapros._constants import default_ssl_context

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
        ssl_context: Optional["ssl.SSLContext"] = None,
    ) -> None:
        self._stream = stream
        self._closed = False
        self._ssl_context = ssl_context or default_ssl_context()

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

    def selected_alpn_protocol(self) -> Literal["http/1.1", "h2"] | None:
        if not isinstance(self._stream, trio.SSLStream):
            return None
        # trio.SSLStream wraps an ssl.SSLObject internally
        ssl_object = self._stream._ssl_object  # type: ignore[attr-defined]
        return ssl_object.selected_alpn_protocol()  # type: ignore[return-value]


class TrioTransport(AsyncBaseTransport):
    def __init__(
        self,
        *,
        ssl_context: Optional["ssl.SSLContext"] = None,
    ) -> None:
        self.ssl_context = default_ssl_context() if ssl_context is None else ssl_context
        self._lock = trio.Lock()

    async def aconnect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        alpn_protocols: list[Literal["http/1.1", "h2"]] | None = None,
        timeout: float | None = None,
    ) -> AsyncBaseNetworkStream:

        if alpn_protocols is not None:
            async with self._lock:
                self.ssl_context.set_alpn_protocols(alpn_protocols)

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
