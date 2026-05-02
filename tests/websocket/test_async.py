import pytest
from inline_snapshot import snapshot

from tests.websocket.ws_server import WebSocketTestServer
from zapros.websocket import BinaryMessage, CloseMessage, ConnectionClosed, TextMessage, aconnect_ws


async def test_text_echo(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        await ws.send(TextMessage(data="hello"))
        msg = await ws.recv()
        assert msg == snapshot(TextMessage(data="echo:hello"))


async def test_binary_echo(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/echo-binary") as ws:
        await ws.send(BinaryMessage(data=b"\x00\x01\x02"))
        msg = await ws.recv()
        assert msg == snapshot(BinaryMessage(data=b"echo:\x00\x01\x02"))


async def test_multiple_messages(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        for i in range(5):
            await ws.send(TextMessage(data=f"msg-{i}"))
        for i in range(5):
            msg = await ws.recv()
            assert msg == TextMessage(data=f"echo:msg-{i}")


async def test_async_iteration(ws_server: WebSocketTestServer):
    received: list[str] = []
    async with aconnect_ws(f"{ws_server.url}/ws/send-then-close") as ws:
        async for msg in ws:
            assert isinstance(msg, TextMessage)
            received.append(msg.data)

    assert received == snapshot(["first", "second", "third"])


async def test_server_initiated_close(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/close-immediately") as ws:
        msg = await ws.recv()
        assert msg == snapshot(CloseMessage(code=4001, reason="go away"))

        with pytest.raises(ConnectionClosed):
            await ws.recv()
        assert ws.close_code == snapshot(4001)
        assert ws.close_reason == snapshot("go away")


async def test_client_initiated_close(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        await ws.send(TextMessage(data="ping"))
        await ws.recv()
        await ws.close(code=1000, reason="done")
        assert ws.close_code == snapshot(1000)
        assert ws.close_reason == snapshot("done")


async def test_double_close_is_safe(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/echo-text") as ws:
        await ws.close()
        await ws.close()


async def test_text_and_binary_on_same_connection(ws_server: WebSocketTestServer):
    async with aconnect_ws(f"{ws_server.url}/ws/echo-any") as ws:
        await ws.send(TextMessage(data="hi"))
        msg = await ws.recv()
        assert msg == snapshot(TextMessage(data="hi"))

        await ws.send(BinaryMessage(data=b"bytes"))
        msg = await ws.recv()
        assert msg == snapshot(BinaryMessage(data=b"bytes"))


async def test_handshake_fails_for_non_ws_path(ws_server: WebSocketTestServer):
    with pytest.raises(RuntimeError, match="WebSocket handshake failed"):
        async with aconnect_ws(f"{ws_server.url}/does-not-exist"):
            pass
