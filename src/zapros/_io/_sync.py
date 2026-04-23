import ssl
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from zapros._constants import DEFAULT_READ_SIZE, default_ssl_context
from zapros._handlers._exc_map import (
    map_socket_connect_exceptions,
    map_socket_read_exceptions,
    map_socket_write_exceptions,
)
from zapros._io._base import BaseNetworkStream, BaseTransport

T = TypeVar("T")

if TYPE_CHECKING:
    import socket
else:
    try:
        import socket
    except ImportError:
        socket = None


class _SyncTLSState:
    def __init__(
        self,
        sock: socket.socket,
        ssl_object: ssl.SSLObject,
        incoming_bio: ssl.MemoryBIO,
        outgoing_bio: ssl.MemoryBIO,
    ) -> None:
        self.sock = sock
        self.ssl_object = ssl_object
        self.incoming_bio = incoming_bio
        self.outgoing_bio = outgoing_bio
        self.handshake_complete = False


class SyncStream(BaseNetworkStream):
    def __init__(self, sock: socket.socket, *, upgrade_ssl_context: ssl.SSLContext) -> None:
        self.sock = sock
        self._closed = False
        self._upgrade_ssl_context = upgrade_ssl_context
        self._tls_state: _SyncTLSState | None = None

    def _flush_outgoing(self, timeout: float | None = None) -> None:
        assert self._tls_state is not None
        pending = self._tls_state.outgoing_bio.read(DEFAULT_READ_SIZE)
        if pending:
            with map_socket_write_exceptions():
                self._tls_state.sock.settimeout(timeout)
                self._tls_state.sock.sendall(pending)

    def _pump_incoming(self, timeout: float | None = None) -> None:
        assert self._tls_state is not None
        with map_socket_read_exceptions():
            self._tls_state.sock.settimeout(timeout)
            data = self._tls_state.sock.recv(DEFAULT_READ_SIZE)
            if data:
                self._tls_state.incoming_bio.write(data)
            else:
                self._tls_state.incoming_bio.write_eof()

    def _call_sslobject_method(self, func: Callable[..., T], *args: Any) -> T:
        assert self._tls_state is not None
        while True:
            try:
                result = func(*args)
                self._flush_outgoing()
                return result
            except ssl.SSLWantReadError:
                self._flush_outgoing()
                self._pump_incoming()
            except ssl.SSLWantWriteError:
                self._flush_outgoing()
            except (ssl.SSLError, ssl.SSLEOFError) as e:
                raise ConnectionError(str(e)) from e

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self._tls_state is not None:
            return self._call_sslobject_method(self._tls_state.ssl_object.read, max_bytes)

        with map_socket_read_exceptions():
            self.sock.settimeout(timeout)
            return self.sock.recv(max_bytes)

    def write_all(self, data: bytes, timeout: float | None = None) -> int:
        if self._tls_state is not None:
            self._call_sslobject_method(self._tls_state.ssl_object.write, data)
            return len(data)

        with map_socket_write_exceptions():
            self.sock.settimeout(timeout)
            self.sock.sendall(data)
            return len(data)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
        except Exception:
            pass

    def start_tls(self, *, server_hostname: str | None = None) -> BaseNetworkStream:
        assert self._upgrade_ssl_context is not None

        hostname = server_hostname

        incoming = ssl.MemoryBIO()
        outgoing = ssl.MemoryBIO()

        ssl_object = self._upgrade_ssl_context.wrap_bio(incoming, outgoing, server_side=False, server_hostname=hostname)

        self._tls_state = _SyncTLSState(self.sock, ssl_object, incoming, outgoing)

        self._call_sslobject_method(self._tls_state.ssl_object.do_handshake)
        self._tls_state.handshake_complete = True

        return self


class SyncTransport(BaseTransport):
    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.ssl_context = default_ssl_context() if ssl_context is None else ssl_context

    def connect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        timeout: float | None = None,
    ) -> BaseNetworkStream:
        with map_socket_connect_exceptions():
            sock = socket.create_connection((host, port), timeout=timeout)

        try:
            if tls:
                sock = self.ssl_context.wrap_socket(
                    sock,
                    server_hostname=server_hostname,
                )
            sock.settimeout(None)
            return SyncStream(sock, upgrade_ssl_context=self.ssl_context)
        except Exception:
            sock.close()
            raise
