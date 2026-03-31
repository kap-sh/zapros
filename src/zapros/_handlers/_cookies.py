from __future__ import annotations

from http.client import HTTPMessage
from http.cookiejar import CookieJar
from typing import cast
from urllib.request import (
    Request as UrllibRequest,
)

import typing_extensions

from zapros._handlers._common import (
    ensure_async_handler,
    ensure_sync_handler,
)

from .._models import Request, Response
from ._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)
from ._sync_base import (
    BaseHandler,
    BaseMiddleware,
)


class _MockHTTPResponse:
    def __init__(self, headers: HTTPMessage) -> None:
        self.msg = headers

    def info(self) -> HTTPMessage:
        return self.msg


class CookieMiddleware(AsyncBaseMiddleware, BaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler | BaseHandler,
        jar: CookieJar | None = None,
    ) -> None:
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseHandler,
            next_handler,
        )
        self.jar = jar if jar is not None else CookieJar()

    def _process_request(self, request: Request) -> UrllibRequest:
        req = UrllibRequest(
            str(request.url),
            headers=dict(request.headers.list()),
        )
        self.jar.add_cookie_header(req)

        if req.has_header("Cookie"):
            cookie_value = req.get_header("Cookie")
            if cookie_value:
                if "cookie" in request.headers:
                    request.headers.extend(
                        [
                            (
                                "Cookie",
                                cookie_value,
                            )
                        ]
                    )
                else:
                    request.headers.add(
                        "Cookie",
                        cookie_value,
                    )

        return req

    def _process_response(
        self,
        response: Response,
        req: UrllibRequest,
    ) -> Response:
        headers = HTTPMessage()
        for (
            k,
            v,
        ) in response.headers.items():
            headers[k] = v

        mock_response = _MockHTTPResponse(headers)
        self.jar.extract_cookies(mock_response, req)  # type: ignore[arg-type]

        return response

    async def ahandle(self, request: Request) -> Response:
        handler = ensure_async_handler(self.async_next)
        req = self._process_request(request)
        response = await handler.ahandle(request)
        return self._process_response(response, req)

    def handle(self, request: Request) -> Response:
        handler = ensure_sync_handler(self.next)
        req = self._process_request(request)
        response = handler.handle(request)
        return self._process_response(response, req)


@typing_extensions.deprecated(
    "CookieHandler is deprecated, use CookieMiddleware instead. "
    "The name 'Handler' was misleading as this is a middleware, not a terminal handler."
)
class CookieHandler(CookieMiddleware):
    pass
