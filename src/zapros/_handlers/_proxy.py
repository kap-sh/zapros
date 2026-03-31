import os
from typing import cast

from pywhatwgurl import URL

from zapros._handlers._async_base import AsyncBaseHandler, AsyncBaseMiddleware
from zapros._handlers._common import ensure_async_handler, ensure_sync_handler
from zapros._handlers._sync_base import BaseHandler, BaseMiddleware
from zapros._models import Request, Response


class Proxy(BaseMiddleware, AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler | BaseHandler) -> None:
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseHandler,
            next_handler,
        )

    def _extract_proxy_from_env(self, request: Request) -> URL | None:
        # 1. Pick proxy from env (respect scheme)
        scheme = request.url.protocol[:-1].lower()

        proxy_url = (
            os.environ.get(f"{scheme}_proxy")
            or os.environ.get(f"{scheme.upper()}_PROXY")
            or os.environ.get("ALL_PROXY")
            or os.environ.get("all_proxy")
        )

        if not proxy_url:
            return None

        # 2. Respect NO_PROXY
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
        if no_proxy:
            host = request.url.host
            for entry in [e.strip() for e in no_proxy.split(",") if e.strip()]:
                if entry == "*" or host == entry or host.endswith(entry.lstrip(".")):
                    return None

        # 3. Parse proxy URL (string → parse)
        parsed = URL(proxy_url)
        return parsed

    def handle(self, request: Request) -> Response:
        proxy_context = request.context.get("network", {}).get("proxy")
        if proxy_context is not None and "url" in proxy_context:
            return ensure_sync_handler(self.next).handle(request)

        if (proxy_from_env := self._extract_proxy_from_env(request)) is not None:
            request.context.setdefault("network", {}).setdefault("proxy", {})["url"] = proxy_from_env

        return Response(200)

    async def ahandle(self, request: Request) -> Response:
        proxy_context = request.context.get("network", {}).get("proxy")
        if proxy_context is not None and "url" in proxy_context:
            return await ensure_async_handler(self.async_next).ahandle(request)

        if (proxy_from_env := self._extract_proxy_from_env(request)) is not None:
            request.context.setdefault("network", {}).setdefault("proxy", {})["url"] = proxy_from_env
        return Response(200)
