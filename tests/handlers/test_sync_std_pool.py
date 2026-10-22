import socket
import threading

import h11
import pytest

from zapros import Client, StdNetworkHandler
from time import sleep


class IdleClosingServer:
    def __init__(self, idle_timeout: float, half_close: bool = False) -> None:
        self.connections = 0
        self._idle_timeout = idle_timeout
        self._half_close = half_close
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self._sock.getsockname()[1]}/"

    def __enter__(self) -> "IdleClosingServer":
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def __exit__(self, *args: object) -> None:
        self._sock.close()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            server = h11.Connection(h11.SERVER)
            conn.settimeout(self._idle_timeout)
            while True:
                event = server.next_event()
                if event is h11.NEED_DATA:
                    try:
                        server.receive_data(conn.recv(65536))
                    except TimeoutError:
                        self._close_idle(conn)
                        return
                elif isinstance(event, h11.EndOfMessage):
                    response = h11.Response(status_code=200, headers=[("content-length", "2")])
                    for reply in (response, h11.Data(data=b"ok"), h11.EndOfMessage()):
                        conn.sendall(server.send(reply))
                    server.start_next_cycle()
                elif isinstance(event, h11.ConnectionClosed):
                    return

    def _close_idle(self, conn: socket.socket) -> None:
        if not self._half_close:
            return
        conn.shutdown(socket.SHUT_WR)
        conn.settimeout(5)
        while conn.recv(65536):
            pass


@pytest.mark.parametrize("half_close", [True, False], ids=["fin", "rst"])
def test_idle_connection_closed_by_server_is_not_reused(half_close: bool) -> None:
    def body():
        yield b"second"

    with IdleClosingServer(idle_timeout=0.1, half_close=half_close) as server:
        with Client(handler=StdNetworkHandler()) as client:
            assert (client.put(server.url, body=b"first")).status == 200
            sleep(0.3)
            assert (client.put(server.url, body=body())).status == 200

    assert server.connections == 2


def test_live_idle_connection_is_reused() -> None:
    with IdleClosingServer(idle_timeout=5) as server:
        with Client(handler=StdNetworkHandler()) as client:
            assert (client.put(server.url, body=b"first")).status == 200
            sleep(0.3)
            assert (client.put(server.url, body=b"second")).status == 200

    assert server.connections == 1
