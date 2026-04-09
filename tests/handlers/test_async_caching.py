import time

import anysqlite
import pytest
from hishel import (
    AsyncSqliteStorage,
    FilterPolicy,
    SpecificationPolicy,
)

from zapros import AsyncClient
from zapros._handlers._caching import (
    CacheMiddleware,
)
from zapros._handlers._mock import (
    Mock as ZaprosMock,
    MockMiddleware,
    MockRouter,
)
from zapros._models import Response


@pytest.mark.asyncio
async def test_cache_miss_then_hit():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).expect(1).mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(handler, storage=storage)

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/",
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        response2 = await client.get(
            "https://example.com/",
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is True

        router.verify()


@pytest.mark.asyncio
async def test_cache_context_fields():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(handler, storage=storage)

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/",
        )
        caching1 = response1.context.get("caching", {})

        assert caching1.get("from_cache") is False
        assert "created_at" in caching1
        assert isinstance(
            caching1.get("created_at"),
            float,
        )

        response2 = await client.get(
            "https://example.com/",
        )
        caching2 = response2.context.get("caching", {})

        assert caching2.get("from_cache") is True
        assert "created_at" in caching2


@pytest.mark.asyncio
async def test_cache_respects_no_cache_directive():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "no-cache"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(handler, storage=storage)

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/",
        )
        assert response1.status == 200

        response2 = await client.get(
            "https://example.com/",
        )
        assert response2.status == 200

        router.verify()


@pytest.mark.xfail(reason="investigate hishel's ttl handling")
@pytest.mark.asyncio
async def test_cache_ttl_in_context():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(handler, storage=storage)

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/",
            context={
                "caching": {
                    "ttl": 2,
                }
            },
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        time.sleep(1.1)

        ZaprosMock().respond(
            Response(
                status=200,
                headers={"Cache-Control": "max-age=3600"},
            )
        ).once().mount(router)

        response2 = await client.get(
            "https://example.com/",
            context={
                "caching": {
                    "ttl": 1.0,
                }
            },
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is False


@pytest.mark.asyncio
async def test_cache_body_key():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(handler, storage=storage)

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.post(
            "https://example.com/",
            body=b"body1",
            context={"caching": {"body_key": "key1"}},
        )
        assert response1.status == 200

        response2 = await client.post(
            "https://example.com/",
            body=b"body2",
            context={"caching": {"body_key": "key2"}},
        )
        assert response2.status == 200

        router.verify()


@pytest.mark.asyncio
async def test_specification_policy():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    in_memory_storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    policy = SpecificationPolicy()
    caching_handler = CacheMiddleware(
        handler,
        storage=in_memory_storage,
        policy=policy,
    )

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/",
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        response2 = await client.get(
            "https://example.com/",
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is True

        router.verify()


@pytest.mark.asyncio
async def test_filter_policy():
    router = MockRouter()
    ZaprosMock().respond(Response(status=200, headers={})).expect(1).mount(router)

    handler = MockMiddleware(router)
    in_memory_storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    policy = FilterPolicy()
    caching_handler = CacheMiddleware(
        handler,
        storage=in_memory_storage,
        policy=policy,
    )

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/",
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        response2 = await client.get(
            "https://example.com/",
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is True

        router.verify()


@pytest.mark.asyncio
async def test_different_urls_not_cached_together():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).expect(2).mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(handler, storage=storage)

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.get(
            "https://example.com/path1",
        )
        assert response1.status == 200

        response2 = await client.get(
            "https://example.com/path2",
        )
        assert response2.status == 200

        router.verify()


@pytest.mark.asyncio
async def test_cache_post_request_with_body_key():
    router = MockRouter()
    ZaprosMock().respond(
        Response(
            status=200,
            headers={"Cache-Control": "max-age=3600"},
        )
    ).once().mount(router)

    handler = MockMiddleware(router)
    storage = AsyncSqliteStorage(connection=await anysqlite.connect(":memory:"))
    caching_handler = CacheMiddleware(
        handler,
        storage=storage,
        policy=FilterPolicy(),
    )

    async with AsyncClient(handler=caching_handler) as client:
        response1 = await client.post(
            "https://example.com/",
            json={"query": "search"},
            context={"caching": {"body_key": "custom_key"}},
        )
        assert response1.status == 200
        caching1 = response1.context.get("caching", {})
        assert caching1.get("from_cache") is False

        response2 = await client.post(
            "https://example.com/",
            json={"query": "search"},
            context={"caching": {"body_key": "custom_key"}},
        )
        assert response2.status == 200
        caching2 = response2.context.get("caching", {})
        assert caching2.get("from_cache") is True

        router.verify()
