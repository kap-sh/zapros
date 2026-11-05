import gzip
import time

import sqlite3
import pytest
from hishel import (
    SqliteStorage,
    CacheOptions,
)
from pywhatwgurl import URL

from zapros import Client
from zapros._handlers._caching import (
    CacheMiddleware,
)
from zapros._handlers._mock import (
    Mock as ZaprosMock,
    MockMiddleware,
    MockRouter,
)
from zapros._models import ClosableStream, Request, Response
from zapros.matchers import header

# the async sqlite storage needs worker threads
pytestmark = pytest.mark.no_pyodide


class TrackingStream(ClosableStream):
    def __init__(self) -> None:
        self.closed = False

    def __next__(self) -> bytes:
        raise StopIteration

    def close(self) -> None:
        self.closed = True


class TrackingStorage(SqliteStorage):
    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def test_cache_miss_then_hit():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).expect(1).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is True

        router.verify()


def test_cache_context_fields():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
            content=b"hello",
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.read() == b"hello"
        assert response1.context.get("caching") == {
            "from_cache": False,
            "revalidated": False,
            "stored": True,
        }

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.read() == b"hello"
        assert response2.context.get("caching") == {
            "from_cache": True,
            "revalidated": False,
            "stored": False,
        }


def test_default_mode_ignores_cache_headers():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "no-store"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.context.get("caching", {}).get("from_cache") is False

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.context.get("caching", {}).get("from_cache") is True

        router.verify()


def test_default_mode_does_not_store_errors():
    router = MockRouter()
    ZaprosMock().respond(Response(status=404)).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.status == 404
        assert response1.context.get("caching", {}).get("stored") is False

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.status == 404
        assert response2.context.get("caching", {}).get("from_cache") is False

        router.verify()


def test_rfc_respects_no_cache_directive():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "no-cache"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage, rfc=True)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.status == 200

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.status == 200

        router.verify()


def test_rfc_with_cache_options():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    in_memory_storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(
        handler,
        storage=in_memory_storage,
        rfc=CacheOptions(shared=False),
    )

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is True

        router.verify()


def test_rfc_revalidation():
    router = MockRouter()
    not_modified = (
        ZaprosMock.given(header("If-None-Match", '"v1"'))
        .respond(Response(status=304, headers={"ETag": '"v1"'}))
        .once()
        .mount(router)
    )
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "no-cache", "ETag": '"v1"'},
            content=b"hello",
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage, rfc=True)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.read() == b"hello"
        assert response1.context.get("caching", {}).get("stored") is True

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.status == 200
        assert response2.read() == b"hello"
        assert response2.context.get("caching") == {
            "from_cache": True,
            "revalidated": True,
            "stored": False,
        }

        router.verify()
        # The revalidation header is only added for the request that is sent.
        assert response2.request is not None
        assert "If-None-Match" not in response2.request.headers
        assert not_modified.call_count == 1


def test_cache_ttl_in_context():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200)).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
            context={"caching": {"ttl": 0.1}},
        )
        response1.read()
        assert response1.context.get("caching", {}).get("stored") is True

        time.sleep(0.2)

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.context.get("caching", {}).get("from_cache") is False

        router.verify()


def test_cache_custom_key():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200, content=b"shared")).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/path1",
            context={"caching": {"key": "custom_key"}},
        )
        assert response1.read() == b"shared"

        response2 = client.get(
            "https://example.com/path2",
            context={"caching": {"key": "custom_key"}},
        )
        assert response2.read() == b"shared"
        assert response2.context.get("caching", {}).get("from_cache") is True

        router.verify()


def test_different_urls_not_cached_together():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/path1",
        )
        assert response1.status == 200

        response2 = client.get(
            "https://example.com/path2",
        )
        assert response2.status == 200

        router.verify()


def test_post_is_not_cached():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        for _ in range(2):
            response = client.post(
                "https://example.com/",
                json={"query": "search"},
            )
            assert response.status == 200
            assert response.context.get("caching") == {
                "from_cache": False,
                "revalidated": False,
                "stored": False,
            }

        router.verify()


def test_already_read_encoded_response():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Content-Encoding": "gzip"},
            content=gzip.compress(b"hello"),
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
        )
        assert response1.read() == b"hello"

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.context.get("caching", {}).get("from_cache") is True
        # The stored body is already decoded, so it must not claim an encoding.
        assert "Content-Encoding" not in response2.headers
        assert response2.headers["Content-Length"] == "5"
        assert response2.read() == b"hello"

        router.verify()


def test_closing_response_closes_upstream():
    router = MockRouter()
    upstream_stream = TrackingStream()
    ZaprosMock().respond(Response(status=200, content=upstream_stream)).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    response = caching_handler.handle(Request(URL("https://example.com/"), "GET"))
    assert response.context.get("caching", {}).get("stored") is True
    response.close()

    assert upstream_stream.closed


def test_upstream_context_is_kept():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            context={"network": {"http_protocol": "HTTP/2"}},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response = client.get(
            "https://example.com/",
        )
        assert response.context.get("network") == {"http_protocol": "HTTP/2"}
        assert response.context.get("caching", {}).get("stored") is True


def test_per_request_rfc_override():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "no-store"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        for _ in range(2):
            response = client.get(
                "https://example.com/",
                context={"caching": {"rfc": True}},
            )
            assert response.context.get("caching", {}).get("stored") is False

        router.verify()


def test_per_request_storage_override():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200)).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    other_storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
            context={"caching": {"storage": other_storage}},
        )
        response1.read()

        response2 = client.get(
            "https://example.com/",
        )
        assert response2.context.get("caching", {}).get("from_cache") is False

        response3 = client.get(
            "https://example.com/",
            context={"caching": {"storage": other_storage}},
        )
        assert response3.context.get("caching", {}).get("from_cache") is True

        router.verify()


def test_closing_client_closes_storage():
    router = MockRouter()
    handler = MockMiddleware(router)
    storage = TrackingStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))

    with Client(handler=CacheMiddleware(handler, storage=storage)):
        pass

    assert storage.closed


def test_force_caches_post_with_key():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200, content=b"result")).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        response1 = client.post(
            "https://example.com/graphql",
            json={"query": "{ user }"},
            context={"caching": {"force": True, "key": "user"}},
        )
        assert response1.read() == b"result"
        assert response1.context.get("caching", {}).get("stored") is True

        response2 = client.post(
            "https://example.com/graphql",
            json={"query": "{ user }"},
            context={"caching": {"force": True, "key": "user"}},
        )
        assert response2.read() == b"result"
        assert response2.context.get("caching", {}).get("from_cache") is True

        router.verify()


def test_key_alone_does_not_cache_post():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200)).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        for _ in range(2):
            response = client.post(
                "https://example.com/graphql",
                json={"query": "{ user }"},
                context={"caching": {"key": "user"}},
            )
            assert response.context.get("caching", {}).get("stored") is False

        router.verify()


def test_force_post_requires_key():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200)).never().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage)

    with Client(handler=caching_handler) as client:
        with pytest.raises(ValueError, match="requires an explicit `key`"):
            client.post(
                "https://example.com/graphql",
                json={"query": "{ user }"},
                context={"caching": {"force": True}},
            )


def test_force_ignores_rfc():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "no-store"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = SqliteStorage(connection=sqlite3.connect(":memory:", check_same_thread=False))
    caching_handler = CacheMiddleware(handler, storage=storage, rfc=True)

    with Client(handler=caching_handler) as client:
        response1 = client.get(
            "https://example.com/",
            context={"caching": {"force": True}},
        )
        response1.read()
        assert response1.context.get("caching", {}).get("stored") is True

        response2 = client.get(
            "https://example.com/",
            context={"caching": {"force": True}},
        )
        assert response2.context.get("caching", {}).get("from_cache") is True
        router.verify()
