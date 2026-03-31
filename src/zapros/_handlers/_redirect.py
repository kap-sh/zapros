from __future__ import annotations

from typing import cast

from pywhatwgurl import URL

from zapros._handlers._common import (
    ensure_async_handler,
    ensure_sync_handler,
)
from zapros._handlers._sync_base import (
    BaseHandler,
    BaseMiddleware,
)

from .._errors import TooManyRedirectsError
from .._models import Headers, Request, Response
from ._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)

REDIRECT_STATUS_CODES = {
    301,
    302,
    303,
    307,
    308,
}

METHOD_PRESERVING_CODES = {307, 308}
METHOD_CONVERTING_CODES = {
    301,
    302,
    303,
}

ALWAYS_STRIP_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "if-match",
        "if-none-match",
        "if-modified-since",
        "if-unmodified-since",
        "if-range",
        "referer",
        "origin",
    }
)

CONTENT_HEADERS_TO_STRIP = frozenset(
    {
        "content-type",
        "content-length",
        "content-encoding",
        "content-language",
        "content-location",
        "transfer-encoding",
        "digest",
    }
)


class RedirectHandler(AsyncBaseMiddleware, BaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler | BaseHandler,
        *,
        max_redirects: int = 10,
    ) -> None:
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseMiddleware,
            next_handler,
        )
        self._max_redirects = max_redirects

    def _build_redirect_request(
        self,
        original_request: Request,
        location: str,
        status_code: int,
    ) -> Request:
        original_url = original_request.url

        redirect_url = URL(
            location,
            base=original_url.to_string(),
        )

        if status_code == 303:
            new_method = "HEAD" if original_request.method == "HEAD" else "GET"
        elif status_code in (301, 302):
            new_method = "GET" if original_request.method == "POST" else original_request.method
        else:
            new_method = original_request.method

        headers_list = original_request.headers.list()
        new_headers_dict: Headers = Headers()

        method_changed_to_get_or_head = new_method in (
            "GET",
            "HEAD",
        )

        for k, v in headers_list:
            k_lower = k.lower()

            if k_lower in ALWAYS_STRIP_HEADERS:
                continue

            if method_changed_to_get_or_head and k_lower in CONTENT_HEADERS_TO_STRIP:
                continue

            if k_lower == "host":
                continue

            new_headers_dict[k] = v

        if original_request.body is None or method_changed_to_get_or_head:
            return Request(
                redirect_url,
                new_method,
                headers=new_headers_dict,
                context=original_request.context.copy(),
            )
        elif original_request.is_replayable():
            return Request(
                redirect_url,
                new_method,
                headers=new_headers_dict,
                body=original_request.body,
                context=original_request.context.copy(),
            )
        else:
            raise NotImplementedError("Redirect with non-replayable body is not supported")

    async def ahandle(self, request: Request) -> Response:
        handler = ensure_async_handler(self.async_next)

        current_request = request
        redirect_count = 0

        while True:
            response = await handler.ahandle(current_request)

            if response.status not in REDIRECT_STATUS_CODES:
                return response

            location = response.headers.get("Location")
            if location is None:
                return response

            if redirect_count >= self._max_redirects:
                await response.aclose()
                raise TooManyRedirectsError(f"Exceeded maximum number of redirects ({self._max_redirects})")

            current_request = self._build_redirect_request(
                current_request,
                location,
                response.status,
            )
            redirect_count += 1
            await response.aclose()

    def handle(self, request: Request) -> Response:
        handler = ensure_sync_handler(self.next)

        current_request = request
        redirect_count = 0

        while True:
            response = handler.handle(current_request)

            if response.status not in REDIRECT_STATUS_CODES:
                return response

            location = response.headers.get("Location")
            if location is None:
                return response

            if redirect_count >= self._max_redirects:
                response.close()
                raise TooManyRedirectsError(f"Exceeded maximum number of redirects ({self._max_redirects})")

            current_request = self._build_redirect_request(
                current_request,
                location,
                response.status,
            )
            redirect_count += 1
            response.close()
