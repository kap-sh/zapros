import socket
import subprocess
import sys
import time

from litestar import Litestar, WebSocket, websocket


@websocket("/ws/echo-text")
async def ws_echo_text(socket: WebSocket) -> None:
    await socket.accept()
    while True:
        try:
            data = await socket.receive_text()
        except Exception:
            return
        await socket.send_text(f"echo:{data}")


@websocket("/ws/echo-binary")
async def ws_echo_binary(socket: WebSocket) -> None:
    await socket.accept()
    while True:
        try:
            data = await socket.receive_bytes()
        except Exception:
            return
        await socket.send_bytes(b"echo:" + data)


@websocket("/ws/echo-any")
async def ws_echo_any(socket: WebSocket) -> None:
    await socket.accept()
    while True:
        try:
            event = await socket.receive()
        except Exception:
            return
        if event["type"] == "websocket.disconnect":
            return
        if "text" in event and event["text"] is not None:
            await socket.send_text(event["text"])
        elif "bytes" in event and event["bytes"] is not None:
            await socket.send_bytes(event["bytes"])


@websocket("/ws/send-then-close")
async def ws_send_then_close(socket: WebSocket) -> None:
    await socket.accept()
    await socket.send_text("first")
    await socket.send_text("second")
    await socket.send_text("third")
    await socket.close(code=1000, reason="bye")


@websocket("/ws/close-immediately")
async def ws_close_immediately(socket: WebSocket) -> None:
    await socket.accept()
    await socket.close(code=4001, reason="go away")


app = Litestar(
    route_handlers=[
        ws_echo_text,
        ws_echo_binary,
        ws_echo_any,
        ws_send_then_close,
        ws_close_immediately,
    ],
)


class WebSocketTestServer:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self.process is not None:
            return

        self.port = _find_free_port(self.host)
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.websocket.ws_server:app",
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_until_up(self.host, self.port, self.process)

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                self.process.kill()
            except Exception:
                pass
        self.process = None


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_until_up(host: str, port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("websocket test server failed to start")
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("websocket test server did not start in time")
