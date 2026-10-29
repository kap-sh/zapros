import asyncio
import socket
import ssl
from typing import cast

import pytest

from zapros._errors import ReadTimeoutError
from zapros._io._asyncio import AsyncIOStream, _AsyncTLSState
from zapros._io._sync import SyncStream, SyncTransport, _SyncTLSState


class _WantReadSSLObject:
    """Stands in for an upgraded TLS session that is still waiting for the peer."""

    def read(self, max_bytes: int) -> bytes:
        raise ssl.SSLWantReadError()


class _SilentSocket:
    """A socket whose peer never sends anything."""

    def __init__(self) -> None:
        self.timeout: float | None = None

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def recv(self, max_bytes: int) -> bytes:
        assert self.timeout is not None, "read without a timeout would block forever"
        raise TimeoutError


def test_sync_start_tls_stream_read_honours_timeout() -> None:
    sock = cast(socket.socket, _SilentSocket())
    stream = SyncStream(sock, upgrade_ssl_context=ssl.create_default_context())
    stream._tls_state = _SyncTLSState(sock, cast(ssl.SSLObject, _WantReadSSLObject()), ssl.MemoryBIO(), ssl.MemoryBIO())

    with pytest.raises(ReadTimeoutError):
        stream.read(1024, timeout=0.01)


@pytest.mark.no_pyodide  # socket.socketpair() crashes Pyodide
def test_asyncio_start_tls_stream_read_honours_timeout() -> None:
    async def main() -> None:
        sock, peer = socket.socketpair()
        with peer:
            reader, writer = await asyncio.open_connection(sock=sock)
            stream = AsyncIOStream(reader, writer)
            stream._tls_state = _AsyncTLSState(
                reader, writer, cast(ssl.SSLObject, _WantReadSSLObject()), ssl.MemoryBIO(), ssl.MemoryBIO()
            )

            # The outer timeout only keeps a regression from hanging the test run.
            with pytest.raises(ReadTimeoutError):
                await asyncio.wait_for(stream.read(1024, timeout=0.01), 5)
            writer.close()

    asyncio.run(main())


@pytest.mark.no_pyodide  # needs a real listening socket
def test_sync_connect_enables_tcp_nodelay() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        stream = cast(SyncStream, SyncTransport().connect("127.0.0.1", server.getsockname()[1]))
        try:
            assert stream.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
        finally:
            stream.close()
