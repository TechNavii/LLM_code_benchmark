import asyncio
import time

import pytest

from cache import AsyncResourceCache


@pytest.mark.asyncio
async def test_loader_called_once_for_concurrent_requests():
    cache = AsyncResourceCache(ttl_seconds=5)
    call_count = 0

    async def loader():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(*(cache.get("a", loader) for _ in range(10)))
    assert results == ["result"] * 10
    assert call_count == 1, "Loader should have been coalesced across concurrent callers"


@pytest.mark.asyncio
async def test_ttl_expiration():
    cache = AsyncResourceCache(ttl_seconds=0.1)
    values = [0]

    async def loader():
        values[0] += 1
        return values[0]

    await cache.get("key", loader)
    await asyncio.sleep(0.15)
    result = await cache.get("key", loader)
    assert result == 2, "Value should refresh after TTL"


@pytest.mark.asyncio
async def test_invalidate_evicts_entry():
    cache = AsyncResourceCache(ttl_seconds=10)

    async def loader():
        return time.monotonic()

    value1 = await cache.get("k", loader)
    cache.invalidate("k")
    value2 = await cache.get("k", loader)
    assert value2 != value1


@pytest.mark.asyncio
async def test_close_prevents_inflight_tasks():
    cache = AsyncResourceCache(ttl_seconds=10)

    block = asyncio.Event()
    start = asyncio.Event()

    async def loader():
        start.set()
        await block.wait()
        return "done"

    task = asyncio.create_task(cache.get("key", loader))
    await start.wait()

    close_task = asyncio.create_task(cache.close())
    await asyncio.sleep(0)
    assert not close_task.done(), "close should wait for inflight tasks"

    block.set()
    await task
    await close_task
