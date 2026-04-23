import functools
from importlib.metadata import (
    PackageNotFoundError,
    version,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ssl
else:
    try:
        import ssl
    except ImportError:
        ssl = None

CHUNK_SIZE = 16 * 1024
DEFAULT_READ_SIZE = 1024 * 64


@functools.cache
def default_ssl_context() -> "ssl.SSLContext":
    if ssl is None:
        raise RuntimeError("SSL support is not available in this environment")

    return ssl.create_default_context()


DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
}

try:
    _version = version("zapros")
except PackageNotFoundError:
    _version = "0.0.0"

USER_AGENT = f"python-zapros/{_version}"
