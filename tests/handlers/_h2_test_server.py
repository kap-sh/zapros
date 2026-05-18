from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import h2.config
import h2.connection
import h2.events


@dataclass
class H2Response:
    status: int = 200
    headers: list[tuple[str, str]] = field(default_factory=lambda: [("content-type", "text/plain")])
    body: bytes = b"ok"
    delay_headers: float = 0.0
    send_goaway: bool = False


Handler = Callable[[bytes, list[tuple[str, str]]], H2Response]
"""Receives (request_body_bytes, request_headers) and returns the H2Response."""


def _default_handler(body: bytes, headers: list[tuple[str, str]]) -> H2Response:
    return H2Response()


class AsyncH2TestServer:
    def __init__(self, handler: Handler | None = None) -> None:
        self._handler = handler or _default_handler
        self._host = "127.0.0.1"
        self._port = 0
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._started = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        if self._thread is not None:
            return

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self._host, 0))
            self._port = s.getsockname()[1]

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._started.wait(timeout=5.0)

    def stop(self) -> None:
        if self._loop is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._server = None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def _serve() -> None:
            self._server = await asyncio.start_server(self._handle_connection, self._host, self._port)
            self._started.set()
            async with self._server:
                await self._server.serve_forever()

        try:
            loop.run_until_complete(_serve())
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            loop.close()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        config = h2.config.H2Configuration(client_side=False, header_encoding="utf-8")
        conn = h2.connection.H2Connection(config=config)
        conn.initiate_connection()
        writer.write(conn.data_to_send())
        await writer.drain()

        request_data: dict[int, bytearray] = {}
        request_headers: dict[int, list[tuple[str, str]]] = {}

        try:
            while True:
                data = await reader.read(65535)
                if not data:
                    break
                events = conn.receive_data(data)
                for event in events:
                    if isinstance(event, h2.events.RequestReceived):
                        request_data[event.stream_id] = bytearray()
                        request_headers[event.stream_id] = [(str(k), str(v)) for k, v in (event.headers or [])]
                    elif isinstance(event, h2.events.DataReceived):
                        request_data[event.stream_id].extend(event.data)
                        conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, h2.events.StreamEnded):
                        body = bytes(request_data.pop(event.stream_id, b""))
                        headers = request_headers.pop(event.stream_id, [])
                        resp = self._handler(body, headers)
                        if resp.send_goaway:
                            conn.close_connection()
                        else:
                            if resp.delay_headers:
                                await asyncio.sleep(resp.delay_headers)
                            conn.send_headers(
                                event.stream_id,
                                [(":status", str(resp.status)), *resp.headers],
                            )
                            conn.send_data(event.stream_id, resp.body, end_stream=True)
                out = conn.data_to_send()
                if out:
                    writer.write(out)
                    await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


SyncH2TestServer = AsyncH2TestServer
