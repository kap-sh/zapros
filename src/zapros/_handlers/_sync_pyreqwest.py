from __future__ import annotations

from collections.abc import (
    Iterator as ABCIterator,
)
from typing import TYPE_CHECKING

from .._models import (
    ClosableStream,
    Request,
    Response,
)
from ._sync_base import (
    BaseHandler,
)
from ._exc_map import map_connect_exceptions, map_read_exceptions

if TYPE_CHECKING:
    import sys
    from contextlib import AbstractContextManager

    if sys.version_info >= (3, 11):
        from pyreqwest.client import (
            SyncClientBuilder,
        )
        from pyreqwest.response import (
            SyncResponse as PyreqwestResponse,
        )
    else:
        if not TYPE_CHECKING:
            SyncClientBuilder = None
            PyreqwestResponse = None
else:
    try:
        from pyreqwest.client import (
            SyncClientBuilder,
        )
        from pyreqwest.response import (
            SyncResponse as PyreqwestResponse,
        )
    except ImportError:
        if not TYPE_CHECKING:
            SyncClientBuilder = None
            PyreqwestResponse = None


class PyreqwestStream(ClosableStream):
    def __init__(
        self,
        response: PyreqwestResponse,
        stream_request: AbstractContextManager[PyreqwestResponse],
    ) -> None:
        self._response = response
        self._stream_request = stream_request

    def __next__(self) -> bytes:
        with map_read_exceptions():
            chunk = self._response.body_reader.read_chunk()
            if chunk is None:
                raise StopIteration
            return chunk.to_bytes()

    def close(self) -> None:
        self._stream_request.__exit__(None, None, None)


class PyreqwestHandler(BaseHandler):
    def __init__(
        self,
        client: SyncClientBuilder | None = None,
    ) -> None:
        if SyncClientBuilder is None:  # type: ignore[reportPossiblyUnboundVariable]
            raise ImportError("pyreqwest is not installed. Install it with: pip install pyreqwest")
        self._builder = client
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        builder = SyncClientBuilder() if self._builder is None else self._builder
        builder = builder.gzip(False).deflate(False).brotli(False).zstd(False)
        self._client = builder.build()
        return self._client

    def handle(self, request: Request) -> Response:
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
            ABCIterator,
        ):
            req_builder = req_builder.body_stream(request.body)

        stream_request = req_builder.build_streamed()

        with map_connect_exceptions():
            pyreqwest_response = stream_request.__enter__()

        return Response(
            status=pyreqwest_response.status,
            headers=pyreqwest_response.headers,
            content=PyreqwestStream(pyreqwest_response, stream_request),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
