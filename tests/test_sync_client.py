import pytest

from zapros import BaseHandler, Client, Request, Response


class BrokenHandler(BaseHandler):
    def handle(self, request: Request) -> Response:
        raise RuntimeError("Error from BrokenHandler")


def test_handler_transform():
    with Client() as client:
        with pytest.raises(RuntimeError, match="Error from BrokenHandler"):
            client.get("https://example.com", handler=lambda _: BrokenHandler())


def test_handler_explicit():
    with Client() as client:
        with pytest.raises(RuntimeError, match="Error from BrokenHandler"):
            client.get("https://example.com", handler=BrokenHandler())
