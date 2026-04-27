import pytest

from zapros import AsyncClient, Client, Request, Response
from zapros.matchers import Matcher
from zapros.mock import Mock, MockMiddleware, MockRouter


class UrlMatcher(Matcher):
    def __init__(self, expected_url: str) -> None:
        self.expected_url = expected_url

    def match(self, request: Request) -> bool:
        return str(request.url) == self.expected_url


@pytest.mark.parametrize(
    "base_url,endpoint,expected_url",
    [
        # --- Basic cases: trailing slash on base + relative endpoint ---
        pytest.param(
            "https://zapros.dev/api/",
            "test",
            "https://zapros.dev/api/test",
            id="base-with-trailing-slash-and-relative-endpoint",
        ),
        pytest.param(
            "https://zapros.dev/api/",
            "users/42",
            "https://zapros.dev/api/users/42",
            id="base-with-trailing-slash-and-nested-relative-endpoint",
        ),
        pytest.param(
            "https://zapros.dev/",
            "test",
            "https://zapros.dev/test",
            id="root-base-with-trailing-slash-and-relative-endpoint",
        ),
        pytest.param(
            "https://zapros.dev",
            "test",
            "https://zapros.dev/test",
            id="root-base-without-trailing-slash-and-relative-endpoint",
        ),
        # --- Base WITHOUT trailing slash: last segment gets replaced (WHATWG) ---
        pytest.param(
            "https://zapros.dev/api",
            "test",
            "https://zapros.dev/test",
            id="base-without-trailing-slash-replaces-last-segment",
        ),
        pytest.param(
            "https://zapros.dev/api/v1",
            "users",
            "https://zapros.dev/api/users",
            id="base-without-trailing-slash-replaces-only-last-segment",
        ),
        # --- Endpoint with leading slash = absolute path, replaces base path ---
        pytest.param(
            "https://zapros.dev/api/",
            "/test",
            "https://zapros.dev/test",
            id="absolute-path-endpoint-replaces-base-path",
        ),
        pytest.param(
            "https://zapros.dev/api/v1/users/",
            "/health",
            "https://zapros.dev/health",
            id="absolute-path-endpoint-discards-deep-base-path",
        ),
        # --- Empty endpoint resolves to base ---
        pytest.param(
            "https://zapros.dev/api/",
            "",
            "https://zapros.dev/api/",
            id="empty-endpoint-resolves-to-base",
        ),
        # --- Endpoint as fully-qualified URL replaces base entirely ---
        pytest.param(
            "https://zapros.dev/api/",
            "https://other.example/path",
            "https://other.example/path",
            id="absolute-url-endpoint-replaces-base-entirely",
        ),
        pytest.param(
            "https://zapros.dev/api/",
            "http://other.example/path",
            "http://other.example/path",
            id="absolute-url-endpoint-can-change-scheme",
        ),
        # --- Query strings ---
        pytest.param(
            "https://zapros.dev/api/",
            "users?id=42",
            "https://zapros.dev/api/users?id=42",
            id="endpoint-with-query-string",
        ),
        pytest.param(
            "https://zapros.dev/api/",
            "?id=42",
            "https://zapros.dev/api/?id=42",
            id="endpoint-as-query-only-keeps-base-path",
        ),
        # --- Fragments ---
        pytest.param(
            "https://zapros.dev/api/",
            "users#section",
            "https://zapros.dev/api/users#section",
            id="endpoint-with-fragment",
        ),
        # --- Dot segments ---
        pytest.param(
            "https://zapros.dev/api/v1/",
            "../v2/users",
            "https://zapros.dev/api/v2/users",
            id="endpoint-with-parent-dot-segment",
        ),
        pytest.param(
            "https://zapros.dev/api/",
            "./users",
            "https://zapros.dev/api/users",
            id="endpoint-with-current-dot-segment",
        ),
        # --- Port preservation ---
        pytest.param(
            "https://zapros.dev:8080/api/",
            "test",
            "https://zapros.dev:8080/api/test",
            id="base-with-port-is-preserved",
        ),
        # --- Base with query/fragment is dropped on merge ---
        pytest.param(
            "https://zapros.dev/api/?token=abc",
            "users",
            "https://zapros.dev/api/users",
            id="base-query-string-is-dropped-on-merge",
        ),
    ],
)
class TestBaseUrl:
    """
    Tests for base URL handling in AsyncClient and Client, ensuring that the base URL is correctly merged with request
    endpoints according to URL resolution rules. Covers various edge cases including
    trailing slashes, absolute paths, query strings, fragments, and port preservation.
    """

    async def test_async(  # unasync: generate @TestBaseUrl
        self,
        base_url: str,
        endpoint: str,
        expected_url: str,
    ) -> None:
        router = MockRouter()
        async with AsyncClient(MockMiddleware(router), base_url=base_url) as client:
            router.add(Mock.given(UrlMatcher(expected_url)).respond(Response(status=200)))
            response = await client.get(endpoint)
            assert response.status == 200

    def test_sync(  # unasync: generated @TestBaseUrl
        self,
        base_url: str,
        endpoint: str,
        expected_url: str,
    ) -> None:
        router = MockRouter()
        with Client(MockMiddleware(router), base_url=base_url) as client:
            router.add(Mock.given(UrlMatcher(expected_url)).respond(Response(status=200)))
            response = client.get(endpoint)
            assert response.status == 200
