from __future__ import annotations

import socket
import ssl

from ._base_io import BaseNetworkStream
from ._handlers._exc_map import map_connect_exceptions, map_read_exceptions, map_write_exceptions


def connect_tcp(
    host: str,
    port: int,
    *,
    ssl_context: ssl.SSLContext | None = None,
    timeout: float | None = None,
    server_hostname: str | None = None,
) -> StdNetworkStream:
    with map_connect_exceptions():
        sock = socket.create_connection((host, port), timeout=timeout)

    try:
        if ssl_context is not None:
            sock = ssl_context.wrap_socket(
                sock,
                server_hostname=server_hostname or host,
            )
        sock.settimeout(None)
        return StdNetworkStream(sock, server_hostname=server_hostname or host)
    except Exception:
        sock.close()
        raise


class StdNetworkStream(BaseNetworkStream):
    def __init__(self, sock: socket.socket, server_hostname: str | None = None) -> None:
        self.sock = sock
        self._server_hostname = server_hostname
        self._closed = False

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        with map_read_exceptions():
            self.sock.settimeout(timeout)
            return self.sock.recv(max_bytes)

    def write_all(self, data: bytes, timeout: float | None = None) -> int:
        with map_write_exceptions():
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

