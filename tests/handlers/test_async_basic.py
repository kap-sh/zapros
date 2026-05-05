import gzip
from typing import TYPE_CHECKING

import pytest
from inline_snapshot import snapshot

from tests.mock_server import AsyncMockServer

if TYPE_CHECKING:
    from pyreqwest.client import ClientBuilder
else:
    try:
        from pyreqwest.client import ClientBuilder
    except ImportError:
        ClientBuilder = None


from zapros import (
    AsyncBaseMiddleware,
    AsyncClient,
    AsyncPyreqwestHandler,
    AsyncStdNetworkHandler,
    Multipart,
    Part,
)

CASES = [
    pytest.param(("stdnetwork", "asyncio"), id="stdnetwork-asyncio"),
    pytest.param(("stdnetwork", ("asyncio", {"use_uvloop": True})), id="stdnetwork-asyncio-uvloop"),
    pytest.param(("stdnetwork", "trio"), id="stdnetwork-trio"),
    pytest.param(("pyreqwest", "asyncio"), id="pyreqwest-asyncio"),
    pytest.param(("pyreqwest", ("asyncio", {"use_uvloop": True})), id="pyreqwest-asyncio-uvloop"),
]


@pytest.fixture(params=CASES)
def case(request):
    return request.param


@pytest.fixture
def handler_kind(case):
    return case[0]


@pytest.fixture
def anyio_backend(case):
    return case[1]


@pytest.fixture
def handler(handler_kind):
    if handler_kind == "pyreqwest":
        if ClientBuilder is None:
            pytest.skip("pyreqwest is not supported for python 3.10 and below")
        return AsyncPyreqwestHandler(client=ClientBuilder())
    return AsyncStdNetworkHandler()


def strip_date_header(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() != "date"}


def lowercase_headers(
    headers: dict[str, str],
) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


async def test_basic(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            f"{mock_server.url}/echo",
        )

        assert response.text == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")

        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {
                "server": "uvicorn",
                "content-type": "text/plain; charset=utf-8",
                "content-length": "121",
            }
        )


async def test_json_body(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            json={
                "key": "value",
                "num": 42,
            },
        )
        assert response.text == snapshot("""\
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
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "198"}
        )


async def test_json_nested(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            json={
                "user": {
                    "name": "alice",
                    "age": 30,
                },
                "tags": ["a", "b"],
            },
        )
        assert response.text == snapshot("""\
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
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "225"}
        )


async def test_form_body(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            form={
                "username": "alice",
                "password": "secret",
            },
        )
        assert response.text == snapshot("""\
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
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "221"}
        )


async def test_form_url_encoding(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            form={"message": "hello world"},
        )
        assert response.text == snapshot("""\
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
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "210"}
        )


@pytest.mark.xfail(reason="TODO: https://github.com/MarkusSintonen/pyreqwest/issues/24")
async def test_multipart_body(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        mp = Multipart(boundary="test-boundary")
        mp.part("field1", Part.text("hello"))
        mp.part(
            "file",
            Part.bytes(b"file content").file_name("test.txt").mime_type("text/plain"),
        )

        response = await client.post(
            f"{mock_server.url}/echo",
            multipart=mp,
        )
        assert response.text == snapshot("""\
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
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot({"content-length": "475"})


@pytest.mark.xfail(reason="TODO: https://github.com/MarkusSintonen/pyreqwest/issues/24")
async def test_multipart_multiple_fields(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
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

        response = await client.post(
            f"{mock_server.url}/echo",
            multipart=mp,
        )
        assert response.text == snapshot("""\
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
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot({"content-length": "590"})


async def test_bytes_body(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.post(
            f"{mock_server.url}/echo",
            body=b"raw binary data",
        )
        assert response.text == snapshot("""\
POST /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
content-length: 15\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
raw binary data\
""")
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "157"}
        )


async def test_query_params(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            f"{mock_server.url}/echo",
            params={
                "q": "hello",
                "page": "1",
            },
        )
        assert response.text == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "121"}
        )


async def test_custom_headers(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            f"{mock_server.url}/echo",
            headers={
                "X-Custom-Header": "my-value",
                "Authorization": "Bearer token123",
            },
        )
        assert response.text == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
authorization: Bearer token123\r
host: 127.0.0.1\r
user-agent: python-zapros\r
x-custom-header: my-value\r
\r
""")
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "180"}
        )


async def test_put_method(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.put(
            f"{mock_server.url}/echo",
            json={"name": "updated"},
        )
        assert response.text == snapshot("""\
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
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "191"}
        )


async def test_delete_method(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.request(
            "DELETE",
            f"{mock_server.url}/echo",
        )
        assert response.text == snapshot("""\
DELETE /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "124"}
        )


async def test_response_status(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            f"{mock_server.url}/echo",
        )
        assert response.status == snapshot(201)
        assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
            {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "121"}
        )


async def test_stream_context_manager(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        async with client.stream(
            "GET",
            f"{mock_server.url}/echo",
        ) as response:
            assert response.status == snapshot(201)
            await response.aread()
            assert response.text == snapshot("""\
GET /echo HTTP/1.1\r
accept: */*\r
accept-encoding: zstd, br, gzip, deflate\r
host: 127.0.0.1\r
user-agent: python-zapros\r
\r
""")
            assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
                {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "121"}
            )


async def test_stream_iter_bytes(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        async with client.stream(
            "GET",
            f"{mock_server.url}/echo",
        ) as response:
            chunks = []
            async for chunk in response.async_iter_bytes():
                chunks.append(chunk)
            assert b"".join(chunks) == snapshot(
                b"GET /echo HTTP/1.1\r\naccept: */*\r\naccept-encoding: zstd, br, gzip, deflate\r\nhost: 127.0.0.1\r\nuser-agent: python-zapros\r\n\r\n"  # noqa: E501
            )
            assert response.status == snapshot(201)
            assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
                {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "121"}
            )


async def test_stream_json_body(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    async with AsyncClient(handler=handler) as client:
        async with client.stream(
            "POST",
            f"{mock_server.url}/echo",
            json={"stream": True},
        ) as response:
            await response.aread()
            assert response.text == snapshot("""\
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
            assert response.status == snapshot(201)
            assert strip_date_header(lowercase_headers(dict(response.headers))) == snapshot(
                {"server": "uvicorn", "content-type": "text/plain; charset=utf-8", "content-length": "189"}
            )


async def test_gzip_raw_bytes_unchanged(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    original = "hello from the server"

    async with AsyncClient(handler=handler) as client:
        async with client.stream("GET", f"{mock_server.url}/gzip", params={"data": original}) as response:
            chunks = []
            async for chunk in response.async_iter_raw():
                chunks.append(chunk)

    assert b"".join(chunks) == gzip.compress(original.encode())


async def test_with_websocket_upgrade(
    mock_server: AsyncMockServer,
    handler: AsyncBaseMiddleware,
):
    if isinstance(handler, AsyncPyreqwestHandler):
        pytest.skip("TODO: figure out how to support websocket upgrades in AsyncPyreqwestHandler")

    async with AsyncClient(handler=handler) as client:
        response = await client.get(
            f"{mock_server.url}/ws",
            headers={
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                "Sec-WebSocket-Version": "13",
            },
        )
        assert response.status == 101

        response_headers = {
            k: v for k, v in response.headers.items() if k.lower() not in {"date", "sec-websocket-accept"}
        }
        assert lowercase_headers(response_headers) == snapshot(
            {"upgrade": "websocket", "connection": "Upgrade", "server": "uvicorn"}
        )
        assert response.context.get("handoff", {}).get("network_stream") is not None
