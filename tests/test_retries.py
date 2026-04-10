import time

import pytest

from zapros import (
    URL,
    Request,
    Response,
)
from zapros._handlers._mock import (
    Mock as ZaprosMock,
    MockMiddleware,
    MockRouter,
)
from zapros._handlers._retries import (
    DEFAULT_RETRY_STATUS_CODES,
    SAFE_RETRY_METHODS,
    RetryMiddleware,
    RetryPolicy,
)
from zapros._models import Headers


def test_retry_on_503():
    router = MockRouter()
    ZaprosMock().respond(Response(status=503)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_retry_on_network_exception():
    router = MockRouter()
    ZaprosMock().callback(ConnectionError("Network error")).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_multiple_retries_until_success():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=4,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_retry_exhaustion_returns_last_response():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=503)).expect(3).mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 503
    mock.verify()


def test_retry_exhaustion_raises_last_exception():
    router = MockRouter()
    mock = ZaprosMock().callback(ConnectionError("Network error")).expect(3).mount(router)

    mock_handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        mock_handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )

    with pytest.raises(ConnectionError):
        retry_handler.handle(request)

    mock.verify()


def test_get_method_retries_on_500():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_post_method_does_not_retry():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=500)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "POST",
        text="body",
    )
    response = retry_handler.handle(request)

    assert response.status == 500
    mock.verify()


def test_put_method_retries():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "PUT",
        text="body",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_delete_method_retries():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "DELETE",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_retry_on_429_rate_limit():
    router = MockRouter()
    ZaprosMock().respond(Response(status=429)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_retry_on_502_bad_gateway():
    router = MockRouter()
    ZaprosMock().respond(Response(status=502)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_retry_on_504_gateway_timeout():
    router = MockRouter()
    ZaprosMock().respond(Response(status=504)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_no_retry_on_404():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=404)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 404
    mock.verify()


def test_no_retry_on_200():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    mock.verify()


def test_no_retry_on_301():
    router = MockRouter()
    mock = (
        ZaprosMock()
        .respond(
            Response(
                status=301,
                headers={"Location": "/other"},
            )
        )
        .once()
        .mount(router)
    )

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 301
    mock.verify()


def test_max_attempts_one_means_no_retry():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=500)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=1,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 500
    mock.verify()


def test_exponential_backoff_timing():
    timestamps = []

    def handle_with_timestamps(
        request: Request,
    ) -> Response:
        timestamps.append(time.time())
        if len(timestamps) < 3:
            return Response(
                status=500,
                headers=Headers({}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    ZaprosMock().callback(handle_with_timestamps).mount(router)
    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.1,
        backoff_jitter=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    assert len(timestamps) == 3

    delay1 = timestamps[1] - timestamps[0]
    delay2 = timestamps[2] - timestamps[1]

    assert 0.08 <= delay1 <= 0.15
    assert 0.15 <= delay2 <= 0.25


def test_backoff_max_cap():
    timestamps = []

    def handle_with_timestamps(
        request: Request,
    ) -> Response:
        timestamps.append(time.time())
        if len(timestamps) < 3:
            return Response(
                status=500,
                headers=Headers({}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    ZaprosMock().callback(handle_with_timestamps).mount(router)
    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=1.0,
        backoff_max=0.2,
        backoff_jitter=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200

    delay2 = timestamps[2] - timestamps[1]
    assert delay2 <= 0.25


def test_custom_retry_policy():
    class CustomRetryPolicy:
        def should_retry(
            self,
            *,
            request: Request,
            response: Response | None,
            error: Exception | None,
            attempt: int,
        ) -> bool:
            if response and response.status == 418:
                return True
            return False

    router = MockRouter()
    ZaprosMock().respond(Response(status=418)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        policy=CustomRetryPolicy(),
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "POST",
        text="body",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_custom_policy_overrides_defaults():
    class AlwaysRetryPolicy:
        def should_retry(
            self,
            *,
            request: Request,
            response: Response | None,
            error: Exception | None,
            attempt: int,
        ) -> bool:
            return True

    router = MockRouter()
    ZaprosMock().respond(Response(status=404)).once().mount(router)
    ZaprosMock().respond(Response(status=404)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        policy=AlwaysRetryPolicy(),
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_second_attempt_succeeds():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


async def test_async_retry_on_503():
    router = MockRouter()
    ZaprosMock().respond(Response(status=503)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = await retry_handler.ahandle(request)

    assert response.status == 200
    router.verify()


async def test_async_retry_on_network_exception():
    router = MockRouter()
    ZaprosMock().callback(ConnectionError("Network error")).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = await retry_handler.ahandle(request)

    assert response.status == 200
    router.verify()


async def test_async_post_does_not_retry():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=500)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "POST",
        text="body",
    )
    response = await retry_handler.ahandle(request)

    assert response.status == 500
    mock.verify()


async def test_async_exponential_backoff():
    timestamps = []

    def handle_with_timestamps(
        request: Request,
    ) -> Response:
        timestamps.append(time.time())
        if len(timestamps) < 3:
            return Response(
                status=500,
                headers=Headers({}),
                content=None,
            )
        return Response(
            status=200,
            headers=Headers({}),
            content=None,
        )

    router = MockRouter()
    ZaprosMock().callback(handle_with_timestamps).mount(router)
    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.1,
        backoff_jitter=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "GET",
    )
    response = await retry_handler.ahandle(request)

    assert response.status == 200
    assert len(timestamps) == 3

    delay1 = timestamps[1] - timestamps[0]
    delay2 = timestamps[2] - timestamps[1]

    assert 0.08 <= delay1 <= 0.15
    assert 0.15 <= delay2 <= 0.25


def test_retry_protocol_check():
    class CustomPolicy:
        def should_retry(
            self,
            *,
            request: Request,
            response: Response | None,
            error: Exception | None,
            attempt: int,
        ) -> bool:
            return False

    policy = CustomPolicy()
    assert isinstance(policy, RetryPolicy)


def test_default_constants():
    assert 429 in DEFAULT_RETRY_STATUS_CODES
    assert 500 in DEFAULT_RETRY_STATUS_CODES
    assert 502 in DEFAULT_RETRY_STATUS_CODES
    assert 503 in DEFAULT_RETRY_STATUS_CODES
    assert 504 in DEFAULT_RETRY_STATUS_CODES

    assert "GET" in SAFE_RETRY_METHODS
    assert "HEAD" in SAFE_RETRY_METHODS
    assert "PUT" in SAFE_RETRY_METHODS
    assert "DELETE" in SAFE_RETRY_METHODS
    assert "OPTIONS" in SAFE_RETRY_METHODS
    assert "TRACE" in SAFE_RETRY_METHODS
    assert "POST" not in SAFE_RETRY_METHODS
    assert "PATCH" not in SAFE_RETRY_METHODS


def test_head_method_retries():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "HEAD",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_options_method_retries():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "OPTIONS",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_trace_method_retries():
    router = MockRouter()
    ZaprosMock().respond(Response(status=500)).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "TRACE",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_patch_method_does_not_retry():
    router = MockRouter()
    mock = ZaprosMock().respond(Response(status=500)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "PATCH",
        text="body",
    )
    response = retry_handler.handle(request)

    assert response.status == 500
    mock.verify()


def test_post_retries_on_connection_error_before_transmission():
    router = MockRouter()
    ZaprosMock().callback(ConnectionError("Connection refused")).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "POST",
        text="body",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_post_retries_on_connection_refused_error():
    router = MockRouter()
    ZaprosMock().callback(ConnectionRefusedError("Connection refused")).once().mount(router)
    ZaprosMock().respond(Response(status=200)).once().mount(router)

    handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        handler,
        max_attempts=2,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "POST",
        text="body",
    )
    response = retry_handler.handle(request)

    assert response.status == 200
    router.verify()


def test_post_does_not_retry_on_read_timeout():
    class ReadTimeoutError(Exception):
        pass

    router = MockRouter()
    mock = ZaprosMock().callback(ReadTimeoutError("Read timeout")).once().mount(router)

    mock_handler = MockMiddleware(router)
    retry_handler = RetryMiddleware(
        mock_handler,
        max_attempts=3,
        backoff_factor=0.0,
    )

    request = Request(
        URL("https://example.com/"),
        "POST",
        text="body",
    )

    with pytest.raises(ReadTimeoutError):
        retry_handler.handle(request)

    mock.verify()
