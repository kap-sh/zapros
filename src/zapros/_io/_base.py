from abc import abstractmethod

from typing_extensions import Protocol, runtime_checkable


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


class BaseTransport(Protocol):
    def connect(
        self,
        host: str,
        port: int,
        server_hostname: str | None = None,
        tls: bool = False,
        *,
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
        timeout: float | None = None,
    ) -> AsyncBaseNetworkStream: ...
