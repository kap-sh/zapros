import re

import pytest

from zapros import URL
from zapros._handlers._mock import (
    Mock,
    MockMiddleware,
    MockRouter,
)
from zapros._models import (
    Headers,
    Request,
    Response,
)
from zapros.matchers import (
    and_,
    header,
    host,
    json,
    method,
    not_,
    or_,
    path,
    query,
)


def test_method_matcher():
    matcher = method("GET")
    request = Request(
        URL("https://example.com/path"),
        "GET",
    )
    assert matcher.match(request)

    request_post = Request(
        URL("https://example.com/path"),
        "POST",
    )
    assert not matcher.match(request_post)


def test_method_matcher_case_insensitive():
    matcher = method("get")
    request = Request(
        URL("https://example.com/path"),
        "GET",
    )
    assert matcher.match(request)


def test_path_matcher():
    matcher = path("/health")
    request = Request(
        URL("https://example.com/health"),
        "GET",
    )
    assert matcher.match(request)

    request_other = Request(
        URL("https://example.com/status"),
        "GET",
    )
    assert not matcher.match(request_other)


def test_path_matcher_with_regexp():
    matcher = path(re.compile(r"/user/.*"))
    request = Request(
        URL("https://example.com/user/42"),
        "GET",
    )
    assert matcher.match(request)

    request_other = Request(
        URL("https://example.com/status"),
        "GET",
    )
    assert not matcher.match(request_other)


def test_host_matcher():
    matcher = host("api.example.com")
    request = Request(
        URL("https://api.example.com/path"),
        "GET",
    )
    assert matcher.match(request)

    request_other = Request(
        URL("https://other.example.com/path"),
        "GET",
    )
    assert not matcher.match(request_other)


def test_header_matcher():
    matcher = header("x-api-key", "secret")
    headers = Headers({"x-api-key": "secret"})
    request = Request(
        URL("https://example.com/path"),
        "GET",
        headers=headers,
    )
    assert matcher.match(request)

    headers_wrong = Headers({"x-api-key": "wrong"})
    request_wrong = Request(
        URL("https://example.com/path"),
        "GET",
        headers=headers_wrong,
    )
    assert not matcher.match(request_wrong)


def test_query_matcher():
    matcher = query(page="2", limit="10")
    request = Request(
        URL("https://example.com/path?page=2&limit=10"),
        "GET",
    )
    assert matcher.match(request)

    request_missing = Request(
        URL("https://example.com/path?page=2"),
        "GET",
    )
    assert not matcher.match(request_missing)


def test_json_matcher():
    matcher = json(lambda data: data.get("name") == "test")
    request = Request(
        URL("https://example.com/path"),
        "POST",
        json={"name": "test"},
    )
    assert matcher.match(request)

    request_wrong = Request(
        URL("https://example.com/path"),
        "POST",
        json={"name": "other"},
    )
    assert not matcher.match(request_wrong)


def test_and_matcher():
    matcher = and_(method("GET"), path("/health"))
    request = Request(
        URL("https://example.com/health"),
        "GET",
    )
    assert matcher.match(request)

    request_wrong_method = Request(
        URL("https://example.com/health"),
        "POST",
    )
    assert not matcher.match(request_wrong_method)

    request_wrong_path = Request(
        URL("https://example.com/status"),
        "GET",
    )
    assert not matcher.match(request_wrong_path)


def test_or_matcher():
    matcher = or_(path("/health"), path("/status"))
    request_health = Request(
        URL("https://example.com/health"),
        "GET",
    )
    assert matcher.match(request_health)

    request_status = Request(
        URL("https://example.com/status"),
        "GET",
    )
    assert matcher.match(request_status)

    request_other = Request(
        URL("https://example.com/other"),
        "GET",
    )
    assert not matcher.match(request_other)


def test_not_matcher():
    matcher = not_(method("GET"))
    request_post = Request(
        URL("https://example.com/path"),
        "POST",
    )
    assert matcher.match(request_post)

    request_get = Request(
        URL("https://example.com/path"),
        "GET",
    )
    assert not matcher.match(request_get)


def test_mock_given_respond():
    mock = Mock.given(path("/health")).respond(
        Response(
            status=200,
            json={"status": "ok"},
        )
    )
    request = Request(
        URL("https://example.com/health"),
        "GET",
    )

    assert mock.matches(request)
    response = mock.handle(request)
    assert response.status == 200


def test_mock_and_chaining():
    mock = Mock.given(method("GET")).and_(path("/health")).respond(Response(status=200, text="OK"))
    request = Request(
        URL("https://example.com/health"),
        "GET",
    )
    assert mock.matches(request)

    request_wrong = Request(
        URL("https://example.com/health"),
        "POST",
    )
    assert not mock.matches(request_wrong)


def test_mock_respond_text():
    mock = Mock.given(path("/hello")).respond(Response(status=200, text="Hello World"))
    request = Request(
        URL("https://example.com/hello"),
        "GET",
    )
    response = mock.handle(request)

    assert response.status == 200
    assert response.headers.get("content-type") == "text/plain; charset=utf-8"
    assert response.headers.get("content-length") == "11"


def test_mock_respond_json():
    mock = Mock.given(path("/data")).respond(
        Response(
            status=200,
            json={"key": "value"},
        )
    )
    request = Request(
        URL("https://example.com/data"),
        "GET",
    )
    response = mock.handle(request)

    assert response.status == 200
    assert response.headers.get("content-type") == "application/json; charset=utf-8"


def test_mock_respond_with_headers():
    mock = Mock.given(path("/custom")).respond(
        Response(
            status=201,
            text="Created",
            headers={"x-custom": "header"},
        )
    )
    request = Request(
        URL("https://example.com/custom"),
        "GET",
    )
    response = mock.handle(request)

    assert response.status == 201
    assert response.headers.get("x-custom") == "header"


def test_mock_callback():
    from zapros._models import Response

    def custom_handler(
        req: Request,
    ) -> Response:
        status = 404 if req.url.pathname == "/notfound" else 200
        return Response(
            status=status,
            headers=Headers({}),
            content=None,
        )

    mock = Mock.given(method("GET")).callback(custom_handler)

    request_found = Request(
        URL("https://example.com/found"),
        "GET",
    )
    response_found = mock.handle(request_found)
    assert response_found.status == 200

    request_notfound = Request(
        URL("https://example.com/notfound"),
        "GET",
    )
    response_notfound = mock.handle(request_notfound)
    assert response_notfound.status == 404


def test_mock_expect():
    mock = Mock.given(path("/api")).respond(Response(status=200)).expect(2)
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    mock.handle(request)
    mock.handle(request)

    mock.verify()


def test_mock_tracks_calls():
    mock = Mock.given(path("/api")).respond(Response(status=200))
    first_request = Request(
        URL("https://example.com/api"),
        "GET",
    )
    second_request = Request(
        URL("https://example.com/api"),
        "POST",
    )

    assert not mock.called
    assert mock.call_count == 0

    mock.handle(first_request)
    mock.handle(second_request)

    assert mock.called
    assert mock.call_count == 2
    assert mock.calls == [first_request, second_request]


def test_mock_assert_called_helpers():
    mock = Mock.given(path("/api")).respond(Response(status=200))
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    with pytest.raises(AssertionError, match="Mock was not called"):
        mock.assert_called()

    mock.assert_not_called()

    mock.handle(request)

    mock.assert_called()
    mock.assert_called_once()

    with pytest.raises(AssertionError, match="Mock was unexpectedly called"):
        mock.assert_not_called()


def test_mock_assert_called_once_failure():
    mock = Mock.given(path("/api")).respond(Response(status=200)).name("API Mock")
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    with pytest.raises(AssertionError, match="API Mock expected 1 call, got 0"):
        mock.assert_called_once()

    mock.handle(request)
    mock.handle(request)

    with pytest.raises(AssertionError, match="API Mock expected 1 call, got 2"):
        mock.assert_called_once()


def test_mock_expect_failure():
    mock = Mock.given(path("/api")).respond(Response(status=200)).expect(2).name("API Mock")
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    mock.handle(request)

    with pytest.raises(
        AssertionError,
        match="API Mock: expected 2 calls, got 1",
    ):
        mock.verify()


def test_mock_once():
    mock = Mock.given(path("/api")).respond(Response(status=200)).once()
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    mock.handle(request)
    mock.verify()


def test_mock_never():
    mock = Mock.given(path("/api")).respond(Response(status=200)).never()
    mock.verify()


def test_mock_never_failure():
    mock = Mock.given(path("/api")).respond(Response(status=200)).never()
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    mock.handle(request)

    with pytest.raises(
        AssertionError,
        match="expected 0 calls, got 1",
    ):
        mock.verify()


def test_mock_reset():
    mock = Mock.given(path("/api")).respond(Response(status=200)).once()
    request = Request(
        URL("https://example.com/api"),
        "GET",
    )

    mock.handle(request)
    mock.verify()

    mock.reset()

    assert not mock.called
    assert mock.call_count == 0

    with pytest.raises(AssertionError):
        mock.verify()


def test_router_add_and_dispatch():
    router = MockRouter()
    mock1 = Mock.given(path("/health")).respond(Response(status=200, text="OK"))
    mock2 = Mock.given(path("/status")).respond(
        Response(
            status=200,
            json={"status": "up"},
        )
    )

    router.add(mock1).add(mock2)

    request_health = Request(
        URL("https://example.com/health"),
        "GET",
    )
    response = router.dispatch(request_health)
    assert response is not None
    assert response.status == 200

    request_status = Request(
        URL("https://example.com/status"),
        "GET",
    )
    response = router.dispatch(request_status)
    assert response is not None
    assert response.status == 200


def test_router_dispatch_no_match():
    router = MockRouter()
    mock = Mock.given(path("/health")).respond(Response(status=200))
    router.add(mock)

    request = Request(
        URL("https://example.com/notfound"),
        "GET",
    )
    response = router.dispatch(request)
    assert response is None


def test_router_dispatch_first_match():
    router = MockRouter()
    mock1 = Mock.given(path("/api")).respond(Response(status=200, text="First"))
    mock2 = Mock.given(path("/api")).respond(Response(status=200, text="Second"))

    router.add(mock1).add(mock2)

    request = Request(
        URL("https://example.com/api"),
        "GET",
    )
    response = router.dispatch(request)
    assert response is not None
    assert response.status == 200


def test_router_verify():
    router = MockRouter()
    mock1 = Mock.given(path("/health")).respond(Response(status=200)).once()
    mock2 = Mock.given(path("/status")).respond(Response(status=200)).never()

    router.add(mock1).add(mock2)

    request = Request(
        URL("https://example.com/health"),
        "GET",
    )
    router.dispatch(request)

    router.verify()


def test_router_verify_failure():
    router = MockRouter()
    mock = Mock.given(path("/api")).respond(Response(status=200)).once()
    router.add(mock)

    with pytest.raises(AssertionError):
        router.verify()


def test_router_reset():
    router = MockRouter()
    mock = Mock.given(path("/api")).respond(Response(status=200)).once()
    router.add(mock)

    request = Request(
        URL("https://example.com/api"),
        "GET",
    )
    router.dispatch(request)
    router.verify()

    router.reset()

    with pytest.raises(AssertionError):
        router.verify()


def test_complex_matcher_combination():
    matcher = and_(
        method("POST"),
        or_(
            path("/users"),
            path("/accounts"),
        ),
        header(
            "content-type",
            "application/json",
        ),
    )

    request_users = Request(
        URL("https://example.com/users"),
        "POST",
        headers=Headers({"content-type": "application/json"}),
    )
    assert matcher.match(request_users)

    request_accounts = Request(
        URL("https://example.com/accounts"),
        "POST",
        headers=Headers({"content-type": "application/json"}),
    )
    assert matcher.match(request_accounts)

    request_wrong_path = Request(
        URL("https://example.com/other"),
        "POST",
        headers=Headers({"content-type": "application/json"}),
    )
    assert not matcher.match(request_wrong_path)

    request_wrong_method = Request(
        URL("https://example.com/users"),
        "GET",
        headers=Headers({"content-type": "application/json"}),
    )
    assert not matcher.match(request_wrong_method)


def test_helper_functions():
    m = method("GET")
    request = Request(
        URL("https://example.com/path"),
        "GET",
    )
    assert m.match(request)

    p = path("/health")
    request = Request(
        URL("https://example.com/health"),
        "GET",
    )
    assert p.match(request)

    h = host("api.example.com")
    request = Request(
        URL("https://api.example.com/path"),
        "GET",
    )
    assert h.match(request)


def test_chaining_with_helper_functions():
    matcher = path("/api").method("POST").host("api.example.com")

    request = Request(
        URL("https://api.example.com/api"),
        "POST",
    )
    assert matcher.match(request)

    request_wrong_method = Request(
        URL("https://api.example.com/api"),
        "GET",
    )
    assert not matcher.match(request_wrong_method)

    request_wrong_host = Request(
        URL("https://other.example.com/api"),
        "POST",
    )
    assert not matcher.match(request_wrong_host)


def test_chaining_with_query_and_header():
    matcher = (
        path("/search")
        .query(q="test", page="1")
        .header(
            "authorization",
            "Bearer token",
        )
    )

    request = Request(
        URL("https://example.com/search?q=test&page=1"),
        "GET",
        headers=Headers({"authorization": "Bearer token"}),
    )
    assert matcher.match(request)

    request_wrong_query = Request(
        URL("https://example.com/search?q=test"),
        "GET",
        headers=Headers({"authorization": "Bearer token"}),
    )
    assert not matcher.match(request_wrong_query)


def test_chaining_with_and_or():
    matcher = method("GET").and_(
        or_(
            path("/health"),
            path("/status"),
        )
    )

    request_health = Request(
        URL("https://example.com/health"),
        "GET",
    )
    assert matcher.match(request_health)

    request_status = Request(
        URL("https://example.com/status"),
        "GET",
    )
    assert matcher.match(request_status)

    request_other = Request(
        URL("https://example.com/other"),
        "GET",
    )
    assert not matcher.match(request_other)


def test_mock_with_chainedmatchers():
    mock = (
        Mock.given(
            path("/api/users")
            .method("POST")
            .header(
                "content-type",
                "application/json",
            )
        )
        .respond(Response(status=201, json={"id": 123}))
        .once()
    )

    request = Request(
        URL("https://example.com/api/users"),
        "POST",
        headers=Headers({"content-type": "application/json"}),
    )
    assert mock.matches(request)
    response = mock.handle(request)
    assert response.status == 201
    mock.verify()


def test_router_with_chainedmatchers():
    router = MockRouter()
    mock1 = Mock.given(method("GET").path("/health")).respond(Response(status=200, text="OK"))
    mock2 = Mock.given(method("GET").path("/status")).respond(
        Response(
            status=200,
            json={"status": "up"},
        )
    )

    router.add(mock1).add(mock2)

    request_health = Request(
        URL("https://example.com/health"),
        "GET",
    )
    response = router.dispatch(request_health)
    assert response is not None
    assert response.status == 200


def test_given_standalone_function():
    mock = Mock.given(path("/api").method("POST")).respond(
        Response(
            status=201,
            json={"created": True},
        )
    )

    request = Request(
        URL("https://example.com/api"),
        "POST",
    )
    assert mock.matches(request)
    response = mock.handle(request)
    assert response.status == 201


def test_mount_method():
    router = MockRouter()
    Mock.given(path("/health")).respond(Response(status=200, text="OK")).mount(router)

    request = Request(
        URL("https://example.com/health"),
        "GET",
    )
    response = router.dispatch(request)
    assert response is not None
    assert response.status == 200


def test_fluent_api_complete():
    router = MockRouter()

    Mock.given(path("/api/users").method("GET")).respond(Response(status=200, json=[])).once().mount(router)

    Mock.given(path("/api/users").method("POST")).respond(Response(status=201, json={"id": 1})).once().mount(router)

    request_get = Request(
        URL("https://example.com/api/users"),
        "GET",
    )
    response_get = router.dispatch(request_get)
    assert response_get is not None
    assert response_get.status == 200

    request_post = Request(
        URL("https://example.com/api/users"),
        "POST",
    )
    response_post = router.dispatch(request_post)
    assert response_post is not None
    assert response_post.status == 201

    router.verify()


def test_mock_callback_exception_instance():
    mock = Mock.given(path("/error")).callback(ValueError("something went wrong"))
    request = Request(
        URL("https://example.com/error"),
        "GET",
    )

    with pytest.raises(
        ValueError,
        match="something went wrong",
    ):
        mock.handle(request)


def test_mock_callback_exception_class():
    mock = Mock.given(path("/error")).callback(ValueError)
    request = Request(
        URL("https://example.com/error"),
        "GET",
    )

    with pytest.raises(ValueError):
        mock.handle(request)


async def test_async_mock_handler_dispatch():
    router = MockRouter()
    Mock.given(path("/health")).respond(Response(status=200, text="OK")).mount(router)
    Mock.given(path("/api").method("POST")).respond(
        Response(
            status=201,
            json={"created": True},
        )
    ).mount(router)

    handler = MockMiddleware(router)

    request_health = Request(
        URL("https://example.com/health"),
        "GET",
    )
    response = await handler.ahandle(request_health)
    assert response.status == 200

    request_api = Request(
        URL("https://example.com/api"),
        "POST",
    )
    response = await handler.ahandle(request_api)
    assert response.status == 201


async def test_async_mock_handler_no_match():
    router = MockRouter()
    Mock.given(path("/health")).respond(Response(status=200, text="OK")).mount(router)

    handler = MockMiddleware(router)

    request = Request(
        URL("https://example.com/notfound"),
        "GET",
    )
    with pytest.raises(
        ValueError,
        match="No mock matched request: GET /notfound",
    ):
        await handler.ahandle(request)


async def test_async_mock_handler_with_fallback():
    fallback_router = MockRouter()
    Mock().callback(
        lambda request: Response(
            status=404,
            headers=Headers({}),
            content=None,
        )
    ).mount(fallback_router)

    router = MockRouter()
    Mock.given(path("/health")).respond(Response(status=200, text="OK")).mount(router)

    fallback = MockMiddleware(fallback_router)
    handler = MockMiddleware(router, next_handler=fallback)

    request = Request(
        URL("https://example.com/notfound"),
        "GET",
    )
    response = await handler.ahandle(request)
    assert response.status == 404
