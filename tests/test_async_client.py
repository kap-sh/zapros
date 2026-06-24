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
