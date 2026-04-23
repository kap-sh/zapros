import gzip
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

from litestar import Litestar, Request, Response, WebSocket, get, websocket
from litestar.handlers import route

if TYPE_CHECKING:
    import socket
else:
    try:
        import socket
    except ImportError:
        socket = None


def _normalize_header(name: bytes, value: bytes) -> tuple[str, str]:
    key = name.decode("latin-1").lower()
    text = value.decode("latin-1")

    if key == "user-agent" and text.startswith("python-zapros/"):
        text = "python-zapros"
    elif key == "host":
        text = text.split(":", 1)[0]

    return key, text


@route("/{path:path}", http_method=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def echo(request: Request[Any, Any, Any]) -> str:
    method = request.method
    path = request.url.path
    http_version = request.scope.get("http_version", "1.1")

    request_line = f"{method} {path} HTTP/{http_version}\r\n"
    headers = "".join(
        f"{key}: {value}\r\n"
        for key, value in sorted(_normalize_header(name, value) for name, value in request.scope["headers"])
    )

    body_bytes = await request.body()
    try:
        body = body_bytes.decode()
    except Exception:
        body = repr(body_bytes)

    return f"{request_line}{headers}\r\n{body}"


@websocket("/ws")
async def ws_handler(socket: WebSocket) -> None:
    await socket.accept()

    while True:
        data = await socket.receive_text()
        await socket.send_text(f"Echo: {data}")


@get("/gzip")
async def gzip_endpoint(request: Request) -> Response[bytes]:
    raw: Any | str = request.query_params.get("data", "")
    compressed = gzip.compress(raw.encode())

    return Response(
        content=compressed,
        media_type="application/json",
        headers={
            "Content-Encoding": "gzip",
            "Content-Length": str(len(compressed)),
        },
    )


app = Litestar(route_handlers=[echo, ws_handler, gzip_endpoint])


class MockServer:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.process = None

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
                "tests.mock_server:app",
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
            raise RuntimeError("mock server failed to start")
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("mock server did not start in time")


AsyncMockServer = MockServer
