import base64
import sys
from contextlib import (
    AbstractContextManager,
    contextmanager,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Callable,
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

from zapros._handlers._sync_base import (
    BaseHandler,
    BaseMiddleware,
)

from ._models import (
    ClosableStream,
    Stream,
    Headers,
    Request,
    RequestContext,
    Response,
)

if TYPE_CHECKING:
    from zapros import BaseHandler

    from ._multipart import Multipart


class Client:
    @overload
    def __init__(
        self,
        handler: Union[None, "BaseHandler"] = None,
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
        handler: Union[None, "BaseHandler"] = None,
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
        handler: Union[None, "BaseHandler"] = None,
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
            StdNetworkHandler,
        )

        if sys.platform == "emscripten" and handler is None:
            from zapros import (
                PyodideHandler,
            )

            self.handler = PyodideHandler()
        else:
            self.handler = handler if handler is not None else StdNetworkHandler()
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
    def request(
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
    def request(
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
    def request(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def request(
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
    def request(
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

    def request(
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
        body: bytes | Stream | None = None,
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
            response = self.handler.handle(request=request)

            try:
                response.read()
            finally:
                response.close()
        finally:
            if isinstance(request.body, ClosableStream):
                request.body.close()

        return response

    @overload
    def get(
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
    def get(
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
    def get(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def get(
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
    def get(
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

    def get(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    def post(
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
    def post(
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
    def post(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def post(
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
    def post(
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

    def post(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    def put(
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
    def put(
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
    def put(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def put(
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
    def put(
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

    def put(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    def patch(
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
    def patch(
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
    def patch(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def patch(
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
    def patch(
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

    def patch(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    def delete(
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
    def delete(
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
    def delete(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def delete(
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
    def delete(
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

    def delete(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    def head(
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
    def head(
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
    def head(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def head(
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
    def head(
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

    def head(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    def options(
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
    def options(
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
    def options(
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
        body: bytes | Stream,
    ) -> Response: ...

    @overload
    def options(
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
    def options(
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

    def options(
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
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Response:
        return self.request(  # type: ignore[call-overload]
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
    ) -> AbstractContextManager[Response]: ...

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
    ) -> AbstractContextManager[Response]: ...

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
        body: bytes | Stream,
    ) -> AbstractContextManager[Response]: ...

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
    ) -> AbstractContextManager[Response]: ...

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
    ) -> AbstractContextManager[Response]: ...

    @contextmanager  # type: ignore
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
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | Stream | None = None,
        multipart: "Multipart | None" = None,
    ) -> Iterable[Response]:  # type: ignore
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

        response = self.handler.handle(request=request)

        try:
            yield response
        finally:
            response.close()

    def wrap_with_middleware(
        self,
        factory: Callable[
            [BaseHandler],
            BaseMiddleware,
        ],
    ) -> Self:
        self.handler = factory(self.handler)
        return self

    def close(self) -> None:
        handler_to_close: BaseHandler | None = self.handler

        while handler_to_close is not None:
            handler_to_close.close()
            handler_to_close = (
                handler_to_close.next
                if isinstance(
                    handler_to_close,
                    BaseMiddleware,
                )
                else None
            )

    def __enter__(
        self,
    ) -> "Client":
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        self.close()
