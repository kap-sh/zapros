import pytest

from tests.mock_server import MockServer


@pytest.fixture(scope="session")
def mock_server():
    server = MockServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
def mock_server_url(mock_server) -> str:
    return mock_server.url
