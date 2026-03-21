# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "oauthlib",
#     "zapros",
# ]
#
# [tool.uv.sources]
# zapros = { path = "../", editable = true }
# ///

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event
from typing import NotRequired, TypedDict
from urllib.parse import parse_qs, urlparse

from oauthlib.oauth2 import WebApplicationClient

from zapros import AsyncBaseHandler, AsyncBaseMiddleware, AsyncClient, Request, Response, URLSearchParams


@dataclass(slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class OAuthConfig(TypedDict):
    client_id: str
    client_secret: NotRequired[str | None]
    authorization_endpoint: str
    token_endpoint: str
    scopes: NotRequired[list[str]]
    redirect_uri: NotRequired[str]
    callback_port: NotRequired[int]


def _wait_for_callback(port: int) -> str:
    done = Event()
    result: dict[str, str | None] = {"url": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            result["url"] = self.path
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization complete. You can close this tab.")
            done.set()

        def log_message(self, *args, **kwargs) -> None:
            pass

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        server.timeout = 0.5
        while not done.is_set():
            server.handle_request()

    if not result["url"]:
        raise RuntimeError("No callback received")
    return result["url"]


class OAuthHandler(AsyncBaseMiddleware):
    def __init__(self, next_handler: AsyncBaseHandler, config: OAuthConfig) -> None:
        self.async_next = next_handler
        self.cfg = config
        self.client = WebApplicationClient(config["client_id"])
        self._token: TokenSet | None = None
        self._lock = asyncio.Lock()

    async def ahandle(self, request: Request) -> Response:
        token = await self._get_token()
        request.headers["Authorization"] = f"Bearer {token.access_token}"

        response = await self.async_next.ahandle(request)
        if response.status == 401 and token.refresh_token:
            await response.aclose()
            token = await self._refresh()
            request.headers["Authorization"] = f"Bearer {token.access_token}"
            response = await self.async_next.ahandle(request)

        return response

    async def _get_token(self) -> TokenSet:
        async with self._lock:
            if self._token is None or self._token.expired:
                if self._token and self._token.refresh_token:
                    self._token = await self._refresh()
                else:
                    self._token = await self._authorize()
            return self._token

    async def _authorize(self) -> TokenSet:
        redirect_uri = self.cfg.get("redirect_uri", "http://127.0.0.1:8914/callback")
        port = self.cfg.get("callback_port", 8914)

        auth_url = self.client.prepare_request_uri(
            self.cfg["authorization_endpoint"],
            redirect_uri=redirect_uri,
            scope=list(self.cfg.get("scopes", [])),
        )

        print(f"\nPlease visit this URL to authorize the application:\n{auth_url}\n")
        callback_path = await asyncio.to_thread(_wait_for_callback, port)

        code = parse_qs(urlparse(callback_path).query).get("code", [None])[0]
        if not code:
            raise RuntimeError("No authorization code received")

        body = self.client.prepare_request_body(
            code=code,
            redirect_uri=redirect_uri,
            client_secret=self.cfg.get("client_secret"),
        )

        token_request = Request(
            method="POST",
            url=self.cfg["token_endpoint"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body.encode(),
        )
        resp = await self.async_next.ahandle(token_request)
        data = await resp.ajson()

        self.client.parse_request_body_response(URLSearchParams(data).to_string())
        return self._save_token(data)

    async def _refresh(self) -> TokenSet:
        if not self._token or not self._token.refresh_token:
            raise RuntimeError("No refresh token available")

        body = self.client.prepare_refresh_body(
            refresh_token=self._token.refresh_token,
            client_secret=self.cfg.get("client_secret"),
        )

        token_request = Request(
            method="POST",
            url=self.cfg["token_endpoint"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body.encode(),
        )
        resp = await self.async_next.ahandle(token_request)
        data = await resp.ajson()

        if "refresh_token" not in data:
            data["refresh_token"] = self._token.refresh_token

        self.client.parse_request_body_response(URLSearchParams(data).to_string())
        return self._save_token(data)

    def _save_token(self, data: dict) -> TokenSet:
        self._token = TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + data.get("expires_in", 3600) - 30,
        )
        return self._token


async def main() -> None:
    async with AsyncClient().wrap_with_middleware(
        lambda next: OAuthHandler(
            next,
            config=OAuthConfig(
                client_id="...",  # create a GitHub OAuth app to get these values
                authorization_endpoint="https://github.com/login/oauth/authorize",
                token_endpoint="https://github.com/login/oauth/access_token",
                scopes=[
                    "user",
                    "repo",
                ],
            ),
        )
    ) as client:
        response = await client.get("https://api.github.com/user")
        user_data = await response.ajson()
        print(f"Authenticated as: {user_data.get('login')}")

        repos_response = await client.get("https://api.github.com/user/repos")
        repos = await repos_response.ajson()
        print(f"\nYou have access to {len(repos)} repositories")


if __name__ == "__main__":
    asyncio.run(main())
