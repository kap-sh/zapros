from http import HTTPStatus

import pytest

from zapros._models import Response


@pytest.mark.parametrize(
    "status",
    [
        HTTPStatus.OK,
        HTTPStatus.CREATED,
        HTTPStatus.ACCEPTED,
        HTTPStatus.NON_AUTHORITATIVE_INFORMATION,
        HTTPStatus.NO_CONTENT,
        HTTPStatus.RESET_CONTENT,
        HTTPStatus.PARTIAL_CONTENT,
        HTTPStatus.MULTI_STATUS,
        HTTPStatus.ALREADY_REPORTED,
        HTTPStatus.IM_USED,
    ],
)
async def test_is_success_response(status: HTTPStatus) -> None:
    response = Response(status=status)
    assert response.is_success


@pytest.mark.parametrize(
    "status",
    [
        HTTPStatus.MULTIPLE_CHOICES,
        HTTPStatus.MOVED_PERMANENTLY,
        HTTPStatus.FOUND,
        HTTPStatus.SEE_OTHER,
        HTTPStatus.NOT_MODIFIED,
        HTTPStatus.USE_PROXY,
        HTTPStatus.TEMPORARY_REDIRECT,
        HTTPStatus.PERMANENT_REDIRECT,
    ],
)
async def test_is_redirect_response(status: HTTPStatus) -> None:
    response = Response(status=status)
    assert response.is_redirection


@pytest.mark.parametrize(
    "status",
    [
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.PAYMENT_REQUIRED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.METHOD_NOT_ALLOWED,
        HTTPStatus.NOT_ACCEPTABLE,
        HTTPStatus.PROXY_AUTHENTICATION_REQUIRED,
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.CONFLICT,
        HTTPStatus.GONE,
        HTTPStatus.LENGTH_REQUIRED,
        HTTPStatus.PRECONDITION_FAILED,
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        HTTPStatus.REQUEST_URI_TOO_LONG,
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
        HTTPStatus.EXPECTATION_FAILED,
        HTTPStatus.IM_A_TEAPOT,
        HTTPStatus.MISDIRECTED_REQUEST,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        HTTPStatus.LOCKED,
        HTTPStatus.FAILED_DEPENDENCY,
        HTTPStatus.TOO_EARLY,
        HTTPStatus.UPGRADE_REQUIRED,
        HTTPStatus.PRECONDITION_REQUIRED,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE,
        HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS,
    ],
)
async def test_is_client_error(status: HTTPStatus) -> None:
    response = Response(status=status)
    assert response.is_error
    assert response.is_client_error


@pytest.mark.parametrize(
    "status",
    [
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.NOT_IMPLEMENTED,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
        HTTPStatus.HTTP_VERSION_NOT_SUPPORTED,
        HTTPStatus.VARIANT_ALSO_NEGOTIATES,
        HTTPStatus.INSUFFICIENT_STORAGE,
        HTTPStatus.LOOP_DETECTED,
        HTTPStatus.NOT_EXTENDED,
        HTTPStatus.NETWORK_AUTHENTICATION_REQUIRED,
    ],
)
async def test_is_server_error(status: HTTPStatus) -> None:
    response = Response(status=status)
    assert response.is_error
    assert response.is_server_error
