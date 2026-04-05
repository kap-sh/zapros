from __future__ import annotations

import asyncio
import contextlib
import socket
import ssl
from collections.abc import Iterator

import h11

from .._errors import (
    ConnectionError,
    ConnectTimeoutError,
    DNSResolutionError,
    ReadTimeoutError,
    SSLError,
    WriteTimeoutError,
)


@contextlib.contextmanager
def map_connect_exceptions() -> Iterator[None]:
    try:
        yield
    except (asyncio.TimeoutError, socket.timeout) as e:
        raise ConnectTimeoutError("Connection timed out") from e
    except socket.gaierror as e:
        raise DNSResolutionError(f"DNS resolution failed: {e}") from e
    except ssl.SSLError as e:
        raise SSLError(f"SSL error during connection: {e}") from e
    except OSError as e:
        if e.errno in (60, 110):
            raise ConnectTimeoutError("Connection timed out") from e
        raise ConnectionError(f"Connection failed: {e}") from e


@contextlib.contextmanager
def map_write_exceptions() -> Iterator[None]:
    try:
        yield
    except (asyncio.TimeoutError, socket.timeout) as e:
        raise WriteTimeoutError("Write operation timed out") from e
    except OSError as e:
        raise ConnectionError(f"Write failed: {e}") from e


@contextlib.contextmanager
def map_read_exceptions() -> Iterator[None]:
    try:
        yield
    except (asyncio.TimeoutError, socket.timeout) as e:
        raise ReadTimeoutError("Read operation timed out") from e
    except (h11.RemoteProtocolError, h11.LocalProtocolError) as e:
        raise ConnectionError(f"HTTP protocol error: {e}") from e
    except OSError as e:
        raise ConnectionError(f"Read failed: {e}") from e
