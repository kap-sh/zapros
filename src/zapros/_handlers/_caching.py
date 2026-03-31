from typing import (
    TYPE_CHECKING,
    AsyncIterable,
    AsyncIterator,
    Iterable,
    Iterator,
    Union,
    cast,
    overload,
)

import typing_extensions

if TYPE_CHECKING:
    from hishel import (
        AsyncBaseStorage as HishelAsyncBaseStorage,
        AsyncCacheProxy,
        CachePolicy,
        Headers,
        Request as HishelRequest,
        Response as HishelResponse,
        SyncBaseStorage as HishelSyncBaseStorage,
        SyncCacheProxy,
    )
else:
    try:
        from hishel import (
            AsyncBaseStorage as HishelAsyncBaseStorage,
            AsyncCacheProxy,
            CachePolicy,
            Headers,
            Request as HishelRequest,
            Response as HishelResponse,
            SyncBaseStorage as HishelSyncBaseStorage,
            SyncCacheProxy,
        )
    except ImportError:
        HishelAsyncBaseStorage = None
        AsyncCacheProxy = None
        CachePolicy = None
        Headers = None
        HishelRequest = None
        HishelResponse = None
        HishelSyncBaseStorage = None
        SyncCacheProxy = None
from pywhatwgurl import URL

from zapros._models import (
    Request,
    Response,
    ResponseCachingContext,
)

from ._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)
from ._sync_base import (
    BaseHandler,
    BaseMiddleware,
)


class _BytesStream(
    AsyncIterable[bytes],
    Iterable[bytes],
):
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._sent = False

    def __iter__(
        self,
    ) -> "_BytesStream":
        return self

    def __next__(self) -> bytes:
        if self._sent:
            raise StopIteration
        self._sent = True
        return self._data

    def __aiter__(
        self,
    ) -> "_BytesStream":
        return self

    async def __anext__(self) -> bytes:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return self._data


@overload
def _zapros_to_hishel(
    model: Request,
) -> "HishelRequest": ...
@overload
def _zapros_to_hishel(
    model: Response,
) -> "HishelResponse": ...
def _zapros_to_hishel(
    model: Request | Response,
) -> Union["HishelRequest", "HishelResponse"]:

    if isinstance(model, Request):
        stream: Iterator[bytes] | AsyncIterator[bytes]

        if model.body is None:
            stream = _BytesStream(b"")
        elif isinstance(model.body, bytes):
            stream = _BytesStream(model.body)
        else:
            stream = model.body
        return HishelRequest(
            method=model.method,
            url=str(model.url.to_string()),
            headers=Headers(dict(model.headers.list())),
            stream=stream,
            metadata={"hishel_" + key: value for key, value in model.context.get("caching", {}).items()},
        )
    else:
        stream: Iterator[bytes] | AsyncIterator[bytes]

        if model.content is None:
            stream = _BytesStream(b"")
        elif isinstance(model.content, bytes):
            stream = _BytesStream(model.content)
        else:
            stream = model.content

        return HishelResponse(
            status_code=model.status,
            headers=Headers(dict(model.headers.list())),
            stream=stream,
            metadata={},
        )


@overload
def _hishel_to_zapros(
    model: "HishelRequest",
) -> Request: ...
@overload
def _hishel_to_zapros(
    model: "HishelResponse",
) -> Response: ...
def _hishel_to_zapros(
    model: Union[HishelRequest, HishelResponse],
) -> Request | Response:
    if isinstance(model, HishelRequest):
        return Request(
            method=model.method,
            url=URL(model.url),
            headers=Headers(dict(model.headers)),
            body=model.stream,
            context={
                "caching": {
                    key.removeprefix("hishel_"): value
                    for key, value in model.metadata.items()
                    if key.startswith("hishel_")
                }  # type: ignore
            },
        )
    else:
        context: ResponseCachingContext = {}

        if "hishel_from_cache" in model.metadata:
            context["from_cache"] = model.metadata["hishel_from_cache"]
        if "hishel_created_at" in model.metadata:
            context["created_at"] = model.metadata["hishel_created_at"]
        if "hishel_revalidated" in model.metadata:
            context["revalidated"] = model.metadata["hishel_revalidated"]
        if "hishel_stored" in model.metadata:
            context["stored"] = model.metadata["hishel_stored"]

        return Response(
            status=model.status_code,
            headers=Headers(dict(model.headers)),
            content=model.stream,
            context={"caching": context},
        )


class CacheMiddleware(AsyncBaseMiddleware, BaseMiddleware):
    @overload
    def __init__(
        self,
        next_handler: AsyncBaseHandler,
        *,
        storage: Union[HishelAsyncBaseStorage, None] = None,
        policy: Union[CachePolicy, None] = None,
    ) -> None: ...
    @overload
    def __init__(
        self,
        next_handler: BaseHandler,
        *,
        storage: Union[HishelSyncBaseStorage, None] = None,
        policy: Union[CachePolicy, None] = None,
    ) -> None: ...
    def __init__(
        self,
        next_handler: AsyncBaseHandler | BaseHandler,
        *,
        storage: Union[HishelSyncBaseStorage, HishelAsyncBaseStorage, None] = None,
        policy: Union[CachePolicy, None] = None,
    ) -> None:

        if CachePolicy is None:  # type: ignore[reportUnboundVariable]
            raise ImportError(
                "hishel is not installed. Install zapros with caching feature: pip install zapros[caching]"
            )

        self.next = cast(BaseMiddleware, next_handler)
        self.async_next = cast(
            AsyncBaseMiddleware,
            next_handler,
        )
        self._storage = storage
        self._policy = policy
        self._cache_proxy: AsyncCacheProxy | SyncCacheProxy | None = None

    def _get_sync_cache_proxy(
        self,
    ) -> SyncCacheProxy:
        if self._cache_proxy is None:

            def _sync_send_request(
                request: HishelRequest,
            ) -> HishelResponse:
                zapros_request = _hishel_to_zapros(request)
                zapros_response = self.next.handle(zapros_request)
                return _zapros_to_hishel(zapros_response)

            assert (
                isinstance(
                    self._storage,
                    HishelSyncBaseStorage,
                )
                or self._storage is None
            ), "Sync handler requires sync storage"
            self._cache_proxy = SyncCacheProxy(
                request_sender=_sync_send_request,
                storage=self._storage,
                policy=self._policy,
            )

        if not isinstance(
            self._cache_proxy,
            SyncCacheProxy,
        ):
            raise TypeError("Cache proxy is not a SyncCacheProxy")
        return self._cache_proxy

    async def _get_async_cache_proxy(
        self,
    ) -> AsyncCacheProxy:
        if self._cache_proxy is None:

            async def _async_send_request(
                request: HishelRequest,
            ) -> HishelResponse:
                zapros_request = _hishel_to_zapros(request)
                zapros_response = await self.async_next.ahandle(zapros_request)
                return _zapros_to_hishel(zapros_response)

            assert (
                isinstance(
                    self._storage,
                    HishelAsyncBaseStorage,
                )
                or self._storage is None
            ), "Async handler requires async storage"
            self._cache_proxy = AsyncCacheProxy(
                request_sender=_async_send_request,
                storage=self._storage,
                policy=self._policy,
            )

        if not isinstance(
            self._cache_proxy,
            AsyncCacheProxy,
        ):
            raise TypeError("Cache proxy is not an AsyncCacheProxy")
        return self._cache_proxy

    async def ahandle(self, request: Request) -> Response:
        hishel_request = _zapros_to_hishel(request)
        proxy = await self._get_async_cache_proxy()
        hishel_response = await proxy.handle_request(hishel_request)
        return _hishel_to_zapros(hishel_response)

    def handle(self, request: Request) -> Response:
        hishel_request = _zapros_to_hishel(request)
        hishel_response = self._get_sync_cache_proxy().handle_request(hishel_request)
        return _hishel_to_zapros(hishel_response)


@typing_extensions.deprecated(
    "CachingHandler is deprecated, use CacheMiddleware instead. "
    "The name 'Handler' was misleading as this is a middleware, not a terminal handler."
)
class CachingHandler(CacheMiddleware):
    pass
