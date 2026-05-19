from abc import abstractmethod

from typing_extensions import Literal, Protocol, runtime_checkable


@runtime_checkable
class BaseNetworkStream(Protocol):
    @abstractmethod
    def read(self, max_bytes: int, timeout: float | None = None) -> bytes: ...
    @abstractmethod
    def write_all(self, data: bytes, timeout: float | None = None) -> int: ...
    def close(self) -> None: ...
    def start_tls(
        self,
        *,
        server_hostname: str | None = None,
    ) -> "BaseNetworkStream":
        return self

    def selected_alpn_protocol(self) -> Literal["http/1.1", "h2"] | None:
        return None


@runtime_checkable
class AsyncBaseNetworkStream(Protocol):
    @abstractmethod
    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes: ...
    @abstractmethod
    async def write_all(self, data: bytes, timeout: float | None = None) -> int: ...
    async def start_tls(
        self,
        *,
        server_hostname: str | None = None,
    ) -> "AsyncBaseNetworkStream":
        return self

    async def close(self) -> None: ...
    def selected_alpn_protocol(self) -> Literal["http/1.1", "h2"] | None:
        return None


class BaseTransport(Protocol):
    def connect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        alpn_protocols: list[Literal["http/1.1", "h2"]] | None = None,
        timeout: float | None = None,
    ) -> BaseNetworkStream: ...


class AsyncBaseTransport(Protocol):
    async def aconnect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
        alpn_protocols: list[Literal["http/1.1", "h2"]] | None = None,
        timeout: float | None = None,
    ) -> AsyncBaseNetworkStream: ...
