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


class CapturingHandler(BaseHandler):
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def handle(self, request: Request) -> Response:
        self.requests.append(request)
        return Response(status=200)


def test_request_trailers_passed_through():
    handler = CapturingHandler()
    with Client(handler=handler) as client:
        client.post("https://example.com", body=b"hello", trailers={"X-Checksum": "abc"})
        client.get("https://example.com")

    assert handler.requests[0].trailers is not None
    assert handler.requests[0].trailers["x-checksum"] == "abc"
    assert handler.requests[1].trailers is None
