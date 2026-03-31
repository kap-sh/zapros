import ssl
from importlib.metadata import (
    PackageNotFoundError,
    version,
)

CHUNK_SIZE = 16 * 1024
DEFAULT_READ_SIZE = 1024 * 64
DEFAULT_SSL_CONTEXT = ssl.create_default_context()

DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
}

try:
    _version = version("zapros")
except PackageNotFoundError:
    _version = "0.0.0"

USER_AGENT = f"python-zapros/{_version}"
