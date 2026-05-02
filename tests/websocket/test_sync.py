import pytest
from inline_snapshot import snapshot

from tests.websocket.ws_server import WebSocketTestServer
from zapros.websocket import BinaryMessage, CloseMessage, ConnectionClosed, TextMessage, connect_ws


def test_text_echo(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        ws.send(TextMessage(data="hello"))
        msg = ws.recv()
        assert msg == snapshot(TextMessage(data="echo:hello"))


def test_binary_echo(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/echo-binary") as ws:
        ws.send(BinaryMessage(data=b"\x00\x01\x02"))
        msg = ws.recv()
        assert msg == snapshot(BinaryMessage(data=b"echo:\x00\x01\x02"))


def test_multiple_messages(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        for i in range(5):
            ws.send(TextMessage(data=f"msg-{i}"))
        for i in range(5):
            msg = ws.recv()
            assert msg == TextMessage(data=f"echo:msg-{i}")


def test_async_iteration(ws_server: WebSocketTestServer):
    received: list[str] = []
    with connect_ws(f"{ws_server.url}/ws/send-then-close") as ws:
        for msg in ws:
            assert isinstance(msg, TextMessage)
            received.append(msg.data)

    assert received == snapshot(["first", "second", "third"])


def test_server_initiated_close(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/close-immediately") as ws:
        msg = ws.recv()
        assert msg == snapshot(CloseMessage(code=4001, reason="go away"))

        with pytest.raises(ConnectionClosed):
            ws.recv()
        assert ws.close_code == snapshot(4001)
        assert ws.close_reason == snapshot("go away")


def test_client_initiated_close(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        ws.send(TextMessage(data="ping"))
        ws.recv()
        ws.close(code=1000, reason="done")
        assert ws.close_code == snapshot(1000)
        assert ws.close_reason == snapshot("done")


def test_double_close_is_safe(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        ws.close()
        ws.close()


def test_text_and_binary_on_same_connection(ws_server: WebSocketTestServer):
    with connect_ws(f"{ws_server.url}/ws/echo-any") as ws:
        ws.send(TextMessage(data="hi"))
        msg = ws.recv()
        assert msg == snapshot(TextMessage(data="hi"))

        ws.send(BinaryMessage(data=b"bytes"))
        msg = ws.recv()
        assert msg == snapshot(BinaryMessage(data=b"bytes"))


def test_handshake_fails_for_non_ws_path(ws_server: WebSocketTestServer):
    with pytest.raises(RuntimeError, match="WebSocket handshake failed"):
        with connect_ws(f"{ws_server.url}/does-not-exist"):
            pass
