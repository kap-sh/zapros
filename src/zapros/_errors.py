from __future__ import annotations


class AsyncSyncMismatchError(Exception):
    """Raised when an asynchronous handler or function is used in a synchronous context, or vice versa."""

    def __init__(self, message: str) -> None:
        super().__init__(
            f"{message}\nSee https://zapros.dev/guide/async-sync.html#asyncsyncmismatcherror for more info."
        )


class ConnectionError(Exception):
    """Raised when a connection cannot be established or is lost."""

    pass


class DNSResolutionError(ConnectionError):
    """Raised when DNS resolution fails."""

    pass


class TimeoutError(Exception):
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


class TooManyRedirectsError(Exception):
    """Raised when the maximum number of redirects is exceeded."""

    pass


class AuthenticationError(Exception):
    """Base class for all authentication-related errors."""

    pass
