from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Literal,
    cast,
)
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

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
from zapros._models import (
    AsyncClosableStream,
    Headers,
    Request,
    Response,
)

from ..matchers import Matcher


class _CassetteBytesStream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._consumed = False

    def __iter__(
        self,
    ) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        if self._consumed:
            raise StopIteration
        self._consumed = True
        return self._data

    def __aiter__(
        self,
    ) -> _CassetteBytesStream:
        return self

    async def __anext__(self) -> bytes:
        if self._consumed:
            raise StopAsyncIteration
        self._consumed = True
        return self._data


RequestMapper = Callable[[Request], Request]
ResponseMapper = Callable[[Response], Response]
CassetteMode = Literal[
    "all",
    "new_episodes",
    "once",
    "none",
]


class UnhandledRequestError(ValueError):
    pass


def _normalize_url(url: Any) -> str:
    raw = str(url)
    parts = urlsplit(raw)
    normalized_query = urlencode(
        sorted(
            parse_qsl(
                parts.query,
                keep_blank_values=True,
            )
        ),
        doseq=True,
    )
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            normalized_query,
            parts.fragment,
        )
    )


def _extract_encoding_from_content_type(content_type: str) -> str:
    parts = content_type.split(";")
    for part in parts[1:]:
        stripped = part.strip()
        if stripped.lower().startswith("charset="):
            charset = stripped[8:].strip()
            if charset.startswith('"') and charset.endswith('"'):
                charset = charset[1:-1]
            return charset
    return "utf-8"


def _serialize_body(
    body: bytes | None,
    headers: Headers,
) -> Any:
    if body is None:
        return None

    content_type = headers.get("content-type", "")
    mime_type = content_type.split(";")[0].strip().lower()
    charset = _extract_encoding_from_content_type(content_type)

    if mime_type == "application/json" or mime_type.endswith("+json"):
        return json.loads(body.decode(charset))
    elif mime_type.startswith("text/"):
        return body.decode(charset)
    else:
        return base64.b64encode(body).decode("ascii")


def _deserialize_body(
    body: Any,
    headers: Headers,
) -> bytes | None:
    if body is None:
        return None

    content_type = headers.get("content-type", "")
    mime_type = content_type.split(";")[0].strip().lower()
    charset = _extract_encoding_from_content_type(content_type)

    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False).encode(charset)
    elif isinstance(body, str):
        is_json = mime_type == "application/json" or mime_type.endswith("+json")
        is_text = mime_type.startswith("text/")

        if is_text or is_json:
            return body.encode(charset)
        else:
            return base64.b64decode(body)
    else:
        raise ValueError(f"Unexpected body type: {type(body)}")


def _request_key(
    request: Request,
) -> dict[str, Any]:
    return {
        "method": request.method.upper(),
        "uri": _normalize_url(request.url),
    }


@dataclass
class _StoredInteraction:
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


class Cassette:
    def __init__(
        self,
        *,
        allow_playback_repeats: bool = False,
    ) -> None:
        self._modifiers: list[Modifier] = []
        self._allow_playback_repeats = allow_playback_repeats

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

    @property
    def allow_playback_repeats(
        self,
    ) -> bool:
        return self._allow_playback_repeats


class CassetteHandler(AsyncBaseMiddleware, BaseMiddleware):
    def __init__(
        self,
        cassette: Cassette,
        next_handler: AsyncBaseHandler | BaseHandler,
        *,
        mode: CassetteMode,
        cassette_dir: str,
        cassette_name: str = "default",
    ) -> None:
        self._cassette = cassette
        self._mode = mode
        self.next = cast(BaseHandler, next_handler)
        self.async_next = cast(
            AsyncBaseMiddleware,
            next_handler,
        )
        self._cassette_dir = Path(cassette_dir)
        self._cassette_name = cassette_name
        self._cassette_existed_at_init = self._cassette_path().exists()
        self._interactions = self._load()

    def _cassette_path(self) -> Path:
        return self._cassette_dir / f"{self._cassette_name}.json"

    def _load(
        self,
    ) -> list[_StoredInteraction]:
        path = self._cassette_path()
        if not path.exists():
            return []

        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            _StoredInteraction(
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

    def _build_replayed_response(self, item: _StoredInteraction) -> Response:
        headers = Headers(item.response["headers"])
        body = _deserialize_body(item.response["body"], headers)
        return Response(
            status=item.response["status"],
            headers=headers,
            content=body,
        )

    def _find_matching_interaction(
        self,
        prepared_request: Request,
    ) -> _StoredInteraction | None:
        key = _request_key(prepared_request)

        if self._cassette.allow_playback_repeats:
            for item in self._interactions:
                if item.request == key:
                    return item
            return None

        for item in self._interactions:
            if item.request == key and not item.played_back:
                return item

        return None

    def _mark_played_back(self, item: _StoredInteraction) -> None:
        if self._cassette.allow_playback_repeats:
            return
        item.played_back = True

    def _can_record(self) -> bool:
        if self._mode == "all":
            return True

        if self._mode == "new_episodes":
            return True

        if self._mode == "once":
            return not self._cassette_existed_at_init

        if self._mode == "none":
            return False

        raise ValueError(f"Unknown cassette mode: {self._mode}")

    def _record_interaction(
        self,
        prepared_request: Request,
        prepared_response: Response,
        response_body: bytes | None,
        response_headers: Headers,
    ) -> None:
        body_content = _serialize_body(
            response_body,
            response_headers,
        )
        self._interactions.append(
            _StoredInteraction(
                request=_request_key(prepared_request),
                response={
                    "status": prepared_response.status,
                    "headers": dict(response_headers),
                    "body": body_content,
                },
            )
        )
        self._save()

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

    async def ahandle(self, request: Request) -> Response:
        handler = ensure_async_handler(self.async_next)

        replayable_request = await self._amaterialize_request(request)

        if isinstance(request.body, AsyncClosableStream):
            await request.body.aclose()

        prepared_request = self._cassette.prepare_request(replayable_request)

        if self._mode != "all":
            stored = self._find_matching_interaction(prepared_request)
            if stored is not None:
                self._mark_played_back(stored)
                return self._build_replayed_response(stored)

        if not self._can_record():
            raise UnhandledRequestError(
                f"No cassette matched request: {prepared_request.method} {_normalize_url(prepared_request.url)}"
            )

        network_response = await handler.ahandle(replayable_request)

        mapped_response = self._cassette.prepare_network_response(replayable_request, network_response)

        if mapped_response.content is None:
            mapped_body = None
            mapped_headers = Headers(mapped_response.headers)
        else:
            mapped_body = await mapped_response.aread()
            mapped_headers = Headers(
                (k, v) for k, v in mapped_response.headers.items() if k.lower() != "content-encoding"
            )

        await mapped_response.aclose()

        replayable_response = Response(
            status=mapped_response.status,
            headers=Headers(mapped_headers),
            content=mapped_body,
        )

        self._record_interaction(
            prepared_request,
            replayable_response,
            mapped_body,
            mapped_headers,
        )
        return replayable_response

    def handle(self, request: Request) -> Response:
        handler = ensure_sync_handler(self.next)

        replayable_request = self._materialize_request(request)
        prepared_request = self._cassette.prepare_request(replayable_request)

        if self._mode != "all":
            stored = self._find_matching_interaction(prepared_request)
            if stored is not None:
                self._mark_played_back(stored)
                return self._build_replayed_response(stored)

        if not self._can_record():
            raise UnhandledRequestError(
                f"No cassette matched request: {prepared_request.method} {_normalize_url(prepared_request.url)}"
            )

        network_response = handler.handle(replayable_request)

        mapped_response = self._cassette.prepare_network_response(replayable_request, network_response)

        if mapped_response.content is None:
            mapped_body = None
            mapped_headers = Headers(mapped_response.headers)
        else:
            mapped_body = mapped_response.read()
            mapped_headers = Headers(
                (k, v) for k, v in mapped_response.headers.items() if k.lower() != "content-encoding"
            )

        mapped_response.close()

        replayable_response = Response(
            status=mapped_response.status,
            headers=Headers(mapped_headers),
            content=mapped_body,
        )

        self._record_interaction(
            prepared_request,
            replayable_response,
            mapped_body,
            mapped_headers,
        )
        return replayable_response
