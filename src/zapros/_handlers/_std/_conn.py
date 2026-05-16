from abc import abstractmethod

from zapros._async_pool import AsyncConnPool
from zapros._base_pool import AsyncPoolConnection, PoolConnection
from zapros._models import Request, Response
from zapros._sync_pool import ConnPool


class AsyncHttpConnection(AsyncPoolConnection):
    @abstractmethod
    async def send_request(
        self,
        request: Request,
        *,
        conn_pool: AsyncConnPool,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        deadline: float | None = None,
    ) -> Response:
        raise NotImplementedError()


class HttpConnection(PoolConnection):
    @abstractmethod
    def send_request(
        self,
        request: Request,
        *,
        conn_pool: ConnPool,
        read_timeout: float | None,
        write_timeout: float | None,
        deadline: float | None,
    ) -> Response:
        raise NotImplementedError()
