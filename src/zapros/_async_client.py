import base64
import sys
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
)
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Callable,
    Iterable,  # unasync: strip
    Mapping,
    Self,
    Sequence,
    Union,
    overload,
)

from pywhatwgurl import (
    URL,
    URLSearchParams,
)

from zapros._handlers._async_base import (
    AsyncBaseHandler,
    AsyncBaseMiddleware,
)

from ._models import (
    AsyncClosableStream,
    AsyncStream,
    Headers,
    Request,
    RequestContext,
    Response,
)

if TYPE_CHECKING:
    from zapros import AsyncBaseHandler

    from ._multipart import Multipart


class AsyncClient:
    @overload
    def __init__(
        self,
        handler: Union[None, "AsyncBaseHandler"] = None,
        *,
        default_headers: Mapping[str, str] | Headers | None = None,
        default_params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        handler: Union[None, "AsyncBaseHandler"] = None,
        *,
        default_headers: Mapping[str, str] | Headers | None = None,
        default_params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str],
    ) -> None: ...

    def __init__(
        self,
        handler: Union[None, "AsyncBaseHandler"] = None,
        *,
        default_headers: Mapping[str, str] | Headers | None = None,
        default_params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
    ) -> None:
        from zapros import (
            AsyncStdNetworkHandler,
        )

        if sys.platform == "emscripten" and handler is None:
            from zapros import (
                AsyncPyodideHandler,
            )

            self.handler = AsyncPyodideHandler()
        else:
            self.handler = handler if handler is not None else AsyncStdNetworkHandler()
        self.default_headers: Headers = (
            default_headers if isinstance(default_headers, Headers) else Headers(default_headers)
        )
        self.default_params = URLSearchParams(default_params)
        self.auth = auth

    def _merge_url(
        self,
        url: str | URL,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
    ) -> URL:
        url_obj = url if isinstance(url, URL) else URL(url)
        url_obj.search = URLSearchParams(
            {
                **self.default_params,
                **url_obj.search_params,
                **(URLSearchParams(params)),
            }
        ).to_string()
        return url_obj

    def _merge_headers(
        self,
        headers: Mapping[str, str] | Headers | None,
        auth: str | tuple[str, str] | None = None,
    ) -> Headers:
        merged = dict(self.default_headers.items())

        request_auth = auth if auth is not None else self.auth

        if request_auth is not None:
            if isinstance(request_auth, str):
                merged["Authorization"] = f"Bearer {request_auth}"
            else:
                username, password = request_auth
                credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                merged["Authorization"] = f"Basic {credentials}"

        if headers is not None:
            merged.update(headers.items() if isinstance(headers, Headers) else headers)
        return Headers(merged)

    @overload
    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        url_obj = self._merge_url(url, params)

        merged_headers = self._merge_headers(headers, auth=auth)

        if json is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                json=json,
            )
        elif form is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                form=form,
            )
        elif multipart is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                multipart=multipart,
            )
        elif body is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                body=body,
            )
        else:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
            )

        try:
            response = await self.handler.ahandle(request=request)

            try:
                await response.aread()
            finally:
                await response.aclose()
        finally:
            if isinstance(request.body, AsyncClosableStream):
                await request.body.aclose()

        return response

    @overload
    async def get(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def get(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def get(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def get(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def get(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def get(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "GET",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    async def post(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def post(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def post(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def post(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def post(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def post(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "POST",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    async def put(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def put(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def put(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def put(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def put(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def put(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "PUT",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    async def patch(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def patch(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def patch(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def patch(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def patch(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def patch(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "PATCH",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    async def delete(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def delete(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def delete(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def delete(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def delete(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def delete(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "DELETE",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    async def head(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def head(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def head(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def head(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def head(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def head(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "HEAD",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    async def options(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> Response: ...

    @overload
    async def options(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> Response: ...

    @overload
    async def options(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> Response: ...

    @overload
    async def options(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> Response: ...

    @overload
    async def options(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> Response: ...

    async def options(
        self,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return await self.request(  # type: ignore[call-overload]
            "OPTIONS",
            url,
            headers=headers,
            params=params,
            auth=auth,
            context=context,
            json=json,
            form=form,
            body=body,
            multipart=multipart,
        )

    @overload
    def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any,
    ) -> AbstractAsyncContextManager[Response]: ...

    @overload
    def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
    ) -> AbstractAsyncContextManager[Response]: ...

    @overload
    def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        body: bytes | AsyncStream,
    ) -> AbstractAsyncContextManager[Response]: ...

    @overload
    def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        multipart: "Multipart",
    ) -> AbstractAsyncContextManager[Response]: ...

    @overload
    def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
    ) -> AbstractAsyncContextManager[Response]: ...

    @asynccontextmanager  # type: ignore
    async def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        auth: str | tuple[str, str] | None = None,
        context: RequestContext | None = None,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
    ) -> AsyncIterable[Response]:  # type: ignore
        url_obj = self._merge_url(url, params)
        merged_headers = self._merge_headers(headers, auth=auth)

        if json is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                json=json,
            )
        elif form is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                form=form,
            )
        elif multipart is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                multipart=multipart,
            )
        elif body is not None:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
                body=body,
            )
        else:
            request = Request(
                method=method,
                url=url_obj,
                headers=merged_headers,
                context=context,
            )

        response = await self.handler.ahandle(request=request)

        try:
            yield response
        finally:
            await response.aclose()

    def wrap_with_middleware(
        self,
        factory: Callable[
            [AsyncBaseHandler],
            AsyncBaseMiddleware,
        ],
    ) -> Self:
        self.handler = factory(self.handler)
        return self

    async def aclose(self) -> None:
        handler_to_close: AsyncBaseHandler | None = self.handler

        while handler_to_close is not None:
            await handler_to_close.aclose()
            handler_to_close = (
                handler_to_close.async_next
                if isinstance(
                    handler_to_close,
                    AsyncBaseMiddleware,
                )
                else None
            )

    async def __aenter__(
        self,
    ) -> "AsyncClient":
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        await self.aclose()
