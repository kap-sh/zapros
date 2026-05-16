import json as json_module
from collections.abc import (
    AsyncIterator,
    Iterator,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
    TypeAlias,
    TypedDict,
    TypeVar,
    Union,
    overload,
)

import typing_extensions
from pywhatwgurl import URL, URLSearchParams
from typing_extensions import deprecated

from zapros._errors import AsyncSyncMismatchError, ResponseNotRead, StatusCodeError, StreamExhausted
from zapros._io._base import AsyncBaseNetworkStream, BaseNetworkStream
from zapros._multidict import (
    CIMultiDict,
)
from zapros._utils import get_host_header_value

if TYPE_CHECKING:
    from zapros._handlers._asgi import AsgiWebSocketStream

    from ._multipart import Multipart


from ._constants import (
    CHUNK_SIZE,
    USER_AGENT,
)
from ._decoders import (
    ACCEPT_ENCODING,
    SUPPORTED_DECODERS,
    ByteChunker,
    ContentDecoder,
    IdentityDecoder,
    MultiDecoder,
    TextDecoder,
)


class ClosableStream(Iterator[bytes]):
    def close(self) -> None:
        pass


class TimeoutsContext(TypedDict, total=False):
    connect: float
    read: float
    write: float
    total: float


class CachingContext(TypedDict, total=False):
    """
    When set, indicates that the response to this request should be cached with the specified TTL (in seconds).
    """

    ttl: float

    """
    Indicates that the cache entry should be refreshed on access,
    meaning that the TTL will be reset to the original value whenever the cache entry is accessed.
    """
    refresh_ttl_on_access: bool

    """
    When set, indicates that the cache key should include the request body,
    note that zapros will read the body to include it in the cache key,
    so this should only be used with replayable request bodies.
    """
    body_key: str


class ProxyContext(TypedDict, total=False):
    url: str | URL
    server_hostname: str


class NetworkContext(TypedDict, total=False):
    proxy: ProxyContext


class RequestContext(TypedDict, total=False):
    timeouts: TimeoutsContext
    caching: CachingContext
    network: NetworkContext


class ResponseCachingContext(TypedDict, total=False):
    from_cache: bool
    revalidated: bool
    stored: bool
    created_at: float


class ResponseHandoffContext(TypedDict, total=False):
    network_stream: AsyncBaseNetworkStream | BaseNetworkStream
    trailing_data: bytes
    _asgi_websocket_stream: "AsgiWebSocketStream"


class ResponseContext(TypedDict, total=False):
    caching: ResponseCachingContext
    handoff: ResponseHandoffContext


Stream: TypeAlias = Union[Iterator[bytes], ClosableStream]


class AsyncClosableStream(AsyncIterator[bytes]):
    async def aclose(self) -> None:
        pass


AsyncStream: TypeAlias = Union[
    AsyncIterator[bytes],
    AsyncClosableStream,
]

_T = TypeVar("_T")
_MISSING = object()


class Headers(MutableMapping[str, str]):
    __slots__ = ("_headers",)

    def __init__(
        self,
        headers: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
    ) -> None:
        self._headers: CIMultiDict[str] = CIMultiDict(headers or ())

    def getall(self, key: str) -> list[str]:
        return self._headers.getall(key)

    def add(self, key: str, value: str) -> None:
        self._headers.add(key, value)

    def extend(
        self,
        headers: Mapping[str, str] | Iterable[tuple[str, str]],
    ) -> None:
        self._headers.extend(headers)

    def copy(self) -> "Headers":
        return Headers(self._headers.copy())

    def list(self) -> list[tuple[str, str]]:
        return list(self._headers.items())

    def __getitem__(self, key: str) -> str:
        return self._headers[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._headers[key] = value

    def __delitem__(self, key: str) -> None:
        del self._headers[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._headers)

    def __len__(self) -> int:
        return len(self._headers)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({list(self._headers.items())!r})"


class Request:
    __slots__ = (
        "url",
        "method",
        "headers",
        "body",
        "context",
    )

    @overload
    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        json: Any,
        context: RequestContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ],
        context: RequestContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        body: bytes | Stream | AsyncStream,
        context: RequestContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        multipart: "Multipart",
        context: RequestContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        text: str,
        context: RequestContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        context: RequestContext | None = None,
    ) -> None: ...

    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers | Mapping[str, str] | None = None,
        *,
        json: Any | None = None,
        form: Union[
            str,
            Iterable[Sequence[str]],
            Mapping[str, Union[str, Sequence[str]]],
            URLSearchParams,
        ]
        | None = None,
        body: bytes | Stream | AsyncStream | None = None,
        multipart: "Multipart | None" = None,
        text: str | None = None,
        context: RequestContext | None = None,
    ) -> None:
        self.url = url
        self.method = method
        self.headers: Headers = headers if isinstance(headers, Headers) else Headers(headers)
        self.context: RequestContext = context if context is not None else {}

        if "host" not in self.headers and url.hostname:
            self.headers.add(
                "Host",
                get_host_header_value(url.hostname, url.protocol[:-1], url.port),
            )

        if "accept" not in self.headers:
            self.headers.add("Accept", "*/*")
        if "user-agent" not in self.headers:
            self.headers.add("User-Agent", USER_AGENT)
        if "accept-encoding" not in self.headers:
            self.headers.add(
                "Accept-Encoding",
                ACCEPT_ENCODING,
            )

        request_body: bytes | Stream | AsyncStream | None = None

        if json is not None:
            request_body = json_module.dumps(
                json,
                separators=(
                    ",",
                    ":",
                ),
                ensure_ascii=False,
            ).encode("utf-8")
            if "Content-Type" not in self.headers:
                self.headers.add(
                    "Content-Type",
                    "application/json",
                )
        elif form is not None:
            request_body = URLSearchParams(form).to_string().encode("utf-8")
            if "Content-Type" not in self.headers:
                self.headers.add(
                    "Content-Type",
                    "application/x-www-form-urlencoded",
                )
        elif multipart is not None:
            request_body = multipart.to_async_body()
            if "Content-Type" not in self.headers:
                self.headers.add(
                    "Content-Type",
                    multipart.content_type,
                )
        elif text is not None:
            request_body = text.encode("utf-8")
            if "Content-Type" not in self.headers:
                self.headers.add(
                    "Content-Type",
                    "text/plain; charset=utf-8",
                )
        elif body is not None:
            request_body = body

        self.body = request_body

        if isinstance(request_body, bytes):
            if "content-length" not in self.headers:
                self.headers.add(
                    "Content-Length",
                    str(len(request_body)),
                )
        elif isinstance(
            request_body,
            (
                Iterator,
                AsyncIterator,
            ),
        ):
            if "transfer-encoding" not in self.headers and "content-length" not in self.headers:
                self.headers.add(
                    "Transfer-Encoding",
                    "chunked",
                )

    def is_replayable(self) -> bool:
        if self.body is None:
            return True
        if isinstance(self.body, bytes):
            return True
        return False

    def __repr__(self) -> str:
        return f"Request(method={self.method!r}, url={str(self.url)!r})"


class Response:
    __slots__ = (
        "status",
        "headers",
        "_content",
        "_decoded_content",
        "_decoder",
        "_consumed",
        "context",
    )

    @overload
    def __init__(
        self,
        status: int,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        content: AsyncStream | Stream | bytes | None,
        context: ResponseContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        status: int,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        text: str,
        context: ResponseContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        status: int,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        json: Any,
        context: ResponseContext | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        status: int,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        context: ResponseContext | None = None,
    ) -> None: ...

    def __init__(
        self,
        status: int,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        content: AsyncStream | Stream | bytes | None = None,
        text: str | None = None,
        json: Any | None = None,
        context: ResponseContext | None = None,
    ) -> None:
        provided_bodies = sum(value is not None for value in (content, text, json))
        if provided_bodies > 1:
            raise ValueError("Only one of `content`, `text`, or `json` may be provided.")

        self.status = status
        self.headers: Headers = headers if isinstance(headers, Headers) else Headers(headers) if headers else Headers()
        self.context: ResponseContext = context if context is not None else {}
        self._content: AsyncStream | Stream | bytes | None = content
        self._decoded_content: bytes | None = None
        self._decoder: ContentDecoder | None = None

        if text is not None:
            encoding = self.encoding
            self._set_static_content(
                text.encode(encoding),
                content_type="text/plain; charset=utf-8",
            )
        elif json is not None:
            self._set_static_content(
                json_module.dumps(json).encode("utf-8"),
                content_type="application/json; charset=utf-8",
            )

        # Static content (bytes, text=, json=) and absent content are always
        # considered consumed -- there's no underlying stream to exhaust, so the
        # body is either immediately available or not present at all.
        self._consumed: bool = isinstance(self._content, bytes) or self._content is None

        if isinstance(self._content, bytes):
            if "content-length" not in self.headers:
                self.headers.add("Content-Length", str(len(self._content)))
        elif isinstance(self._content, (Iterator, AsyncIterator)):
            if "transfer-encoding" not in self.headers and "content-length" not in self.headers:
                self.headers.add("Transfer-Encoding", "chunked")

    def raise_for_status(self) -> None:
        """
        Raises a `StatusCodeError` if the response status code is in the 4xx or 5xx range.
        """
        if 400 <= self.status < 600:
            raise StatusCodeError(
                self,
                f"HTTP error status code: {self.status}",
            )

    @property
    def encoding(self) -> str:
        content_type = self.headers.get("Content-Type") or ""
        for part in content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                return part[8:].strip().strip('"')
        return "utf-8"

    @property
    def consumed(self) -> bool:
        """
        Whether the response body stream has been fully read.

        Returns `True` if the body was provided as static content (bytes, text, or json),
        if no body was provided at all, or if the underlying stream has been exhausted by
        any of the iter/read methods. Returns `False` if a streaming body has been
        provided but not yet fully consumed.
        """
        return self._consumed

    @property
    @deprecated("Use `.read` or `.aread` to get the decoded content instead of accessing `.content` directly")
    def content(self) -> bytes | None:
        """
        The decoded response body, if it has been read. Returns `None` if the body
        has not yet been read. Call `.read()` or `.aread()` to read the body first.
        """
        return self._decoded_content

    @property
    def json(self) -> Any:
        """
        Decodes the response body using the response encoding and parses it as JSON.

        Returns the deserialized Python object.

        The response body must have been read first by calling `.read()` or `.aread()`.
        """
        return json_module.loads(self.text)

    @property
    def text(self) -> str:
        """
        Decodes the response body using the response encoding and returns it as a string.

        The response body must have been read first by calling `.read()` or `.aread()`.
        """
        if self._decoded_content is None:
            if self._content is None:
                return ""
            raise ResponseNotRead(
                "Response body has not been read yet. Call `.read()` or "
                "`.aread()` first to read the body before accessing `.text`.",
            )

        return self._decoded_content.decode(self.encoding)

    @typing_extensions.deprecated("Use `.aread()` and then `.text` instead")
    async def atext(self) -> str:
        """
        Asynchronously reads the entire response body (if it has not already been read),
        decodes it using the response encoding, and returns it as a string.

        If the body has already been consumed, this method behaves the same as `.text`,
        since there is no remaining content to read.

        This is a convenience helper for streaming responses, allowing you to read and
        decode the body in a single call instead of calling `.aread()` and then `.text`
        manually.
        """
        return (await self.aread()).decode(self.encoding)

    async def async_iter_text(  # unasync: generate
        self,
        chunk_size: int | None = None,
    ) -> AsyncIterator[str]:
        decoder = TextDecoder(encoding=self.encoding)
        async for chunk in self.async_iter_bytes(chunk_size):
            yield decoder.decode(chunk)
        remaining = decoder.flush()
        if remaining:
            yield remaining

    def iter_text(  # unasync: generated
        self,
        chunk_size: int | None = None,
    ) -> Iterator[str]:
        decoder = TextDecoder(encoding=self.encoding)
        for chunk in self.iter_bytes(chunk_size):
            yield decoder.decode(chunk)
        remaining = decoder.flush()
        if remaining:
            yield remaining

    async def async_iter_bytes(  # unasync: generate
        self,
        chunk_size: int | None = None,
    ) -> AsyncIterator[bytes]:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE

        if self._decoded_content is not None:
            chunker = ByteChunker(chunk_size)
            for chunk in chunker.feed(self._decoded_content):
                yield chunk
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        decoder = self._get_content_decoder()
        chunker = ByteChunker(chunk_size)

        async for raw_chunk in self._async_iter_source():
            decoded_chunk = decoder.decode(raw_chunk)
            if decoded_chunk:
                for chunk in chunker.feed(decoded_chunk):
                    yield chunk

        final_decoded = decoder.flush()
        if final_decoded:
            for chunk in chunker.feed(final_decoded):
                yield chunk

        remaining = chunker.flush()
        if remaining:
            yield remaining

    def iter_bytes(  # unasync: generated
        self,
        chunk_size: int | None = None,
    ) -> Iterator[bytes]:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE

        if self._decoded_content is not None:
            chunker = ByteChunker(chunk_size)
            for chunk in chunker.feed(self._decoded_content):
                yield chunk
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        decoder = self._get_content_decoder()
        chunker = ByteChunker(chunk_size)

        for raw_chunk in self._iter_source():
            decoded_chunk = decoder.decode(raw_chunk)
            if decoded_chunk:
                for chunk in chunker.feed(decoded_chunk):
                    yield chunk

        final_decoded = decoder.flush()
        if final_decoded:
            for chunk in chunker.feed(final_decoded):
                yield chunk

        remaining = chunker.flush()
        if remaining:
            yield remaining

    async def async_iter_raw(  # unasync: generate
        self,
        chunk_size: int | None = None,
    ) -> AsyncIterator[bytes]:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE

        chunker = ByteChunker(chunk_size)
        async for raw_chunk in self._async_iter_source():
            for chunk in chunker.feed(raw_chunk):
                yield chunk
        remaining = chunker.flush()
        if remaining:
            yield remaining

    def iter_raw(  # unasync: generated
        self,
        chunk_size: int | None = None,
    ) -> Iterator[bytes]:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE

        chunker = ByteChunker(chunk_size)
        for raw_chunk in self._iter_source():
            for chunk in chunker.feed(raw_chunk):
                yield chunk
        remaining = chunker.flush()
        if remaining:
            yield remaining

    async def _async_iter_source(self) -> AsyncIterator[bytes]:  # unasync: generate
        if self._content is None:
            return
        if isinstance(self._content, bytes):
            yield self._content
            return
        if self._consumed:
            raise StreamExhausted(
                "The response body has already been consumed. Call `.aread()` first "
                "to cache the body before iterating multiple times."
            )
        if not isinstance(self._content, AsyncIterator):
            raise AsyncSyncMismatchError("Can't iterate content in this context")
        async for chunk in self._content:
            yield chunk
        self._consumed = True

    def _iter_source(self) -> Iterator[bytes]:  # unasync: generated
        if self._content is None:
            return
        if isinstance(self._content, bytes):
            yield self._content
            return
        if self._consumed:
            raise StreamExhausted(
                "The response body has already been consumed. Call `.read()` first "
                "to cache the body before iterating multiple times."
            )
        if not isinstance(self._content, Iterator):
            raise AsyncSyncMismatchError("Can't iterate content in this context")
        for chunk in self._content:
            yield chunk
        self._consumed = True

    async def aread(self) -> bytes:  # unasync: generate
        if self._decoded_content is not None:
            return self._decoded_content
        chunks: list[bytes] = []
        async for chunk in self.async_iter_bytes():
            chunks.append(chunk)
        self._decoded_content = b"".join(chunks)
        return self._decoded_content

    def read(self) -> bytes:  # unasync: generated
        if self._decoded_content is not None:
            return self._decoded_content
        chunks: list[bytes] = []
        for chunk in self.iter_bytes():
            chunks.append(chunk)
        self._decoded_content = b"".join(chunks)
        return self._decoded_content

    async def aclose(self) -> None:  # unasync: generate
        if self._content is None or isinstance(self._content, bytes):
            return

        if not isinstance(self._content, AsyncIterator):
            raise AsyncSyncMismatchError("Can't call `aclose` in this context")
        if isinstance(self._content, AsyncClosableStream):
            await self._content.aclose()

    def close(self) -> None:  # unasync: generated
        if self._content is None or isinstance(self._content, bytes):
            return

        if not isinstance(self._content, Iterator):
            raise AsyncSyncMismatchError("Can't call `close` in this context")
        if isinstance(self._content, ClosableStream):
            self._content.close()

    def _set_static_content(self, data: bytes, *, content_type: str) -> None:
        self._content = data
        self._decoded_content = data

        self.headers.pop("Content-Encoding", None)

        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = content_type

    def _get_content_decoder(self) -> ContentDecoder:
        if self._decoder is not None:
            return self._decoder

        encoding_header = self.headers.get("Content-Encoding")
        if not encoding_header:
            self._decoder = IdentityDecoder()
            return self._decoder

        encodings = [enc.strip().lower() for enc in encoding_header.split(",")]
        decoders: list[ContentDecoder] = []

        for encoding in encodings:
            if encoding in SUPPORTED_DECODERS:
                decoders.append(SUPPORTED_DECODERS[encoding]())
            elif encoding and encoding != "identity":
                pass

        if not decoders:
            self._decoder = IdentityDecoder()
        elif len(decoders) == 1:
            self._decoder = decoders[0]
        else:
            self._decoder = MultiDecoder(decoders)

        return self._decoder

    def __repr__(self) -> str:
        return f"Response(status={self.status!r})"

    def __enter__(self) -> "Response":
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        self.close()

    async def __aenter__(self) -> "Response":
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        await self.aclose()
