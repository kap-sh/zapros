from abc import abstractmethod

from zapros._async_pool import AsyncConnPool
from zapros._base_pool import AsyncPoolConnection, PoolConnection
from zapros._models import Request, Response
from zapros._sync_pool import ConnPool


class BrokenConnectionError(ConnectionError):
    """
    Raised when a connection from the pool which was expected to be alive is
    found to be closed or otherwise unusable. This can happen when the server
    closes an idle connection, and the client tries to reuse it from the pool.
    When this happens, the connection should not be returned to the pool, and
    the request should be retried with a new connection.
    This should be raised by the connection's send_request() when the first operation on the connection fails.
    """

    pass


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
