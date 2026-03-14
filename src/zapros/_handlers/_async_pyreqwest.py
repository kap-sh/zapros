from __future__ import annotations

from collections.abc import (
    AsyncIterator as ABCAsyncIterator,
)
from typing import TYPE_CHECKING

from .._models import (
    AsyncClosableStream,
    Request,
    Response,
)
from ._async_base import (
    AsyncBaseHandler,
)
from ._exc_map import map_connect_exceptions, map_read_exceptions

if TYPE_CHECKING:
    import sys
    from contextlib import AbstractAsyncContextManager

    if sys.version_info >= (3, 11):
        from pyreqwest.client import (
            ClientBuilder,
        )
        from pyreqwest.response import (
            Response as PyreqwestResponse,
        )
    else:
        if not TYPE_CHECKING:
            ClientBuilder = None
            PyreqwestResponse = None
else:
    try:
        from pyreqwest.client import (
            ClientBuilder,
        )
        from pyreqwest.response import (
            Response as PyreqwestResponse,
        )
    except ImportError:
        if not TYPE_CHECKING:
            ClientBuilder = None
            PyreqwestResponse = None


class AsyncPyreqwestStream(AsyncClosableStream):
    def __init__(
        self,
        response: PyreqwestResponse,
        stream_request: AbstractAsyncContextManager[PyreqwestResponse],
    ) -> None:
        self._response = response
        self._stream_request = stream_request

    async def __anext__(self) -> bytes:
        with map_read_exceptions():
            chunk = await self._response.body_reader.read_chunk()
            if chunk is None:
                raise StopAsyncIteration
            return chunk.to_bytes()

    async def aclose(self) -> None:
        await self._stream_request.__aexit__(None, None, None)


class AsyncPyreqwestHandler(AsyncBaseHandler):
    def __init__(
        self,
        client: ClientBuilder | None = None,
    ) -> None:
        if ClientBuilder is None:  # type: ignore[reportPossiblyUnboundVariable]
            raise ImportError("pyreqwest is not installed. Install it with: pip install pyreqwest")
        self._builder = client
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        builder = ClientBuilder() if self._builder is None else self._builder
        builder = builder.gzip(False).deflate(False).brotli(False).zstd(False)
        self._client = builder.build()
        return self._client

    async def ahandle(self, request: Request) -> Response:
        client = self._get_client()

        req_builder = client.request(
            request.method,
            str(request.url),
        )

        for (
            key,
            value,
        ) in request.headers.items():
            req_builder = req_builder.header(key, value)

        if isinstance(request.body, bytes):
            req_builder = req_builder.body_bytes(request.body)
        elif isinstance(
            request.body,
            ABCAsyncIterator,
        ):
            req_builder = req_builder.body_stream(request.body)

        stream_request = req_builder.build_streamed()

        with map_connect_exceptions():
            pyreqwest_response = await stream_request.__aenter__()

        return Response(
            status=pyreqwest_response.status,
            headers=pyreqwest_response.headers,
            content=AsyncPyreqwestStream(pyreqwest_response, stream_request),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
