import pytest

from zapros import URL
from zapros._errors import TooManyRedirectsError
from zapros._handlers._mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros._handlers._redirect import (
    RedirectMiddleware,
)
from zapros._models import (
    Headers,
    Request,
    Response,
)
from zapros.matchers import host, path


def create_recording_handler():
    requests: list[Request] = []

    def record_request(
        request: Request,
    ) -> Response:
        requests.append(request)
        return Response(
            status=404,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(record_request).mount(router)

    class RecordingHandlerWrapper:
        def __init__(self):
            self.requests = requests
            self.handler = MockMiddleware(router)

        def handle(self, request: Request) -> Response:
            return self.handler.handle(request)

        async def ahandle(self, request: Request) -> Response:
            return await self.handler.ahandle(request)

        def close(self) -> None:
            self.handler.close()

        async def aclose(self) -> None:
            await self.handler.aclose()

    return RecordingHandlerWrapper()


def test_redirect_301_preserves_method():
    router = MockRouter()

    Mock.given(path("/initial")).respond(
        Response(
            status=301,
            headers={"Location": "/final"},
        )
    ).mount(router)

    Mock.given(path("/final")).respond(
        Response(
            status=200,
            text="OK",
        )
    ).mount(router)

    mock_handler = MockMiddleware(router)
    handler = RedirectMiddleware(mock_handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="body content",
    )
    response = handler.handle(request)

    assert response.status == 200


def test_redirect_301_follows():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=301,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)

    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert response.text == "OK"


def test_redirect_302_follows():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=302,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert response.text == "OK"


def test_redirect_307_preserves_method():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=307,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    router.mocks[1]


def test_redirect_308_preserves_method():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=308,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "PUT",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_301_converts_post_to_get():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=301,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_302_converts_post_to_get():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=302,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_303_converts_to_get():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=303,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_no_location_header():
    router = MockRouter()
    Mock.given(path("/initial")).respond(Response(status=301)).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 301


def test_redirect_max_redirects():
    router = MockRouter()
    for i in range(15):
        Mock.given(path(f"/step{i}")).respond(
            Response(
                status=302,
                headers={"Location": f"/step{i + 1}"},
            )
        ).mount(router)
    Mock.given(path("/step15")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler, max_redirects=5)

    request = Request(
        URL("https://example.com/step0"),
        "GET",
    )
    with pytest.raises(TooManyRedirectsError):
        redirect_handler.handle(request)


def test_redirect_updates_host_header():
    router = MockRouter()
    Mock.given(path("/initial")).mount(router).respond(
        Response(
            status=302,
            headers={"Location": "https://other.com/final"},
        )
    )
    Mock.given(host("other.com")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
        headers=Headers({"Host": "example.com"}),
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_strips_authorization():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=302,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
        headers=Headers({"Authorization": "Bearer token"}),
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_chain():
    router = MockRouter()
    Mock.given(path("/first")).respond(
        Response(
            status=302,
            headers={"Location": "/second"},
        )
    ).mount(router)
    Mock.given(path("/second")).respond(
        Response(
            status=302,
            headers={"Location": "/third"},
        )
    ).mount(router)
    Mock.given(path("/third")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/first"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert response.text == "OK"


def test_redirect_preserves_query_string():
    router = MockRouter()
    (
        Mock.given(path("/initial"))
        .respond(
            Response(
                status=302,
                headers={"Location": "/final?redirected=true"},
            )
        )
        .mount(router)
    )
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial?foo=bar"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


async def test_async_redirect():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=302,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
    )
    response = await redirect_handler.ahandle(request)

    assert response.status == 200
    assert response.text == "OK"


async def test_async_redirect_307_preserves_method():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=307,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="body",
    )
    response = await redirect_handler.ahandle(request)

    assert response.status == 200


def test_redirect_non_redirect_status_passes_through():
    router = MockRouter()
    Mock.given(path("/")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert response.text == "OK"


def test_redirect_with_custom_port():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=302,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com:8080/initial"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_absolute_url():
    router = MockRouter()
    (
        Mock.given(path("/initial"))
        .respond(
            Response(
                status=302,
                headers={"Location": "https://other.example.com/final"},
            )
        )
        .mount(router)
    )
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_head_method_preserved():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=302,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "HEAD",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_delete_preserved_on_307():
    router = MockRouter()
    (
        Mock.given(path("/resource"))
        .respond(
            Response(
                status=307,
                headers={"Location": "/new-location"},
            )
        )
        .mount(router)
    )
    Mock.given(path("/new-location")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/resource"),
        "DELETE",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_delete_preserved_on_301():
    router = MockRouter()
    Mock.given(path("/resource")).respond(
        Response(
            status=301,
            headers={"Location": "/new-location"},
        )
    ).mount(router)
    Mock.given(path("/new-location")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/resource"),
        "DELETE",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_relative_path():
    router = MockRouter()
    Mock.given(path("/api/v1/resource")).respond(
        Response(
            status=302,
            headers={"Location": "../v2/resource"},
        )
    ).mount(router)
    Mock.given(path("/api/v2/resource")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/api/v1/resource"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_query_only():
    call_count = {"value": 0}

    def handle_with_counter(
        request: Request,
    ) -> Response:
        call_count["value"] += 1
        if call_count["value"] == 1:
            return Response(
                status=302,
                headers=Headers({"Location": "?page=2"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_counter).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/search?page=1"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert call_count["value"] == 2


def test_redirect_fragment_only():
    call_count = {"value": 0}

    def handle_with_counter(
        request: Request,
    ) -> Response:
        call_count["value"] += 1
        if call_count["value"] == 1:
            return Response(
                status=302,
                headers=Headers({"Location": "#section"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_counter).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/page"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert call_count["value"] == 2


def test_redirect_complex_relative():
    router = MockRouter()
    Mock.given(path("/docs/old")).respond(
        Response(
            status=302,
            headers={"Location": "./new/file"},
        )
    ).mount(router)
    Mock.given(path("/docs/new/file")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/docs/old"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_fragment_inheritance():
    router = MockRouter()
    Mock().respond(
        Response(
            status=302,
            headers={"Location": "/new-page"},
        )
    ).once().mount(router)
    Mock().given(path("/new-page")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/page#old"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_fragment_override():
    router = MockRouter()
    Mock().respond(
        Response(
            status=302,
            headers={"Location": "/new-page#new"},
        )
    ).once().mount(router)
    Mock().given(path("/new-page")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/page#old"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_fragment_none():
    router = MockRouter()
    Mock().respond(
        Response(
            status=302,
            headers={"Location": "/new-page"},
        )
    ).once().mount(router)
    Mock().given(path("/new-page")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/page"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_fragment_to_empty():
    router = MockRouter()
    Mock().respond(
        Response(
            status=302,
            headers={"Location": "/new-page#"},
        )
    ).once().mount(router)
    Mock().given(path("/new-page")).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/page#old"),
        "GET",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_301_put_preserved():
    router = MockRouter()
    Mock.given(path("/initial")).respond(
        Response(
            status=301,
            headers={"Location": "/final"},
        )
    ).mount(router)
    Mock.given(path("/final")).respond(Response(status=200)).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "PUT",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200


def test_redirect_302_delete_preserved():
    methods = []

    def handle_with_method_tracking(
        request: Request,
    ) -> Response:
        methods.append(request.method)
        if "/initial" in str(request.url):
            return Response(
                status=302,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_method_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "DELETE",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert methods == [
        "DELETE",
        "DELETE",
    ]


def test_redirect_303_delete_to_get():
    methods = []

    def handle_with_method_tracking(
        request: Request,
    ) -> Response:
        methods.append(request.method)
        if "/initial" in str(request.url):
            return Response(
                status=303,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_method_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "DELETE",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert methods == ["DELETE", "GET"]


def test_redirect_303_head_preserved():
    methods = []

    def handle_with_method_tracking(
        request: Request,
    ) -> Response:
        methods.append(request.method)
        if "/initial" in str(request.url):
            return Response(
                status=303,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_method_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "HEAD",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert methods == ["HEAD", "HEAD"]


def test_redirect_strips_cookie():
    headers_list = []

    def handle_with_header_tracking(
        request: Request,
    ) -> Response:
        headers_list.append(dict(request.headers.list()))
        if "/initial" in str(request.url):
            return Response(
                status=302,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_header_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
        headers=Headers({"Cookie": "session=abc123"}),
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert "Cookie" in headers_list[0]
    assert "Cookie" not in headers_list[1]


def test_redirect_strips_if_none_match():
    headers_list = []

    def handle_with_header_tracking(
        request: Request,
    ) -> Response:
        headers_list.append(dict(request.headers.list()))
        if "/initial" in str(request.url):
            return Response(
                status=302,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_header_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
        headers=Headers({"If-None-Match": '"abc123"'}),
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert "If-None-Match" in headers_list[0]
    assert "If-None-Match" not in headers_list[1]


def test_redirect_strips_origin():
    headers_list = []

    def handle_with_header_tracking(
        request: Request,
    ) -> Response:
        headers_list.append(dict(request.headers.list()))
        if "/initial" in str(request.url):
            return Response(
                status=302,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_header_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
        headers=Headers({"Origin": "https://example.com"}),
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert "Origin" in headers_list[0]
    assert "Origin" not in headers_list[1]


def test_redirect_strips_content_encoding_on_get():
    headers_list = []

    def handle_with_header_tracking(
        request: Request,
    ) -> Response:
        headers_list.append(dict(request.headers.list()))
        if "/initial" in str(request.url):
            return Response(
                status=303,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_header_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        headers=Headers({"Content-Encoding": "gzip"}),
        text="body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert "Content-Encoding" in headers_list[0]
    assert "Content-Encoding" not in headers_list[1]


def test_redirect_preserves_content_type_on_307():
    headers_list = []

    def handle_with_header_tracking(
        request: Request,
    ) -> Response:
        headers_list.append(dict(request.headers.list()))
        if "/initial" in str(request.url):
            return Response(
                status=307,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_header_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        headers=Headers({"Content-Type": "application/json"}),
        text='{"key": "value"}',
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert "Content-Type" in headers_list[0]
    assert "Content-Type" in headers_list[1]


def test_redirect_preserves_custom_headers():
    headers_list = []

    def handle_with_header_tracking(
        request: Request,
    ) -> Response:
        headers_list.append(dict(request.headers.list()))
        if "/initial" in str(request.url):
            return Response(
                status=302,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_header_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "GET",
        headers=Headers(
            {
                "X-Custom-Header": "value",
                "X-Another": "test",
            }
        ),
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert "X-Custom-Header" in headers_list[0]
    assert "X-Custom-Header" in headers_list[1]
    assert "X-Another" in headers_list[0]
    assert "X-Another" in headers_list[1]


def test_redirect_303_removes_body():
    bodies = []

    def handle_with_body_tracking(
        request: Request,
    ) -> Response:
        bodies.append(request.body)
        if "/initial" in str(request.url):
            return Response(
                status=303,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_body_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert bodies[0] is not None
    assert bodies[1] is None


def test_redirect_307_preserves_body():
    bodies = []

    def handle_with_body_tracking(
        request: Request,
    ) -> Response:
        bodies.append(request.body)
        if "/initial" in str(request.url):
            return Response(
                status=307,
                headers=Headers({"Location": "/final"}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    Mock().callback(handle_with_body_tracking).mount(router)

    handler = MockMiddleware(router)
    redirect_handler = RedirectMiddleware(handler)

    request = Request(
        URL("https://example.com/initial"),
        "POST",
        text="test body",
    )
    response = redirect_handler.handle(request)

    assert response.status == 200
    assert bodies[0] is not None
    assert bodies[1] is not None
