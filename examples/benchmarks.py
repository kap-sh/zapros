# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "aiohttp>=3.9",
#     "zapros",
# ]
#
# [tool.uv.sources]
# zapros = { path = "../", editable = true }
# ///

import asyncio
import time

import aiohttp

import zapros
from zapros._handlers._async_std import AsyncStdNetworkHandler

URL = "https://httpbin.org/get"
N = 100


async def bench_aiohttp_sequential():
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit_per_host=100)) as session:
        for _ in range(N):
            async with session.get(URL) as resp:
                await resp.read()


async def bench_aiohttp_concurrent():
    async def fetch(session):
        async with session.get(URL) as resp:
            await resp.read()

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit_per_host=100)) as session:
        await asyncio.gather(*[fetch(session) for _ in range(N)])


async def bench_zapros_sequential():
    async with zapros.AsyncClient(
        AsyncStdNetworkHandler(max_connections_per_host=100, max_idle_connections_per_host=100)
    ) as client:
        for _ in range(N):
            await client.get(URL)


async def bench_zapros_concurrent():
    async def fetch(client):
        async with client.stream("GET", URL) as resp:
            await resp.aread()

    async with zapros.AsyncClient(
        AsyncStdNetworkHandler(max_connections_per_host=100, max_idle_connections_per_host=100)
    ) as client:
        await asyncio.gather(*[fetch(client) for _ in range(N)])


async def timed(label, coro):
    start = time.perf_counter()
    await coro
    elapsed = time.perf_counter() - start
    print(f"  {label:<10} {elapsed:.3f}s total  |  {elapsed / N * 1000:.1f}ms/req")


async def main():
    print(f"\nConcurrent ({N} requests)")
    await timed("aiohttp", bench_aiohttp_concurrent())
    await timed("zapros", bench_zapros_concurrent())

    print(f"Sequential ({N} requests)")
    await timed("aiohttp", bench_aiohttp_sequential())
    await timed("zapros", bench_zapros_sequential())


asyncio.run(main())
