import gzip

import pytest

pytest.importorskip("pyreqwest", reason="pyreqwest is not supported for python 3.10 and below")
from inline_snapshot import snapshot
from pyreqwest.client import SyncClientBuilder

from tests.conftest import (
    MockServer,
)
from zapros import (
    BaseMiddleware,
    Client,
    PyreqwestHandler,
    StdNetworkHandler,
    Multipart,
    Part,
)
from zapros._handlers._cookies import (
    CookieHandler,
)


@pytest.fixture(
    params=["stdnetwork", "pyreqwest"],
    ids=lambda x: x,
)
def handler(request):
    handlers = {
        "stdnetwork": StdNetworkHandler,
        "pyreqwest": PyreqwestHandler,
    }

    handler = handlers[request.param]

    if request.param == "pyreqwest":
        return PyreqwestHandler(client=SyncClientBuilder())
    return handler()


def lowercase_headers(
    headers: dict[str, str],
) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def test_basic(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.get(
            f"{mock_server.url}/echo",
        )

        assert response.text() == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")

        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "121"})


def test_json_body(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.post(
            f"{mock_server.url}/echo",
            json={
                "key": "value",
                "num": 42,
            },
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 24\r
content-type: application/json\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
{"key":"value","num":42}\
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "198"})


def test_json_nested(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.post(
            f"{mock_server.url}/echo",
            json={
                "user": {
                    "name": "alice",
                    "age": 30,
                },
                "tags": ["a", "b"],
            },
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 51\r
content-type: application/json\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
{"user":{"name":"alice","age":30},"tags":["a","b"]}\
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "225"})


def test_form_body(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.post(
            f"{mock_server.url}/echo",
            form={
                "username": "alice",
                "password": "secret",
            },
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 30\r
content-type: application/x-www-form-urlencoded\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
username=alice&password=secret\
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "221"})


def test_form_url_encoding(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.post(
            f"{mock_server.url}/echo",
            form={"message": "hello world"},
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 19\r
content-type: application/x-www-form-urlencoded\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
message=hello+world\
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "210"})


@pytest.mark.xfail(reason="TODO: https://github.com/MarkusSintonen/pyreqwest/issues/24")
def test_multipart_body(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        mp = Multipart(boundary="test-boundary")
        mp.part("field1", Part.text("hello"))
        mp.part(
            "file",
            Part.bytes(b"file content").file_name("test.txt").mime_type("text/plain"),
        )

        response = client.post(
            f"{mock_server.url}/echo",
            multipart=mp,
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-type: multipart/form-data; boundary="test-boundary"\r
host: 127.0.0.1\r
transfer-encoding: chunked\r
user-agent: python-zapros/0.1.0\r
\r
--test-boundary\r
Content-Disposition: form-data; name="field1"\r
Content-Type: text/plain; charset=utf-8\r
\r
hello\r
--test-boundary\r
Content-Disposition: form-data; name="file"; filename="test.txt"\r
Content-Type: text/plain\r
\r
file content\r
--test-boundary--\r
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "475"})


@pytest.mark.xfail(reason="TODO: https://github.com/MarkusSintonen/pyreqwest/issues/24")
def test_multipart_multiple_fields(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        mp = Multipart(boundary="boundary-abc")
        mp.part("username", Part.text("bob"))
        mp.part(
            "email",
            Part.text("bob@example.com"),
        )
        mp.part(
            "avatar",
            Part.bytes(b"\x89PNG\r\n").file_name("avatar.png").mime_type("image/png"),
        )

        response = client.post(
            f"{mock_server.url}/echo",
            multipart=mp,
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-type: multipart/form-data; boundary="boundary-abc"\r
host: 127.0.0.1\r
transfer-encoding: chunked\r
user-agent: python-zapros/0.1.0\r
\r
--boundary-abc\r
Content-Disposition: form-data; name="username"\r
Content-Type: text/plain; charset=utf-8\r
\r
bob\r
--boundary-abc\r
Content-Disposition: form-data; name="email"\r
Content-Type: text/plain; charset=utf-8\r
\r
bob@example.com\r
--boundary-abc\r
Content-Disposition: form-data; name="avatar"; filename="avatar.png"\r
Content-Type: image/png\r
\r
�PNG\r
\r
--boundary-abc--\r
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "590"})


def test_bytes_body(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.post(
            f"{mock_server.url}/echo",
            body=b"raw binary data",
        )
        assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 15\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
raw binary data\
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "157"})


def test_query_params(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.get(
            f"{mock_server.url}/echo",
            params={
                "q": "hello",
                "page": "1",
            },
        )
        assert response.text() == snapshot("""\
GET /echo?q=hello&page=1 HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "136"})


def test_custom_headers(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.get(
            f"{mock_server.url}/echo",
            headers={
                "X-Custom-Header": "my-value",
                "Authorization": "Bearer token123",
            },
        )
        assert response.text() == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
authorization: Bearer token123\r
host: 127.0.0.1\r
user-agent: python-zapros\r
x-custom-header: my-value\r
\r
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "180"})


def test_put_method(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.put(
            f"{mock_server.url}/echo",
            json={"name": "updated"},
        )
        assert response.text() == snapshot("""\
PUT /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 18\r
content-type: application/json\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
{"name":"updated"}\
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "191"})


def test_delete_method(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.request(
            "DELETE",
            f"{mock_server.url}/echo",
        )
        assert response.text() == snapshot("""\
DELETE /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "124"})


def test_response_status(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        response = client.get(
            f"{mock_server.url}/echo",
        )
        assert response.status == snapshot(200)
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "121"})


def test_stream_context_manager(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        with client.stream(
            "GET",
            f"{mock_server.url}/echo",
        ) as response:
            assert response.status == snapshot(200)
            assert response.text() == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")
            assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "121"})


def test_stream_iter_bytes(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        with client.stream(
            "GET",
            f"{mock_server.url}/echo",
        ) as response:
            chunks = []
            for chunk in response.iter_bytes():
                chunks.append(chunk)
            assert b"".join(chunks) == snapshot(
                b"GET /echo HTTP/1.1\r\naccept: */*\r\naccept-encoding: zstd, br, gzip, deflate\r\nhost: 127.0.0.1\r\nuser-agent: python-zapros\r\n\r\n"  # noqa: E501
            )
            assert response.status == snapshot(200)
            assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "121"})


def test_stream_json_body(
    mock_server: MockServer,
    handler: BaseMiddleware,
):
    with Client(handler=handler) as client:
        with client.stream(
            "POST",
            f"{mock_server.url}/echo",
            json={"stream": True},
        ) as response:
            assert response.text() == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 15\r
content-type: application/json\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
{"stream":true}\
""")
            assert response.status == snapshot(200)
            assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "189"})


def test_gzip_raw_bytes_unchanged(
    mock_server: MockServer,
    mock_builder,
    request,
    handler: BaseMiddleware,
):
    original = b"hello from the server"
    compressed = gzip.compress(original)

    mock_builder.on("GET", "/data").with_body(compressed).with_header("Content-Encoding", "gzip")

    with Client(handler=handler) as client:
        with client.stream(
            "GET",
            f"{mock_server.url}/data",
            headers={"X-Pytest-Node-Id": request.node.nodeid},
        ) as response:
            chunks = []
            for chunk in response.iter_raw():
                chunks.append(chunk)

    assert b"".join(chunks) == compressed


def test_cookies_without_handler(
    mock_server: MockServer,
    mock_builder,
    request,
    handler: BaseMiddleware,
):
    mock_builder.on("GET", "/set-cookie").with_header(
        "Set-Cookie",
        "session=abc123; Path=/",
    )

    with Client(handler=handler) as client:
        response1 = client.get(
            f"{mock_server.url}/set-cookie",
            headers={"X-Pytest-Node-Id": request.node.nodeid},
        )
        assert response1.status == 200
        assert "set-cookie" in [k.lower() for k in response1.headers.keys()]

        response2 = client.get(
            f"{mock_server.url}/echo",
        )
        text = response2.text()
        assert "cookie:" not in text.lower()


def test_cookies_with_handler(
    mock_server: MockServer,
    mock_builder,
    request,
    handler: BaseMiddleware,
):
    mock_builder.on("GET", "/set-cookie").with_header(
        "Set-Cookie",
        "session=abc123; Path=/",
    )

    cookie_handler = CookieHandler(handler)

    with Client(handler=cookie_handler) as client:
        response1 = client.get(
            f"{mock_server.url}/set-cookie",
            headers={"X-Pytest-Node-Id": request.node.nodeid},
        )
        assert response1.status == 200
        assert "set-cookie" in [k.lower() for k in response1.headers.keys()]

        response2 = client.get(
            f"{mock_server.url}/echo",
        )
        text = response2.text()
        assert "cookie: session=abc123" in text.lower()


def test_with_websocket_upgrade(
    mock_server: MockServer,
    mock_builder,
    request,
    handler: BaseMiddleware,
):
    if isinstance(handler, PyreqwestHandler):
        pytest.skip("TODO: figure out how to support websocket upgrades in PyreqwestHandler")
    mock_builder.on("GET", "/ws").with_header(
        "Upgrade",
        "websocket",
    ).with_status(101)

    with Client(handler=handler) as client:
        response = client.get(
            f"{mock_server.url}/ws",
            headers={
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "X-Pytest-Node-Id": request.node.nodeid,
            },
        )
        assert response.status == 101
        assert lowercase_headers(dict(response.headers)) == snapshot({"content-length": "0", "upgrade": "websocket"})
        assert response.context.get("handoff", {}).get("network_stream") is not None
