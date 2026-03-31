import socket
import threading
from typing import Optional

import h11

from tests.mock._base import (
    MockResponse,
)


class MockServer:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.server_socket: Optional[socket.socket] = None
        self._mocks: dict[
            str,
            dict[
                tuple[str, str],
                MockResponse,
            ],
        ] = {}
        self._running = False
        self._accept_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.server_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
        self.server_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )
        self.server_socket.bind(
            (
                self.host,
                self.port,
            )
        )
        self.server_socket.listen(5)
        self.port = self.server_socket.getsockname()[1]
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_connections,
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_connections(
        self,
    ) -> None:
        while self._running and self.server_socket:
            try:
                self.server_socket.settimeout(0.1)
                client_socket, _ = self.server_socket.accept()
                thread = threading.Thread(
                    target=self.handle_connection,
                    args=(client_socket,),
                    daemon=True,
                )
                thread.start()
            except socket.timeout:
                continue
            except Exception:
                break

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def register_mock(
        self,
        node_id: str,
        method: str,
        path: str,
    ) -> MockResponse:
        if node_id not in self._mocks:
            self._mocks[node_id] = {}
        mock = MockResponse()
        self._mocks[node_id][(method, path)] = mock
        return mock

    def clear_mocks(self, node_id: str) -> None:
        self._mocks.pop(node_id, None)

    def _get_mock(
        self,
        node_id: str,
        method: str,
        path: str,
    ) -> Optional[MockResponse]:
        return self._mocks.get(node_id, {}).get(
            (
                method,
                path,
            )
        )

    def handle_connection(
        self,
        client_socket: socket.socket,
    ) -> None:
        conn = h11.Connection(h11.SERVER)
        client_socket.settimeout(30.0)

        try:
            while True:
                method = b""
                target = b""
                headers: list[tuple[bytes, bytes]] = []
                body = b""
                request_complete = False

                while not request_complete:
                    try:
                        data = client_socket.recv(8192)
                    except socket.timeout:
                        return

                    if not data:
                        return

                    conn.receive_data(data)

                    while True:
                        try:
                            event = conn.next_event()
                        except h11.RemoteProtocolError:
                            return

                        if event is h11.NEED_DATA:
                            break

                        if isinstance(
                            event,
                            h11.Request,
                        ):
                            method = event.method
                            target = event.target
                            headers = list(event.headers.raw_items())
                        elif isinstance(
                            event,
                            h11.Data,
                        ):
                            body += event.data
                        elif isinstance(
                            event,
                            h11.EndOfMessage,
                        ):
                            request_complete = True
                            break

                path = target.split(b"?")[0].decode()

                if path == "/echo":
                    raw_request = method + b" " + target + b" HTTP/1.1\r\n"
                    for (
                        name,
                        value,
                    ) in sorted(
                        (
                            name.lower(),
                            value,
                        )
                        for name, value in headers
                    ):
                        if name == b"user-agent":
                            value_str = value.decode()
                            if value_str.startswith("python-zapros/"):
                                value = b"python-zapros"
                        elif name == b"host":
                            value = value.split(b":")[0]
                        raw_request += name + b": " + value + b"\r\n"
                    raw_request += b"\r\n"
                    raw_request += body

                    response = h11.Response(
                        status_code=200,
                        headers=[
                            (
                                b"Content-Length",
                                str(len(raw_request)).encode("ascii"),
                            )
                        ],
                    )
                    client_socket.sendall(conn.send(response))
                    client_socket.sendall(conn.send(h11.Data(data=raw_request)))
                    client_socket.sendall(conn.send(h11.EndOfMessage()))
                else:
                    node_id: Optional[str] = None
                    for (
                        name,
                        value,
                    ) in headers:
                        if name.lower() == b"x-pytest-node-id":
                            node_id = value.decode()
                            break

                    mock = (
                        self._get_mock(
                            node_id,
                            method.decode(),
                            path,
                        )
                        if node_id
                        else None
                    )

                    if mock is None:
                        response_body = b"Not Found"
                        response = h11.Response(
                            status_code=404,
                            headers=[
                                (
                                    b"Content-Length",
                                    str(len(response_body)).encode("ascii"),
                                )
                            ],
                        )
                        client_socket.sendall(conn.send(response))
                        client_socket.sendall(conn.send(h11.Data(data=response_body)))
                    else:
                        response_headers: list[
                            tuple[
                                bytes,
                                bytes,
                            ]
                        ] = [
                            (
                                b"Content-Length",
                                str(len(mock.body)).encode("ascii"),
                            )
                        ]
                        for (
                            hname,
                            hvalue,
                        ) in mock.headers:
                            response_headers.append(
                                (
                                    hname.encode(),
                                    hvalue.encode(),
                                )
                            )

                        if mock.status // 100 == 1:
                            response = h11.InformationalResponse(
                                status_code=mock.status,
                                headers=response_headers,
                            )
                        else:
                            response = h11.Response(
                                status_code=mock.status,
                                headers=response_headers,
                            )
                        client_socket.sendall(conn.send(response))
                        if mock.body:
                            client_socket.sendall(conn.send(h11.Data(data=mock.body)))

                    if mock and mock.status != 101:
                        client_socket.sendall(conn.send(h11.EndOfMessage()))

                if conn.our_state is h11.SWITCHED_PROTOCOL:
                    conn = h11.Connection(h11.CLIENT)
                else:
                    conn.start_next_cycle()

        except (
            ConnectionError,
            OSError,
        ):
            pass
        finally:
            try:
                client_socket.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        if self._accept_thread:
            self._accept_thread.join(timeout=1.0)
