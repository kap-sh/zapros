import json as json_module
from collections.abc import (
    AsyncIterator as ABCAsyncIterator,
    Iterator as ABCIterator,
)
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
    TypeAlias,
    TypedDict,
    TypeVar,
    Union,
    overload,
)

from pywhatwgurl import URL, URLSearchParams

from zapros._errors import AsyncSyncMismatchError
from zapros._multidict import (
    CIMultiDict,
)

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


class RequestContext(TypedDict, total=False):
    timeouts: TimeoutsContext
    caching: CachingContext


class ResponseCachingContext(TypedDict, total=False):
    from_cache: bool
    revalidated: bool
    stored: bool
    created_at: float


class ResponseContext(TypedDict, total=False):
    caching: ResponseCachingContext


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
            self.headers.add("Host", url.hostname)

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
                ABCIterator,
                ABCAsyncIterator,
            ),
        ):
            if "transfer-encoding" not in self.headers and "content-length" not in self.headers:
                self.headers.add(
                    "Transfer-Encoding",
                    "chunked",
                )

    def __repr__(self) -> str:
        return f"Request(method={self.method!r}, url={str(self.url)!r})"

    def is_replayable(self) -> bool:
        if self.body is None:
            return True
        if isinstance(self.body, bytes):
            return True
        return False


class Response:
    __slots__ = (
        "status",
        "headers",
        "content",
        "_decoder",
        "_is_stream_consumed",
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
        self._decoder: ContentDecoder | None = None
        self._is_stream_consumed: bool = False
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
        elif isinstance(self.content, (ABCIterator, ABCAsyncIterator)):
            if "transfer-encoding" not in self.headers and "content-length" not in self.headers:
                self.headers.add("Transfer-Encoding", "chunked")

    def _set_static_content(self, data: bytes, *, content_type: str) -> None:
        self.content = data
        self._is_stream_consumed = True

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

    @property
    def encoding(self) -> str:
        content_type = self.headers.get("Content-Type") or ""
        for part in content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                return part[8:].strip().strip('"')
        return "utf-8"

    def json(self) -> Any:
        """
        Reads the response body (if it has not already been read), decodes it using
        the response encoding, and parses it as JSON.

        Returns the deserialized Python object.
        """
        return json_module.loads(self.text())

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
        return json_module.loads(await self.atext())

    def text(self) -> str:
        """
        Reads the entire response body (if it has not already been read),
        decodes it using the response encoding, and returns it as a string.
        """
        return self.read().decode(self.encoding)

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

    def iter_text(
        self,
        chunk_size: int | None = None,
    ) -> Iterator[str]:
        decoder = TextDecoder(encoding=self.encoding)
        for chunk in self.iter_bytes(chunk_size):
            yield decoder.decode(chunk)
        remaining = decoder.flush()
        if remaining:
            yield remaining

    async def async_iter_text(
        self,
        chunk_size: int | None = None,
    ) -> AsyncIterator[str]:
        decoder = TextDecoder(encoding=self.encoding)
        async for chunk in self.async_iter_bytes(chunk_size):
            yield decoder.decode(chunk)
        remaining = decoder.flush()
        if remaining:
            yield remaining

    def iter_bytes(
        self,
        chunk_size: int | None = None,
    ) -> Iterator[bytes]:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE

        if isinstance(self.content, bytes):
            chunker = ByteChunker(chunk_size)
            yield from chunker.feed(self.content)
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        if self.content is None:
            self.content = b""
            return

        if not isinstance(self.content, ABCIterator):
            raise AsyncSyncMismatchError(
                "The stream is not synchronous, try using `async_iter_bytes` instead of `iter_bytes`."
            )

        decoder = self._get_content_decoder()
        decoded_chunks: list[bytes] = []

        for raw_chunk in self.content:
            decoded_chunk = decoder.decode(raw_chunk)
            if decoded_chunk:
                decoded_chunks.append(decoded_chunk)

        final_decoded = decoder.flush()
        if final_decoded:
            decoded_chunks.append(final_decoded)

        body = b"".join(decoded_chunks)
        self.content = body
        self._is_stream_consumed = True

        chunker = ByteChunker(chunk_size)
        yield from chunker.feed(body)
        remaining = chunker.flush()
        if remaining:
            yield remaining

    async def async_iter_bytes(
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

        if not isinstance(self.content, ABCAsyncIterator):
            raise AsyncSyncMismatchError(
                "The stream is not asynchronous, try using `iter_bytes` instead of `async_iter_bytes`."
            )

        decoder = self._get_content_decoder()
        decoded_chunks: list[bytes] = []

        async for raw_chunk in self.content:
            decoded_chunk = decoder.decode(raw_chunk)
            if decoded_chunk:
                decoded_chunks.append(decoded_chunk)

        final_decoded = decoder.flush()
        if final_decoded:
            decoded_chunks.append(final_decoded)

        body = b"".join(decoded_chunks)
        self.content = body
        self._is_stream_consumed = True

        chunker = ByteChunker(chunk_size)
        for chunk in chunker.feed(body):
            yield chunk
        remaining = chunker.flush()
        if remaining:
            yield remaining

    def iter_raw(
        self,
        chunk_size: int | None = None,
    ) -> Iterator[bytes]:
        if chunk_size is None:
            chunk_size = CHUNK_SIZE

        if isinstance(self.content, bytes):
            chunker = ByteChunker(chunk_size)
            yield from chunker.feed(self.content)
            remaining = chunker.flush()
            if remaining:
                yield remaining
            return

        if self.content is None:
            return

        if isinstance(self.content, ABCAsyncIterator):
            raise AsyncSyncMismatchError(
                "The stream is not synchronous, try using `async_iter_raw` instead of `iter_raw`."
            )

        chunker = ByteChunker(chunk_size)
        for raw_chunk in self.content:
            for chunk in chunker.feed(raw_chunk):
                yield chunk
        remaining = chunker.flush()
        if remaining:
            yield remaining
        self._is_stream_consumed = True

    async def async_iter_raw(
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

        if not isinstance(self.content, ABCAsyncIterator):
            raise AsyncSyncMismatchError(
                "The stream is not asynchronous, try using `iter_raw` instead of `async_iter_raw`."
            )

        chunker = ByteChunker(chunk_size)
        async for raw_chunk in self.content:
            for chunk in chunker.feed(raw_chunk):
                yield chunk
        remaining = chunker.flush()
        if remaining:
            yield remaining
        self._is_stream_consumed = True

    def read(self) -> bytes:
        if not isinstance(self.content, bytes):
            for _ in self.iter_bytes():
                ...
        return self.content  # type: ignore[return-value]

    async def aread(self) -> bytes:
        if not isinstance(self.content, bytes):
            async for _ in self.async_iter_bytes():
                pass
        return self.content  # type: ignore[return-value]

    def close(self) -> None:
        if self.content is None or self._is_stream_consumed:
            return

        if isinstance(self.content, bytes):
            return

        if isinstance(self.content, ABCAsyncIterator):
            raise AsyncSyncMismatchError("The stream is not synchronous, use `aclose()` instead.")

        if isinstance(self.content, ClosableStream):
            self.content.close()
            self._is_stream_consumed = True

    async def aclose(self) -> None:
        if self.content is None or self._is_stream_consumed:
            return

        if isinstance(self.content, bytes):
            return

        if not isinstance(self.content, ABCAsyncIterator):
            raise AsyncSyncMismatchError("The stream is not asynchronous, try using `close()` instead of `aclose()`.")

        if isinstance(self.content, AsyncClosableStream):
            await self.content.aclose()
            self._is_stream_consumed = True

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
