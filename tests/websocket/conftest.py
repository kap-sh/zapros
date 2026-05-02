import pytest

from tests.websocket.ws_server import WebSocketTestServer


@pytest.fixture(scope="session")
def ws_server():
    server = WebSocketTestServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
