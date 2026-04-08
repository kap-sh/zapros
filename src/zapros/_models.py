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

from zapros._errors import AsyncSyncMismatchError, ResponseNotRead, StatusCodeError
from zapros._io._base import AsyncBaseNetworkStream, BaseNetworkStream
from zapros._multidict import (
    CIMultiDict,
)
from zapros._utils import get_host_header_value

if TYPE_CHECKING:
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
        "content",
        "_stream_to_close",
        "_decoder",
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
            raise ValueError("Only one of `content`, `body`, `text`, or `json_data` may be provided.")

        self.status = status
        self.headers: Headers = headers if isinstance(headers, Headers) else Headers(headers) if headers else Headers()
        self.content: AsyncStream | Stream | bytes | None = content
        self._stream_to_close: AsyncClosableStream | ClosableStream | None = (
            content if isinstance(content, (AsyncClosableStream, ClosableStream)) else None
        )
        self._decoder: ContentDecoder | None = None
        self.context: ResponseContext = context if context is not None else {}

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

        if isinstance(self.content, bytes):
            if "content-length" not in self.headers:
                self.headers.add("Content-Length", str(len(self.content)))
        elif isinstance(self.content, (Iterator, AsyncIterator)):
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
    def json(self) -> Any:
        """
        Reads the response body (if it has not already been read), decodes it using
        the response encoding, and parses it as JSON.

        Returns the deserialized Python object.
        """
        return json_module.loads(self.text)

    @typing_extensions.deprecated("Use `.aread()` and then `.json` instead")
    async def ajson(self) -> Any:
        """
        Asynchronously reads the response body (if it has not already been read),
        decodes it using the response encoding, and parses it as JSON.

        Returns the deserialized Python object.

        If the body has already been consumed, this method behaves the same as `.json()`,
        since there is no remaining content to read.

        This is a convenience helper for streaming responses, allowing you to read,
        decode, and parse the body in a single call instead of calling `.aread()`
        and then `.json()` manually.
        """
        return json_module.loads(self.text)

    @property
    def text(self) -> str:
        """
        Reads the entire response body (if it has not already been read),
        decodes it using the response encoding, and returns it as a string.
        """
        if self.content is not None and not isinstance(self.content, bytes):
            raise ResponseNotRead(
                "Response body has not been read yet. Call `.read()` or "
                "`.aread()`first to read the body before accessing `.text`.",
            )

        if self.content is None:
            return ""

        return self.content.decode(self.encoding)

    @typing_extensions.deprecated("Use `.aread()` and then `.text` instead")
    async def atext(self) -> str:
        """
        Asynchronously reads the entire response body (if it has not already been read),
        decodes it using the response encoding, and returns it as a string.

        If the body has already been consumed, this method behaves the same as `.text()`,
        since there is no remaining content to read.

        This is a convenience helper for streaming responses, allowing you to read and
        decode the body in a single call instead of calling `.aread()` and then `.text()`
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

        if isinstance(self.content, bytes):
            chunker = ByteChunker(chunk_size)
            for chunk in chunker.feed(self.content):
                yield chunk
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        if self.content is None:
            self.content = b""
            return

        if not isinstance(self.content, AsyncIterator):
            raise AsyncSyncMismatchError("Can't call `async_iter_bytes` in this context")

        decoder = self._get_content_decoder()
        chunker = ByteChunker(chunk_size)

        async for raw_chunk in self.content:
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

        if isinstance(self.content, bytes):
            chunker = ByteChunker(chunk_size)
            for chunk in chunker.feed(self.content):
                yield chunk
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        if self.content is None:
            self.content = b""
            return

        if not isinstance(self.content, Iterator):
            raise AsyncSyncMismatchError("Can't call `iter_bytes` in this context")

        decoder = self._get_content_decoder()
        chunker = ByteChunker(chunk_size)

        for raw_chunk in self.content:
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

        if isinstance(self.content, bytes):
            chunker = ByteChunker(chunk_size)
            for chunk in chunker.feed(self.content):
                yield chunk
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        if self.content is None:
            return

        if not isinstance(self.content, AsyncIterator):
            raise AsyncSyncMismatchError("Can't call `async_iter_raw` in this context.")

        chunker = ByteChunker(chunk_size)
        async for raw_chunk in self.content:
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

        if isinstance(self.content, bytes):
            chunker = ByteChunker(chunk_size)
            for chunk in chunker.feed(self.content):
                yield chunk
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        if self.content is None:
            return

        if not isinstance(self.content, Iterator):
            raise AsyncSyncMismatchError("Can't call `iter_raw` in this context.")

        chunker = ByteChunker(chunk_size)
        for raw_chunk in self.content:
            for chunk in chunker.feed(raw_chunk):
                yield chunk
        remaining = chunker.flush()
        if remaining:
            yield remaining

    async def aread(self) -> bytes:  # unasync: generate
        if isinstance(self.content, bytes):
            return self.content
        chunks: list[bytes] = []
        async for chunk in self.async_iter_bytes():
            chunks.append(chunk)
        self.content = b"".join(chunks)
        return self.content

    def read(self) -> bytes:  # unasync: generated
        if isinstance(self.content, bytes):
            return self.content
        chunks: list[bytes] = []
        for chunk in self.iter_bytes():
            chunks.append(chunk)
        self.content = b"".join(chunks)
        return self.content

    async def aclose(self) -> None:  # unasync: generate
        if self._stream_to_close is None:
            return

        if not isinstance(self._stream_to_close, AsyncClosableStream):
            raise AsyncSyncMismatchError("Can't call `aclose` in this context")

        await self._stream_to_close.aclose()
        self._stream_to_close = None

    def close(self) -> None:  # unasync: generated
        if self._stream_to_close is None:
            return

        if not isinstance(self._stream_to_close, ClosableStream):
            raise AsyncSyncMismatchError("Can't call `close` in this context")

        self._stream_to_close.close()
        self._stream_to_close = None

    def _set_static_content(self, data: bytes, *, content_type: str) -> None:
        self.content = data

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
