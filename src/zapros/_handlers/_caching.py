import hashlib
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    Iterator,
    Union,
    cast,
    overload,
)

import typing_extensions

if TYPE_CHECKING:
    from hishel import (
        AnyState,
        AsyncBaseStorage as HishelAsyncBaseStorage,
        AsyncSqliteStorage,
        BaseStorage as HishelBaseStorage,
        CacheMiss,
        CacheOptions,
        CouldNotBeStored,
        FromCache,
        Headers as HishelHeaders,
        IdleClient,
        NeedRevalidation,
        NeedToBeUpdated,
        Request as HishelRequest,
        Response as HishelResponse,
        SqliteStorage,
        StoreAndUse,
    )
else:
    try:
        from hishel import (
            AnyState,
            AsyncBaseStorage as HishelAsyncBaseStorage,
            AsyncSqliteStorage,
            BaseStorage as HishelBaseStorage,
            CacheMiss,
            CacheOptions,
            CouldNotBeStored,
            FromCache,
            Headers as HishelHeaders,
            IdleClient,
            NeedRevalidation,
            NeedToBeUpdated,
            Request as HishelRequest,
            Response as HishelResponse,
            SqliteStorage,
            StoreAndUse,
        )
    except ImportError:
        AnyState = None
        HishelAsyncBaseStorage = None
        AsyncSqliteStorage = None
        HishelBaseStorage = None
        CacheMiss = None
        CacheOptions = None
        CouldNotBeStored = None
        FromCache = None
        HishelHeaders = None
        IdleClient = None
        NeedRevalidation = None
        NeedToBeUpdated = None
        HishelRequest = None
        HishelResponse = None
        SqliteStorage = None
        StoreAndUse = None

from zapros._models import (
    AsyncClosableStream,
    ClosableStream,
    Headers,
    Request,
    Response,
    ResponseCachingContext,
    ResponseContext,
)

from ._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)
from ._sync_base import (
    BaseHandler,
    BaseMiddleware,
)

_AnyStorage = Union[HishelBaseStorage, HishelAsyncBaseStorage, None]

_CACHEABLE_METHODS = frozenset({"GET", "HEAD"})


class _BytesStream(AsyncIterator[bytes], Iterator[bytes]):
    def __init__(self, data: bytes) -> None:
        self._data: bytes | None = data

    def __next__(self) -> bytes:
        if self._data is None:
            raise StopIteration
        data, self._data = self._data, None
        return data

    async def __anext__(self) -> bytes:
        if self._data is None:
            raise StopAsyncIteration
        data, self._data = self._data, None
        return data


class _CachedStream(AsyncClosableStream, ClosableStream):
    def __init__(self, stream: AsyncIterator[bytes] | Iterator[bytes], upstream: Response | None) -> None:
        self._stream = stream
        self._upstream = upstream

    async def __anext__(self) -> bytes:
        assert isinstance(self._stream, AsyncIterator)
        return await anext(self._stream)

    def __next__(self) -> bytes:
        assert isinstance(self._stream, Iterator)
        return next(self._stream)

    async def aclose(self) -> None:
        # Closing the stream discards a partial save, but it doesn't reach the
        # stream it was reading from, so the upstream response is closed here.
        aclose = getattr(self._stream, "aclose", None)
        if aclose is not None:
            await aclose()
        if self._upstream is not None:
            await self._upstream.aclose()

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()
        if self._upstream is not None:
            self._upstream.close()


def _headers_to_hishel(headers: Headers) -> "HishelHeaders":
    grouped: dict[str, list[str]] = {}
    for key, value in headers.list():
        grouped.setdefault(key.lower(), []).append(value)
    # The body is stored without its transfer encoding.
    grouped.pop("transfer-encoding", None)
    return HishelHeaders(grouped)


def _headers_with_changes(original: Headers, wanted: "HishelHeaders") -> Headers:
    """
    Apply the headers the state machine added (for revalidation) to a copy of
    ``original``, leaving every other header as it was.
    """
    headers = original.copy()
    for key in wanted:
        value = wanted[key]
        if key not in original or ", ".join(original.getall(key)) != value:
            headers[key] = value
    return headers


def _request_to_hishel(request: Request) -> "HishelRequest":
    return HishelRequest(
        method=request.method,
        url=request.url.to_string(),
        headers=_headers_to_hishel(request.headers),
    )


def _read_response_to_hishel(response: Response, body: bytes) -> "HishelResponse":
    headers = _headers_to_hishel(response.headers)
    if "content-encoding" in headers:
        # Already read and decoded, so what we have no longer matches these headers.
        del headers["content-encoding"]
        headers.pop("content-length", None)
        headers["content-length"] = str(len(body))
    return HishelResponse(status_code=response.status, headers=headers, stream=_BytesStream(body))


def _response_to_zapros(
    response: "HishelResponse",
    request: Request,
    upstream: Response | None,
    *,
    from_cache: bool,
    revalidated: bool,
    stored: bool,
) -> Response:
    assert response.stream is not None
    context: ResponseContext = upstream.context.copy() if upstream is not None else {}
    context["caching"] = {"from_cache": from_cache, "revalidated": revalidated, "stored": stored}
    return Response(
        status=response.status_code,
        headers=[(key, value) for key in response.headers for value in response.headers.get_list(key) or []],
        content=_CachedStream(response.stream, upstream),
        context=context,
        request=request,
    )


def _not_stored(response: Response) -> Response:
    caching: ResponseCachingContext = {"from_cache": False, "revalidated": False, "stored": False}
    response.context["caching"] = caching
    return response


class CacheMiddleware(AsyncBaseMiddleware, BaseMiddleware):
    """
    By default, caches successful GET and HEAD responses by method and URL, ignoring
    HTTP caching headers, and serves an entry until the storage's TTL or TTI expires
    it. With ``rfc=True`` or ``hishel.CacheOptions``, follows RFC 9111 instead.

    The ``caching`` request context can override ``storage`` and ``rfc``, and set
    ``ttl``, ``tti`` and ``key``, for a single request.
    """

    @overload
    def __init__(
        self,
        next_handler: AsyncBaseHandler,
        *,
        storage: Union[HishelAsyncBaseStorage, None] = None,
        rfc: Union[bool, CacheOptions] = False,
    ) -> None: ...
    @overload
    def __init__(
        self,
        next_handler: BaseHandler,
        *,
        storage: Union[HishelBaseStorage, None] = None,
        rfc: Union[bool, CacheOptions] = False,
    ) -> None: ...
    def __init__(
        self,
        next_handler: AsyncBaseHandler | BaseHandler,
        *,
        storage: Union[HishelBaseStorage, HishelAsyncBaseStorage, None] = None,
        rfc: Union[bool, CacheOptions] = False,
    ) -> None:

        if CacheOptions is None:  # type: ignore[reportUnboundVariable]
            raise ImportError(
                "hishel is not installed. Install zapros with caching feature: pip install zapros[caching]"
            )

        self.next = cast(BaseMiddleware, next_handler)
        self.async_next = cast(
            AsyncBaseMiddleware,
            next_handler,
        )
        self._storage: _AnyStorage = storage
        self._rfc = rfc

    def _get_async_storage(  # unasync: generate @cacheMiddleware
        self,
        storage: "_AnyStorage",
    ) -> HishelAsyncBaseStorage:
        if storage is None:
            if self._storage is None:
                self._storage = AsyncSqliteStorage()
            storage = self._storage
        if not isinstance(storage, HishelAsyncBaseStorage):
            raise TypeError("Incompatible storage type")
        return storage

    def _get_sync_storage(  # unasync: generated @cacheMiddleware
        self,
        storage: "_AnyStorage",
    ) -> HishelBaseStorage:
        if storage is None:
            if self._storage is None:
                self._storage = SqliteStorage()
            storage = self._storage
        if not isinstance(storage, HishelBaseStorage):
            raise TypeError("Incompatible storage type")
        return storage

    async def ahandle(self, request: Request) -> Response:  # unasync: generate @cacheMiddleware
        caching = request.context.get("caching", {})
        force = caching.get("force", False)
        if force and request.method not in _CACHEABLE_METHODS and "key" not in caching:
            raise ValueError(
                f"Forcing the cache for a {request.method} request requires an explicit `key` in the caching "
                "context, because the default key doesn't include the request body."
            )
        storage = self._get_async_storage(caching.get("storage"))
        # A forced request is cached by method and URL whatever the headers say, so RFC 9111 doesn't apply.
        rfc = False if force else caching.get("rfc", self._rfc)
        key = caching.get("key")
        if key is None:
            # In RFC mode, all methods share a key, so that an unsafe request finds the entries it invalidates.
            url = request.url.to_string()
            identity = f"RFC {url}" if rfc is not False else f"{request.method} {url}"
            key = hashlib.sha256(identity.encode()).hexdigest()

        ttl, tti = caching.get("ttl"), caching.get("tti")
        if rfc is False:
            return await self._ahandle_without_rfc(request, storage, key, ttl, tti, force)
        options = CacheOptions() if rfc is True else rfc
        return await self._ahandle_with_rfc(request, storage, key, options, ttl, tti)

    def handle(self, request: Request) -> Response:  # unasync: generated @cacheMiddleware
        caching = request.context.get("caching", {})
        force = caching.get("force", False)
        if force and request.method not in _CACHEABLE_METHODS and "key" not in caching:
            raise ValueError(
                f"Forcing the cache for a {request.method} request requires an explicit `key` in the caching "
                "context, because the default key doesn't include the request body."
            )
        storage = self._get_sync_storage(caching.get("storage"))
        # A forced request is cached by method and URL whatever the headers say, so RFC 9111 doesn't apply.
        rfc = False if force else caching.get("rfc", self._rfc)
        key = caching.get("key")
        if key is None:
            # In RFC mode, all methods share a key, so that an unsafe request finds the entries it invalidates.
            url = request.url.to_string()
            identity = f"RFC {url}" if rfc is not False else f"{request.method} {url}"
            key = hashlib.sha256(identity.encode()).hexdigest()

        ttl, tti = caching.get("ttl"), caching.get("tti")
        if rfc is False:
            return self._handle_without_rfc(request, storage, key, ttl, tti, force)
        options = CacheOptions() if rfc is True else rfc
        return self._handle_with_rfc(request, storage, key, options, ttl, tti)

    async def _ahandle_without_rfc(  # unasync: generate @cacheMiddleware
        self,
        request: Request,
        storage: HishelAsyncBaseStorage,
        key: str,
        ttl: float | None,
        tti: float | None,
        force: bool,
    ) -> Response:
        if request.method not in _CACHEABLE_METHODS and not force:
            return _not_stored(await self.async_next.ahandle(request))

        # A custom key can be shared by GET and HEAD, whose responses aren't interchangeable.
        entries = [entry for entry in await storage.get_entries(key) if entry.request.method == request.method]
        if entries:
            return _response_to_zapros(
                entries[0].response, request, None, from_cache=True, revalidated=False, stored=False
            )

        response = await self.async_next.ahandle(request)
        # A 206 only holds part of the body, so it can't answer later requests.
        if not response.is_success or response.status == 206:
            return _not_stored(response)

        entry = await storage.create_entry(
            _request_to_hishel(request),
            await self._async_to_hishel(response),
            key,
            ttl=ttl,
            tti=tti,
        )
        return _response_to_zapros(entry.response, request, response, from_cache=False, revalidated=False, stored=True)

    def _handle_without_rfc(  # unasync: generated @cacheMiddleware
        self,
        request: Request,
        storage: HishelBaseStorage,
        key: str,
        ttl: float | None,
        tti: float | None,
        force: bool,
    ) -> Response:
        if request.method not in _CACHEABLE_METHODS and not force:
            return _not_stored(self.next.handle(request))

        # A custom key can be shared by GET and HEAD, whose responses aren't interchangeable.
        entries = [entry for entry in storage.get_entries(key) if entry.request.method == request.method]
        if entries:
            return _response_to_zapros(
                entries[0].response, request, None, from_cache=True, revalidated=False, stored=False
            )

        response = self.next.handle(request)
        # A 206 only holds part of the body, so it can't answer later requests.
        if not response.is_success or response.status == 206:
            return _not_stored(response)

        entry = storage.create_entry(
            _request_to_hishel(request),
            self._sync_to_hishel(response),
            key,
            ttl=ttl,
            tti=tti,
        )
        return _response_to_zapros(entry.response, request, response, from_cache=False, revalidated=False, stored=True)

    async def _ahandle_with_rfc(  # unasync: generate @cacheMiddleware
        self,
        request: Request,
        storage: HishelAsyncBaseStorage,
        key: str,
        options: CacheOptions,
        ttl: float | None,
        tti: float | None,
    ) -> Response:
        hishel_request = _request_to_hishel(request)
        state: AnyState = IdleClient(options=options)
        revalidated = False
        upstream: Response | None = None

        while True:
            if isinstance(state, IdleClient):
                state = state.next(hishel_request, await storage.get_entries(key))
            elif isinstance(state, (CacheMiss, NeedRevalidation)):
                # A 304 that matches nothing leads to a plain request, whose response isn't revalidated.
                revalidated = isinstance(state, NeedRevalidation)
                response = await self._async_send(request, state.request)
                if response.status == 304:
                    # The body served will be the cached one, so this response is done.
                    await response.aread()
                else:
                    upstream = response
                state = state.next(await self._async_to_hishel(response))
            elif isinstance(state, StoreAndUse):
                entry = await storage.create_entry(hishel_request, state.response, key, ttl=ttl, tti=tti)
                return _response_to_zapros(
                    entry.response, request, upstream, from_cache=False, revalidated=revalidated, stored=True
                )
            elif isinstance(state, CouldNotBeStored):
                return _response_to_zapros(
                    state.response, request, upstream, from_cache=False, revalidated=revalidated, stored=False
                )
            elif isinstance(state, FromCache):
                return _response_to_zapros(
                    state.entry.response, request, upstream, from_cache=True, revalidated=revalidated, stored=False
                )
            elif isinstance(state, NeedToBeUpdated):
                for updating_entry in state.updating_entries:
                    await storage.update_headers(updating_entry.id, updating_entry.response.headers)
                state = state.next()
            else:
                for entry_id in state.entry_ids:
                    await storage.remove_entry(entry_id)
                state = state.next()

    def _handle_with_rfc(  # unasync: generated @cacheMiddleware
        self,
        request: Request,
        storage: HishelBaseStorage,
        key: str,
        options: CacheOptions,
        ttl: float | None,
        tti: float | None,
    ) -> Response:
        hishel_request = _request_to_hishel(request)
        state: AnyState = IdleClient(options=options)
        revalidated = False
        upstream: Response | None = None

        while True:
            if isinstance(state, IdleClient):
                state = state.next(hishel_request, storage.get_entries(key))
            elif isinstance(state, (CacheMiss, NeedRevalidation)):
                # A 304 that matches nothing leads to a plain request, whose response isn't revalidated.
                revalidated = isinstance(state, NeedRevalidation)
                response = self._sync_send(request, state.request)
                if response.status == 304:
                    # The body served will be the cached one, so this response is done.
                    response.read()
                else:
                    upstream = response
                state = state.next(self._sync_to_hishel(response))
            elif isinstance(state, StoreAndUse):
                entry = storage.create_entry(hishel_request, state.response, key, ttl=ttl, tti=tti)
                return _response_to_zapros(
                    entry.response, request, upstream, from_cache=False, revalidated=revalidated, stored=True
                )
            elif isinstance(state, CouldNotBeStored):
                return _response_to_zapros(
                    state.response, request, upstream, from_cache=False, revalidated=revalidated, stored=False
                )
            elif isinstance(state, FromCache):
                return _response_to_zapros(
                    state.entry.response, request, upstream, from_cache=True, revalidated=revalidated, stored=False
                )
            elif isinstance(state, NeedToBeUpdated):
                for updating_entry in state.updating_entries:
                    storage.update_headers(updating_entry.id, updating_entry.response.headers)
                state = state.next()
            else:
                for entry_id in state.entry_ids:
                    storage.remove_entry(entry_id)
                state = state.next()

    async def _async_send(  # unasync: generate @cacheMiddleware
        self,
        request: Request,
        hishel_request: "HishelRequest",
    ) -> Response:
        # The original request is what gets sent, so that nothing about it is lost.
        # The state machine only changes it to add revalidation headers, and those
        # are only for this send, so the caller never sees them.
        original_headers = request.headers
        request.headers = _headers_with_changes(original_headers, hishel_request.headers)
        try:
            return await self.async_next.ahandle(request)
        finally:
            request.headers = original_headers

    def _sync_send(  # unasync: generated @cacheMiddleware
        self,
        request: Request,
        hishel_request: "HishelRequest",
    ) -> Response:
        # The original request is what gets sent, so that nothing about it is lost.
        # The state machine only changes it to add revalidation headers, and those
        # are only for this send, so the caller never sees them.
        original_headers = request.headers
        request.headers = _headers_with_changes(original_headers, hishel_request.headers)
        try:
            return self.next.handle(request)
        finally:
            request.headers = original_headers

    async def _async_to_hishel(self, response: Response) -> "HishelResponse":  # unasync: generate @cacheMiddleware
        if response.consumed:
            return _read_response_to_hishel(response, await response.aread())
        return HishelResponse(
            status_code=response.status,
            headers=_headers_to_hishel(response.headers),
            stream=response.async_iter_raw(),
        )

    def _sync_to_hishel(self, response: Response) -> "HishelResponse":  # unasync: generated @cacheMiddleware
        if response.consumed:
            return _read_response_to_hishel(response, response.read())
        return HishelResponse(
            status_code=response.status,
            headers=_headers_to_hishel(response.headers),
            stream=response.iter_raw(),
        )

    async def aclose(self) -> None:  # unasync: generate @cacheMiddleware
        if isinstance(self._storage, HishelAsyncBaseStorage):
            await self._storage.close()

    def close(self) -> None:  # unasync: generated @cacheMiddleware
        if isinstance(self._storage, HishelBaseStorage):
            self._storage.close()


@typing_extensions.deprecated(
    "CachingHandler is deprecated, use CacheMiddleware instead. "
    "The name 'Handler' was misleading as this is a middleware, not a terminal handler."
)
class CachingHandler(CacheMiddleware):
    pass
