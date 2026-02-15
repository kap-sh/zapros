from datetime import (
    datetime,
    timedelta,
    timezone,
)
from email.utils import format_datetime
from typing import (
    AsyncIterator,
    Iterator,
)

from zapros import AsyncClient
from zapros._handlers._mock import (
    Mock,
    MockRouter,
)
from zapros._models import (
    Request,
    Response,
)
from zapros.matchers import path


class _BytesStream(
    AsyncIterator[bytes],
    Iterator[bytes],
):
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._sent = False

    def __iter__(
        self,
    ) -> "_BytesStream":
        return self

    def __next__(self) -> bytes:
        if self._sent:
            raise StopIteration
        self._sent = True
        return self._data

    def __aiter__(
        self,
    ) -> "_BytesStream":
        return self

    async def __anext__(self) -> bytes:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return self._data


def make_echo_response(
    req: Request,
) -> Response:
    cookie_header = req.headers.get("Cookie", "")
    body = f"cookie: {cookie_header}" if cookie_header else "no cookie"
    body_bytes = body.encode("utf-8")
    return Response(
        status=200,
        headers={
            "content-type": "text/plain",
            "content-length": str(len(body_bytes)),
        },
        content=_BytesStream(body_bytes),
    )


async def test_basic_cookie_set_and_send(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client

    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200
    assert "set-cookie" in [k.lower() for k in response1.headers.keys()]

    response2 = await client.get(
        "http://example.com/echo",
    )
    text = await response2.atext()
    assert "cookie: session=abc123" in text.lower()


async def test_cookie_with_max_age_attribute(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = await response2.atext()
    assert "cookie: session=abc123" in text.lower()


async def test_cookie_with_secure_attribute_http_not_sent(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/; Secure"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = await response2.atext()
    assert "cookie:" not in text.lower()


async def test_cookie_with_httponly_attribute(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/; HttpOnly"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = await response2.atext()
    assert "cookie: session=abc123" in text.lower()


async def test_multiple_cookies_in_response(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookies")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/set-cookies2")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "user=john; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookies",
    )
    assert response1.status == 200
    await client.get(
        "http://example.com/set-cookies2",
    )

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "session=abc123" in text
    assert "user=john" in text


async def test_cookie_header_not_include_attributes(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "session=abc123" in text
    assert "domain=" not in text
    assert "expires=" not in text
    assert "secure" not in text
    assert "httponly" not in text


async def test_cookie_path_matching_exact(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/api/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/api"},
        )
    ).mount(router)

    Mock.given(path("/api/data")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/api/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get(
        "http://example.com/api/data",
    )
    text = (await response2.atext()).lower()
    assert "cookie: session=abc123" in text


async def test_cookie_path_mismatch_not_sent(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/api/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/api"},
        )
    ).mount(router)

    Mock.given(path("/other")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/api/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get(
        "http://example.com/other",
    )
    text = (await response2.atext()).lower()
    assert "cookie:" not in text


async def test_cookie_default_path(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/api")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123"},
        )
    ).mount(router)

    Mock.given(path("/api/data")).callback(make_echo_response).mount(router)

    response1 = await client.get("http://example.com/api")
    assert response1.status == 200

    response2 = await client.get(
        "http://example.com/api/data",
    )
    text = (await response2.atext()).lower()
    assert "cookie: session=abc123" in text


async def test_cookie_replacement_same_name_domain_path(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie1")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=oldvalue; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/set-cookie2")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=newvalue; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    await client.get(
        "http://example.com/set-cookie1",
    )
    await client.get(
        "http://example.com/set-cookie2",
    )

    response = await client.get("http://example.com/echo")
    text = (await response.atext()).lower()
    assert "session=newvalue" in text
    assert "oldvalue" not in text


async def test_cookie_special_characters_in_value(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "token=abc%20123%40def; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "token=abc%20123%40def" in text


async def test_cookie_empty_value(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "session=" in text


async def test_cookie_max_age_zero_expires_cookie(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/; Max-Age=0"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "cookie:" not in text


async def test_cookie_persists_across_multiple_requests(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/login")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/profile")).callback(make_echo_response).mount(router)
    Mock.given(path("/settings")).callback(make_echo_response).mount(router)
    Mock.given(path("/logout")).callback(make_echo_response).mount(router)

    await client.get(
        "http://example.com/login",
    )

    for path_val in [
        "/profile",
        "/settings",
        "/logout",
    ]:
        response = await client.get(
            f"http://example.com{path_val}",
        )
        text = (await response.atext()).lower()
        assert "cookie: session=abc123" in text


async def test_different_cookies_for_different_paths(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/path1")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "cookie1=value1; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/path2")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "cookie2=value2; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    await client.get(
        "http://example.com/path1",
    )
    await client.get(
        "http://example.com/path2",
    )

    response = await client.get("http://example.com/echo")
    text = (await response.atext()).lower()
    assert "cookie1=value1" in text
    assert "cookie2=value2" in text


async def test_cookie_without_handler_not_sent(
    async_mock_client_no_cookies: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client_no_cookies
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200
    assert "set-cookie" in [k.lower() for k in response1.headers.keys()]

    response2 = await client.get("http://example.com/echo")
    text = await response2.atext()
    assert "cookie:" not in text.lower()


async def test_cookie_path_prefix_with_trailing_slash_matches_subpath(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/api/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/api/"},
        )
    ).mount(router)

    Mock.given(path("/api/sub/path")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/api/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get(
        "http://example.com/api/sub/path",
    )
    text = (await response2.atext()).lower()
    assert "cookie: session=abc123" in text


async def test_cookie_path_prefix_without_trailing_slash_matches_exact(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/api/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/api"},
        )
    ).mount(router)

    Mock.given(path("/apiother")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/api/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get(
        "http://example.com/apiother",
    )
    text = (await response2.atext()).lower()
    assert "cookie:" not in text


async def test_cookie_session_cookie(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    await client.get(
        "http://example.com/set-cookie",
    )

    response = await client.get("http://example.com/echo")
    text = (await response.atext()).lower()
    assert "session=abc123" in text


async def test_cookie_with_expires_in_future(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client

    expires = format_datetime(
        datetime.now(timezone.utc) + timedelta(days=30),
        usegmt=True,
    )

    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={
                "Set-Cookie": f"session=abc123; Path=/; Expires={expires}",
            },
        )
    ).once().mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).once().mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    assert response2.status == 200

    text = await response2.atext()
    assert "cookie: session=abc123" in text.lower()


async def test_cookie_with_expires_in_past(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/; Expires=Wed, 09 Jun 2020 10:18:14 GMT"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "cookie:" not in text


async def test_cookie_same_site_attribute(
    async_mock_client: tuple[AsyncClient, MockRouter],
) -> None:
    client, router = async_mock_client
    Mock.given(path("/set-cookie")).respond(
        Response(
            status=200,
            text="ok",
            headers={"Set-Cookie": "session=abc123; Path=/; SameSite=Strict"},
        )
    ).mount(router)

    Mock.given(path("/echo")).callback(make_echo_response).mount(router)

    response1 = await client.get(
        "http://example.com/set-cookie",
    )
    assert response1.status == 200

    response2 = await client.get("http://example.com/echo")
    text = (await response2.atext()).lower()
    assert "cookie: session=abc123" in text
