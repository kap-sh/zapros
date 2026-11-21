import asyncio
import socket
import ssl
from typing import cast

import pytest

from zapros._errors import ReadTimeoutError, WriteTimeoutError
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


class _BufferingSSLObject:
    """Stands in for a TLS session: whatever is written ends up in the outgoing BIO."""

    def __init__(self, outgoing: ssl.MemoryBIO) -> None:
        self._outgoing = outgoing

    def write(self, data: bytes) -> int:
        return self._outgoing.write(data)


class _RecordingSocket:
    def __init__(self) -> None:
        self.sent = bytearray()
        self.timeouts: list[float | None] = []

    def settimeout(self, timeout: float | None) -> None:
        self.timeouts.append(timeout)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)


def test_sync_start_tls_stream_write_flushes_everything_with_timeout() -> None:
    recording = _RecordingSocket()
    sock = cast(socket.socket, recording)
    outgoing = ssl.MemoryBIO()
    stream = SyncStream(sock, upgrade_ssl_context=ssl.create_default_context())
    ssl_object = cast(ssl.SSLObject, _BufferingSSLObject(outgoing))
    stream._tls_state = _SyncTLSState(sock, ssl_object, ssl.MemoryBIO(), outgoing)

    stream.write_all(b"x" * 1_000_000, timeout=3.0)

    assert len(recording.sent) == 1_000_000
    assert set(recording.timeouts) == {3.0}


@pytest.mark.no_pyodide  # socket.socketpair() crashes Pyodide
def test_asyncio_start_tls_stream_write_flushes_everything() -> None:
    async def main() -> None:
        sock, peer = socket.socketpair()
        reader, writer = await asyncio.open_connection(sock=sock)
        peer_reader, peer_writer = await asyncio.open_connection(sock=peer)
        outgoing = ssl.MemoryBIO()
        stream = AsyncIOStream(reader, writer)
        stream._tls_state = _AsyncTLSState(
            reader, writer, cast(ssl.SSLObject, _BufferingSSLObject(outgoing)), ssl.MemoryBIO(), outgoing
        )

        # The outer timeout only keeps a regression from hanging the test run.
        _, received = await asyncio.wait_for(
            asyncio.gather(stream.write_all(b"x" * 1_000_000), peer_reader.readexactly(1_000_000)), 5
        )
        assert len(received) == 1_000_000
        writer.close()
        peer_writer.close()

    asyncio.run(main())


class _ReadableSSLObject(_BufferingSSLObject):
    """A TLS session with decrypted data ready, whose read also leaves records to send."""

    def read(self, max_bytes: int) -> bytes:
        self._outgoing.write(b"record")
        return b"decrypted"


@pytest.mark.no_pyodide  # socket.socketpair() crashes Pyodide
def test_asyncio_start_tls_stream_write_honours_timeout_and_does_not_block_reads() -> None:
    async def main() -> None:
        sock, peer = socket.socketpair()
        with peer:  # never reads, so the transport fills up
            reader, writer = await asyncio.open_connection(sock=sock)
            outgoing = ssl.MemoryBIO()
            stream = AsyncIOStream(reader, writer)
            stream._tls_state = _AsyncTLSState(
                reader, writer, cast(ssl.SSLObject, _ReadableSSLObject(outgoing)), ssl.MemoryBIO(), outgoing
            )

            # The outer timeouts only keep a regression from hanging the test run.
            with pytest.raises(WriteTimeoutError):
                await asyncio.wait_for(stream.write_all(b"x" * 10_000_000, timeout=0.05), 5)
            assert await asyncio.wait_for(stream.read(1024), 5) == b"decrypted"
            writer.transport.abort()

    asyncio.run(main())


@pytest.mark.no_pyodide  # socket.socketpair() crashes Pyodide
def test_asyncio_start_tls_stream_write_with_timeout_can_be_cancelled() -> None:
    async def main() -> None:
        sock, peer = socket.socketpair()
        with peer:
            reader, writer = await asyncio.open_connection(sock=sock)
            outgoing = ssl.MemoryBIO()
            stream = AsyncIOStream(reader, writer)
            stream._tls_state = _AsyncTLSState(
                reader, writer, cast(ssl.SSLObject, _BufferingSSLObject(outgoing)), ssl.MemoryBIO(), outgoing
            )

            task = asyncio.ensure_future(stream.write_all(b"x", timeout=5))
            # Cancel once the drain has finished but before the write has returned.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            writer.close()

    asyncio.run(main())
