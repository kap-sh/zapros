from __future__ import annotations

import base64

from pywhatwgurl import URL

from zapros._errors import TotalTimeoutError
from zapros._handlers._common import remaining_timeout
from zapros._headers import Connection

from ..._models import Headers, Request


class BrokenConnectionError(ConnectionError):
    """
    Raised when a connection from the pool which was expected to be alive is
    found to be closed or otherwise unusable. This can happen when the server
    closes an idle connection, and the client tries to reuse it from the pool.
    When this happens, the connection should not be returned to the pool, and
    the request should be retried with a new connection.
    This should be raised by the connection's send_request() when the first operation on the connection fails.
    """

    pass


def remaining_timeout_or_raise(deadline: float | None) -> float | None:
    remaining = remaining_timeout(deadline)
    if remaining is not None and remaining <= 0:
        raise TotalTimeoutError("Operation timed out")
    return remaining


def connection_wants_close(headers: list[tuple[str, str]]) -> bool:
    connection_values = Headers(headers).getall("connection")

    if not connection_values:
        return False

    return Connection.from_field_lines(connection_values).has("close")


def response_has_no_body(method: str, status: int) -> bool:
    if method.upper() == "HEAD":
        return True
    if 100 <= status < 200:
        return True
    if status in (204, 304):
        return True
    return False


def proxy_basic_auth_header(request: Request) -> tuple[str, str] | None:
    proxy_context = request.context.get("network", {}).get("proxy")
    if proxy_context is None:
        return None
    proxy_url_value = proxy_context.get("url")
    if proxy_url_value is None:
        return None
    proxy_url = URL(proxy_url_value) if isinstance(proxy_url_value, str) else proxy_url_value
    if not (proxy_url.username or proxy_url.password):
        return None
    username = proxy_url.username or ""
    password = proxy_url.password or ""
    credentials = f"{username}:{password}".encode("utf-8")
    auth_value = base64.b64encode(credentials).decode("ascii")
    return ("Proxy-Authorization", f"Basic {auth_value}")
