import asyncio
from typing import Optional

import h11

from tests.mock._base import (
    MockResponse,
)


class AsyncMockServer:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.server: Optional[asyncio.Server] = None
        self._mocks: dict[
            str,
            dict[
                tuple[str, str],
                MockResponse,
            ],
        ] = {}

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self.handle_connection,
            self.host,
            self.port,
        )
        socket = self.server.sockets[0] if self.server.sockets else None
        if socket:
            self.port = socket.getsockname()[1]

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

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        conn = h11.Connection(h11.SERVER)

        try:
            while True:
                method = b""
                target = b""
                headers: list[tuple[bytes, bytes]] = []
                body = b""
                request_complete = False

                while not request_complete:
                    try:
                        data = await asyncio.wait_for(
                            reader.read(8192),
                            timeout=30.0,
                        )
                    except asyncio.TimeoutError:
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
                    writer.write(conn.send(response))
                    writer.write(conn.send(h11.Data(data=raw_request)))
                    writer.write(conn.send(h11.EndOfMessage()))
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
                        writer.write(conn.send(response))
                        writer.write(conn.send(h11.Data(data=response_body)))
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

                        response = h11.Response(
                            status_code=mock.status,
                            headers=response_headers,
                        )
                        writer.write(conn.send(response))
                        if mock.body:
                            writer.write(conn.send(h11.Data(data=mock.body)))

                    writer.write(conn.send(h11.EndOfMessage()))

                await writer.drain()
                conn.start_next_cycle()

        except (
            ConnectionError,
            asyncio.CancelledError,
        ):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
