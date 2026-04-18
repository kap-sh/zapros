from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zapros._models import Response


class ZaprosError(Exception):
    """Base class for all Zapros errors."""

    pass


class AsyncSyncMismatchError(ZaprosError):
    """Raised when an asynchronous handler or function is used in a synchronous context, or vice versa."""

    def __init__(self, message: str) -> None:
        super().__init__(
            f"{message}\nSee https://zapros.dev/guide/async-sync.html#asyncsyncmismatcherror for more info."
        )


class ConnectionError(ZaprosError):
    """Raised when a connection cannot be established or is lost."""

    pass


class DNSResolutionError(ConnectionError):
    """Raised when DNS resolution fails."""

    pass


class SSLError(ConnectionError):
    """Raised when an SSL/TLS handshake fails."""

    pass


class TimeoutError(ZaprosError):
    """Base class for all Zapros timeout errors."""

    pass


class ConnectTimeoutError(TimeoutError):
    """Raised when connection establishment times out."""

    pass


class ReadTimeoutError(TimeoutError):
    """Raised when reading response data times out."""

    pass


class WriteTimeoutError(TimeoutError):
    """Raised when writing request data times out."""

    pass


class TotalTimeoutError(TimeoutError):
    """Raised when the total request deadline is exceeded."""

    pass


class PoolTimeoutError(TimeoutError):
    """Raised when waiting for a connection pool slot times out."""

    pass


class TooManyRedirectsError(ZaprosError):
    """Raised when the maximum number of redirects is exceeded."""

    pass


class AuthenticationError(ZaprosError):
    """Base class for all authentication-related errors."""

    pass


class ResponseNotRead(ZaprosError):
    """Raised when attempting to access response body content that hasn't been read yet."""

    pass


class StatusCodeError(ZaprosError):
    """Might be raised when a response has an error status code."""

    def __init__(self, response: "Response", message: str | None = None) -> None:
        self.response = response
        if message is None:
            message = f"Error status code: {response.status}"
        super().__init__(message)


class ReadError(ZaprosError):
    """Raised when an error occurs while reading response data."""

    pass


class UnhandledRequestError(ZaprosError, ValueError):
    """Raised by :class:`~zapros.CassetteMiddleware` when a request cannot be
    served from the cassette and the current :class:`~zapros.CassetteMode`
    does not allow recording a new interaction."""

    pass


class WriteError(ZaprosError):
    """Raised when an error occurs while writing request data."""

    pass


class HeaderParseError(ZaprosError):
    """Raised when an error occurs while parsing a header value."""

    pass
