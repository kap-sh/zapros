import pytest

from zapros import AsyncBaseHandler, AsyncClient, BaseHandler, Client, Request, Response


class Recorder(BaseHandler):
    def __init__(self) -> None:
        self.urls: list[str] = []

    def handle(self, request: Request) -> Response:
        self.urls.append(str(request.url))
        return Response(status=200)


class AsyncRecorder(AsyncBaseHandler):
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def ahandle(self, request: Request) -> Response:
        self.urls.append(str(request.url))
        return Response(status=200)


CASES = [
    pytest.param(
        "https://zapros.dev/inbox?from=login&from=octavius&from=octavius",
        None,
        {},
        "https://zapros.dev/inbox?from=login&from=octavius&from=octavius",
        id="repeated-name-in-the-url-is-kept",
    ),
    pytest.param(
        "https://zapros.dev/items",
        [("tag", "a"), ("tag", "b")],
        {},
        "https://zapros.dev/items?tag=a&tag=b",
        id="repeated-name-in-params-is-kept",
    ),
    pytest.param(
        "https://zapros.dev/items",
        {"tag": ["a", "b"]},
        {},
        "https://zapros.dev/items?tag=a&tag=b",
        id="sequence-value-in-params-is-kept",
    ),
    pytest.param(
        "https://zapros.dev/items?tag=a&tag=b&page=1",
        {"tag": "c"},
        {},
        "https://zapros.dev/items?page=1&tag=c",
        id="params-replace-every-value-of-a-name-in-the-url",
    ),
    pytest.param(
        "https://zapros.dev/items?page=2",
        None,
        {"page": "1", "lang": "en"},
        "https://zapros.dev/items?lang=en&page=2",
        id="url-replaces-a-default-param",
    ),
    pytest.param(
        "https://zapros.dev/items?a=1",
        {"b": "2"},
        {"c": "3"},
        "https://zapros.dev/items?c=3&a=1&b=2",
        id="distinct-names-from-all-three-sources",
    ),
]


@pytest.mark.parametrize("url,params,default_params,expected", CASES)
def test_sync_client_keeps_repeated_query_names(url, params, default_params, expected):
    recorder = Recorder()
    with Client(handler=recorder, default_params=default_params) as client:
        client.get(url, params=params)
    assert recorder.urls == [expected]


@pytest.mark.parametrize("url,params,default_params,expected", CASES)
async def test_async_client_keeps_repeated_query_names(url, params, default_params, expected):
    recorder = AsyncRecorder()
    async with AsyncClient(handler=recorder, default_params=default_params) as client:
        await client.get(url, params=params)
    assert recorder.urls == [expected]
