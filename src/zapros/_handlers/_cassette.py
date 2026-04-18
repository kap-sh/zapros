from __future__ import annotations

import base64
import enum
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    cast,
)

import typing_extensions
from pywhatwgurl import URL

from zapros._errors import HeaderParseError, UnhandledRequestError
from zapros._handlers._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)
from zapros._handlers._common import (
    ensure_async_handler,
    ensure_sync_handler,
)
from zapros._handlers._sync_base import (
    BaseHandler,
    BaseMiddleware,
)
from zapros._headers import ContentType
from zapros._models import (
    AsyncClosableStream,
    ClosableStream,
    Headers,
    Request,
    Response,
)

from ..matchers import Matcher

RequestMapper = Callable[[Request], Request]
ResponseMapper = Callable[[Response], Response]


class CassetteMode(enum.Enum):
    """Recording behavior for :class:`CassetteMiddleware`."""

    ALL = "all"
    """Always send requests to the network and record them.

    Any pre-existing cassette contents are discarded at init — the cassette is
    rewritten from scratch, not appended to. Use when regenerating cassettes.
    """

    NEW_EPISODES = "new_episodes"
    """Replay matched requests from the cassette; send unmatched ones to the
    network and append the new interactions to the cassette."""

    ONCE = "once"
    """Record only if the cassette file does not yet exist.

    Once a cassette exists, behave like :attr:`NONE` — replay matches and raise
    :class:`~zapros.UnhandledRequestError` on unmatched requests.
    """

    NONE = "none"
    """Replay-only. Never hit the network; unmatched requests raise
    :class:`~zapros.UnhandledRequestError`."""


def normalize_url(url: URL) -> str:
    copy = URL(url.href)
    copy.search_params.sort()
    return copy.href


def parse_content_type(headers: Headers) -> ContentType | None:
    value = headers.get("content-type")
    if not value:
        return None
    try:
        return ContentType.parse(value)
    except HeaderParseError:
        return None


def is_json(ct: ContentType | None) -> bool:
    return ct is not None and (ct.media_type == "application/json" or ct.subtype.endswith("+json"))


def is_text(ct: ContentType | None) -> bool:
    return ct is not None and ct.type == "text"


def charset(ct: ContentType | None) -> str:
    return ct.charset if ct is not None and ct.charset is not None else "utf-8"


def serialize_body(
    body: bytes,
    headers: Headers,
) -> Any:
    ct = parse_content_type(headers)
    charset_ = charset(ct)

    if is_json(ct):
        return json.loads(body.decode(charset_))
    elif is_text(ct):
        return body.decode(charset_)
    else:
        return base64.b64encode(body).decode("ascii")


def deserialize_body(
    body: Any,
    headers: Headers,
) -> bytes:
    ct = parse_content_type(headers)
    charset_ = charset(ct)

    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False).encode(charset_)
    elif isinstance(body, str):
        if is_text(ct) or is_json(ct):
            return body.encode(charset_)
        else:
            return base64.b64decode(body)
    else:
        raise ValueError(f"Unexpected body type: {type(body)}")


def request_key(
    request: Request,
) -> dict[str, Any]:
    return {
        "method": request.method.upper(),
        "uri": normalize_url(request.url),
    }


def get_cassette_mode_from_env() -> CassetteMode:
    mode_str = os.getenv("ZAPROS_CASSETTE_MODE", CassetteMode.ONCE.value).lower()
    try:
        return CassetteMode(mode_str)
    except ValueError:
        raise ValueError(f"Invalid cassette mode in environment variable ZAPROS_CASSETTE_MODE: {mode_str}") from None


@dataclass
class StoredInteraction:
    request: dict[str, Any]
    response: dict[str, Any]
    played_back: bool = False


class Modifier:
    def __init__(self, matcher: Matcher) -> None:
        self._matcher = matcher
        self._network_request_mapper: RequestMapper | None = None
        self._network_response_mapper: ResponseMapper | None = None
        self._name: str | None = None

    def matches(self, request: Request) -> bool:
        return self._matcher.match(request)

    def map_network_request(self, fn: RequestMapper) -> Modifier:
        self._network_request_mapper = fn
        return self

    def map_network_response(self, fn: ResponseMapper) -> Modifier:
        self._network_response_mapper = fn
        return self

    def name(self, name: str) -> Modifier:
        self._name = name
        return self

    def apply_network_request(self, request: Request) -> Request:
        if self._network_request_mapper is None:
            return request
        return self._network_request_mapper(request)

    def apply_network_response(self, response: Response) -> Response:
        if self._network_response_mapper is None:
            return response
        return self._network_response_mapper(response)


class ModifierRouter:
    def __init__(self) -> None:
        self._modifiers: list[Modifier] = []

    def modifier(self, matcher: Matcher) -> Modifier:
        modifier = Modifier(matcher)
        self._modifiers.append(modifier)
        return modifier

    def prepare_request(self, request: Request) -> Request:

        for modifier in self._modifiers:
            if modifier.matches(request):
                request = modifier.apply_network_request(request)

        return request

    def prepare_network_response(
        self,
        request: Request,
        response: Response,
    ) -> Response:
        current = response

        for modifier in self._modifiers:
            if modifier.matches(request):
                current = modifier.apply_network_response(current)

        return current


class CassetteMiddleware(AsyncBaseMiddleware, BaseMiddleware):
    def __init__(
        self,
        next_handler: AsyncBaseHandler | BaseHandler,
        *,
        router: ModifierRouter | None = None,
        mode: CassetteMode | None = None,
        cassette_dir: str = "cassettes",
        cassette_name: str = "default",
        allow_playback_repeats: bool = False,
    ) -> None:
        self.router = router or ModifierRouter()
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseMiddleware,
            next_handler,
        )
        self._mode = mode if mode is not None else get_cassette_mode_from_env()

        self._allow_playback_repeats = allow_playback_repeats
        self._cassette_dir = Path(cassette_dir)
        self._cassette_name = cassette_name
        self._cassette_existed_at_init = self._cassette_path().exists()
        self._interactions = [] if self._mode == CassetteMode.ALL else self._load()

    def _cassette_path(self) -> Path:
        return self._cassette_dir / f"{self._cassette_name}.json"

    def _load(
        self,
    ) -> list[StoredInteraction]:
        path = self._cassette_path()
        if not path.exists():
            return []

        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            StoredInteraction(
                request=item["request"],
                response=item["response"],
                played_back=False,  # runtime-only state
            )
            for item in payload
        ]

    def _save(self) -> None:
        self._cassette_dir.mkdir(parents=True, exist_ok=True)
        path = self._cassette_path()
        payload = [
            {
                "request": item.request,
                "response": item.response,
            }
            for item in self._interactions
        ]
        path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _build_replayed_response(self, item: StoredInteraction) -> Response:
        headers = Headers(item.response["headers"])
        body = deserialize_body(item.response["body"], headers)
        return Response(
            status=item.response["status"],
            headers={
                **headers,
                "content-length": str(len(body)),
            },
            content=body,
        )

    def _find_matching_interaction(
        self,
        prepared_request: Request,
    ) -> StoredInteraction | None:
        key = request_key(prepared_request)

        if self._allow_playback_repeats:
            for item in self._interactions:
                if item.request == key:
                    return item
            return None

        for item in self._interactions:
            if item.request == key and not item.played_back:
                return item

        return None

    def _mark_played_back(self, item: StoredInteraction) -> None:
        if self._allow_playback_repeats:
            return
        item.played_back = True

    def _can_record(self) -> bool:
        if self._mode == CassetteMode.ALL:
            return True

        if self._mode == CassetteMode.NEW_EPISODES:
            return True

        if self._mode == CassetteMode.ONCE:
            return not self._cassette_existed_at_init

        if self._mode == CassetteMode.NONE:
            return False

        raise ValueError(f"Unknown cassette mode: {self._mode}")

    async def _amaterialize_request(self, request: Request) -> Request:
        body = request.body
        if body is None or isinstance(body, bytes):
            return request

        return Request(
            method=request.method,
            url=request.url,
            headers=Headers(dict(request.headers)),
            body=b"".join([chunk async for chunk in body]),  # type: ignore
        )

    def _materialize_request(self, request: Request) -> Request:
        body = request.body
        if body is None or isinstance(body, bytes):
            return request

        return Request(
            method=request.method,
            url=request.url,
            headers=Headers(dict(request.headers)),
            body=b"".join(body),  # type: ignore
        )

    async def ahandle(self, request: Request) -> Response:  # unasync: generate @cassetteMiddleware
        handler = ensure_async_handler(self.async_next)

        replayable_request = await self._amaterialize_request(request)

        if isinstance(request.body, AsyncClosableStream):
            await request.body.aclose()

        prepared_request = self.router.prepare_request(replayable_request)

        if self._mode != CassetteMode.ALL:
            stored = self._find_matching_interaction(prepared_request)
            if stored is not None:
                self._mark_played_back(stored)
                return self._build_replayed_response(stored)

        if not self._can_record():
            raise UnhandledRequestError(
                f"No cassette matched request: {prepared_request.method} {normalize_url(prepared_request.url)}"
            )

        network_response = await handler.ahandle(replayable_request)

        mapped_response = self.router.prepare_network_response(replayable_request, network_response)

        mapped_body = await mapped_response.aread()
        mapped_headers = Headers((k, v) for k, v in mapped_response.headers.items() if k.lower() != "content-encoding")

        await network_response.aclose()
        await mapped_response.aclose()

        replayable_response = Response(
            status=mapped_response.status,
            headers=Headers(mapped_headers),
            content=mapped_body,
        )

        self._interactions.append(
            StoredInteraction(
                request=request_key(prepared_request),
                response={
                    "status": replayable_response.status,
                    "headers": dict(replayable_response.headers),
                    "body": serialize_body(await replayable_response.aread(), replayable_response.headers),
                },
                played_back=False,
            )
        )
        return replayable_response

    def handle(self, request: Request) -> Response:  # unasync: generated @cassetteMiddleware
        handler = ensure_sync_handler(self.next)

        replayable_request = self._materialize_request(request)

        if isinstance(request.body, ClosableStream):
            request.body.close()

        prepared_request = self.router.prepare_request(replayable_request)

        if self._mode != CassetteMode.ALL:
            stored = self._find_matching_interaction(prepared_request)
            if stored is not None:
                self._mark_played_back(stored)
                return self._build_replayed_response(stored)

        if not self._can_record():
            raise UnhandledRequestError(
                f"No cassette matched request: {prepared_request.method} {normalize_url(prepared_request.url)}"
            )

        network_response = handler.handle(replayable_request)

        mapped_response = self.router.prepare_network_response(replayable_request, network_response)

        mapped_body = mapped_response.read()
        mapped_headers = Headers((k, v) for k, v in mapped_response.headers.items() if k.lower() != "content-encoding")

        network_response.close()
        mapped_response.close()

        replayable_response = Response(
            status=mapped_response.status,
            headers=Headers(mapped_headers),
            content=mapped_body,
        )

        self._interactions.append(
            StoredInteraction(
                request=request_key(prepared_request),
                response={
                    "status": replayable_response.status,
                    "headers": dict(replayable_response.headers),
                    "body": serialize_body(replayable_response.read(), replayable_response.headers),
                },
                played_back=False,
            )
        )
        return replayable_response

    async def aclose(self) -> None:
        # TODO: It's not critical to call the sync code here because cassettes are mostly used in the tests, buy maybe
        # we should consider making the async close to avoid blocking the event loop with file I/O?
        return self.close()

    def close(self) -> None:
        self._save()


@typing_extensions.deprecated(
    "CassetteHandler is deprecated, use CassetteMiddleware instead. "
    "The name 'Handler' was misleading as this is a middleware, not a terminal handler."
)
class CassetteHandler(CassetteMiddleware):
    pass


@typing_extensions.deprecated(
    "Cassette is deprecated, use ModifierRouter instead. "
    "The name 'Cassette' was misleading as this class only manages modifiers, not cassette recordings."
)
class Cassette(ModifierRouter):
    pass
