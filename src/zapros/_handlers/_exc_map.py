from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import trio
else:
    try:
        import trio
    except ImportError:
        trio = None

from .._errors import (
    ConnectionError,
    ConnectTimeoutError,
    DNSResolutionError,
    ReadError,
    ReadTimeoutError,
    SSLError,
    WriteError,
    WriteTimeoutError,
)

if TYPE_CHECKING:
    import socket
    import ssl
else:
    try:
        import socket
        import ssl
    except ImportError:
        socket = None
        ssl = None


_CONNECT_TIMEOUT_ERRNOS = {60, 110}
_CONNECTION_LOST_ERRORS = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


@contextlib.contextmanager
def map_socket_connect_exceptions() -> Iterator[None]:
    """
    Map raw socket connection exceptions to Zapros errors.

    Example:
        with map_socket_connect_exceptions():
            sock.connect((host, port))
    """
    try:
        yield
    except TimeoutError as e:
        raise ConnectTimeoutError("Connection timed out") from e
    except socket.gaierror as e:
        raise DNSResolutionError(f"DNS resolution failed: {e}") from e
    except ssl.SSLError as e:
        raise SSLError(f"SSL error during connection: {e}") from e
    except OSError as e:
        if e.errno in _CONNECT_TIMEOUT_ERRNOS:
            raise ConnectTimeoutError("Connection timed out") from e
        raise ConnectionError(f"Connection failed: {e}") from e


@contextlib.contextmanager
def map_asyncio_connect_exceptions() -> Iterator[None]:
    """
    Map asyncio connection exceptions to Zapros errors.

    Note:
        This is intended for wrapping ``asyncio.open_connection(...)``.
        A timeout is only raised if the caller applies one externally, for example with ``asyncio.timeout()``.

    Example:
        with map_asyncio_connect_exceptions():
            reader, writer = await asyncio.open_connection(host, port)
    """
    try:
        yield
    except TimeoutError as e:
        raise ConnectTimeoutError("Connection timed out") from e
    except socket.gaierror as e:
        raise DNSResolutionError(f"DNS resolution failed: {e}") from e
    except ssl.SSLError as e:
        raise SSLError(f"SSL error during connection: {e}") from e
    except OSError as e:
        if e.errno in _CONNECT_TIMEOUT_ERRNOS:
            raise ConnectTimeoutError("Connection timed out") from e
        raise ConnectionError(f"Connection failed: {e}") from e


@contextlib.contextmanager
def map_trio_connect_exceptions() -> Iterator[None]:
    """
    Map Trio connection and TLS-handshake exceptions to Zapros errors.

    Note:
        This is intended for wrapping ``trio.open_tcp_stream(...)`` and
        ``trio.SSLStream.do_handshake()``.
    """
    try:
        yield
    except trio.TooSlowError as e:
        raise ConnectTimeoutError("Connection timed out") from e
    except socket.gaierror as e:
        raise DNSResolutionError(f"DNS resolution failed: {e}") from e
    except ssl.SSLError as e:
        raise SSLError(f"SSL error during connection: {e}") from e
    except (trio.BrokenResourceError, trio.ClosedResourceError, trio.BusyResourceError) as e:
        raise ConnectionError(f"Connection failed: {e}") from e
    except OSError as e:
        if e.errno in _CONNECT_TIMEOUT_ERRNOS:
            raise ConnectTimeoutError("Connection timed out") from e
        raise ConnectionError(f"Connection failed: {e}") from e


@contextlib.contextmanager
def map_socket_write_exceptions() -> Iterator[None]:
    """
    Map raw socket write exceptions to Zapros errors.

    Example:
        with map_socket_write_exceptions():
            sock.sendall(data)
    """
    try:
        yield
    except TimeoutError as e:
        raise WriteTimeoutError("Write operation timed out") from e
    except _CONNECTION_LOST_ERRORS as e:
        raise WriteError(f"Connection lost during write: {e}") from e
    except OSError as e:
        raise WriteError(f"Write failed: {e}") from e


@contextlib.contextmanager
def map_trio_write_exceptions() -> Iterator[None]:
    """
    Map Trio stream write exceptions to Zapros errors.

    Note:
        This is intended for wrapping ``await stream.send_all(...)``.
    """
    try:
        yield
    except trio.TooSlowError as e:
        raise WriteTimeoutError("Write operation timed out") from e
    except (trio.BrokenResourceError, trio.ClosedResourceError, trio.BusyResourceError) as e:
        raise WriteError(f"Write failed: {e}") from e
    except _CONNECTION_LOST_ERRORS as e:
        raise WriteError(f"Connection lost during write: {e}") from e
    except OSError as e:
        raise WriteError(f"Write failed: {e}") from e


@contextlib.contextmanager
def map_asyncio_write_exceptions() -> Iterator[None]:
    """
    Map asyncio stream write exceptions to Zapros errors.

    Note:
        This is intended for wrapping ``writer.write(...)`` plus
        ``await writer.drain()``. A timeout is only raised if the caller
        applies one externally, for example with ``asyncio.timeout()``.

    Example:
        with map_asyncio_write_exceptions():
            writer.write(data)
            await writer.drain()
    """
    try:
        yield
    except TimeoutError as e:
        raise WriteTimeoutError("Write operation timed out") from e
    except _CONNECTION_LOST_ERRORS as e:
        raise WriteError(f"Connection lost during write: {e}") from e
    except OSError as e:
        raise WriteError(f"Write failed: {e}") from e


@contextlib.contextmanager
def map_socket_read_exceptions() -> Iterator[None]:
    try:
        yield
    except TimeoutError as e:
        raise ReadTimeoutError("Read operation timed out") from e
    except OSError as e:
        raise ReadError(f"Read failed: {e}") from e


@contextlib.contextmanager
def map_trio_read_exceptions() -> Iterator[None]:
    try:
        yield
    except trio.TooSlowError as e:
        raise ReadTimeoutError("Read operation timed out") from e
    except (trio.BrokenResourceError, trio.ClosedResourceError, trio.BusyResourceError) as e:
        raise ReadError(f"Read failed: {e}") from e
    except OSError as e:
        raise ReadError(f"Read failed: {e}") from e


@contextlib.contextmanager
def map_asyncio_read_exceptions() -> Iterator[None]:
    try:
        yield
    except TimeoutError as e:
        raise ReadTimeoutError("Read operation timed out") from e
    except OSError as e:
        raise ReadError(f"Read failed: {e}") from e


def map_connect_exceptions() -> contextlib.AbstractContextManager[None]:
    return map_socket_connect_exceptions()


def map_write_exceptions() -> contextlib.AbstractContextManager[None]:
    return map_socket_write_exceptions()


def map_read_exceptions() -> contextlib.AbstractContextManager[None]:
    return map_socket_read_exceptions()
