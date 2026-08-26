import pytest

from zapros import AsyncBaseHandler, AsyncClient, Request, Response


class BrokenHandler(AsyncBaseHandler):
    async def ahandle(self, request: Request) -> Response:
        raise RuntimeError("Error from BrokenHandler")


async def test_handler_transform():
    async with AsyncClient() as client:
        with pytest.raises(RuntimeError, match="Error from BrokenHandler"):
            await client.get("https://example.com", handler=lambda _: BrokenHandler())


async def test_handler_explicit():
    async with AsyncClient() as client:
        with pytest.raises(RuntimeError, match="Error from BrokenHandler"):
            await client.get("https://example.com", handler=BrokenHandler())


class CapturingHandler(AsyncBaseHandler):
    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def ahandle(self, request: Request) -> Response:
        self.requests.append(request)
        return Response(status=200)


async def test_request_trailers_passed_through():
    handler = CapturingHandler()
    async with AsyncClient(handler=handler) as client:
        await client.post("https://example.com", body=b"hello", trailers={"X-Checksum": "abc"})
        await client.get("https://example.com")

    assert handler.requests[0].trailers is not None
    assert handler.requests[0].trailers["x-checksum"] == "abc"
    assert handler.requests[1].trailers is None
