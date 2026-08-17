"""The TTL cache: expiry, single-flight de-duplication, and what is not cached."""

from __future__ import annotations

import asyncio

import pytest

from merlin_mcp.cache import TTLCache


async def test_value_is_reused_within_its_lifetime() -> None:
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = TTLCache(default_ttl=60.0)
    assert await cache.get_or_set("k", factory) == 1
    assert await cache.get_or_set("k", factory) == 1
    assert calls == 1


async def test_value_is_recomputed_once_it_expires() -> None:
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = TTLCache(default_ttl=0.0)
    assert await cache.get_or_set("k", factory) == 1
    assert await cache.get_or_set("k", factory) == 2
    assert calls == 2


async def test_concurrent_callers_share_one_computation() -> None:
    """Single-flight is the reason this exists rather than a plain dict."""
    calls = 0

    async def slow() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "value"

    cache = TTLCache(default_ttl=60.0)
    results = await asyncio.gather(*(cache.get_or_set("k", slow) for _ in range(5)))

    assert results == ["value"] * 5
    assert calls == 1


async def test_a_raised_error_is_not_cached() -> None:
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("upstream down")
        return "recovered"

    cache = TTLCache(default_ttl=60.0)
    with pytest.raises(RuntimeError):
        await cache.get_or_set("k", flaky)
    assert await cache.get_or_set("k", flaky) == "recovered"


async def test_ttl_for_gives_a_value_its_own_lifetime() -> None:
    calls = 0

    async def factory() -> str | None:
        nonlocal calls
        calls += 1
        return None

    cache = TTLCache(default_ttl=3600.0)
    # A "not found" result is remembered only briefly, so a transient 404 does not
    # stick around for the whole index lifetime.
    await cache.get_or_set("k", factory, ttl=3600.0, ttl_for=lambda value: 0.0)
    await cache.get_or_set("k", factory, ttl=3600.0, ttl_for=lambda value: 0.0)
    assert calls == 2


async def test_lock_table_does_not_grow_without_bound() -> None:
    cache = TTLCache(default_ttl=0.0)

    async def factory() -> int:
        return 1

    for index in range(200):
        await cache.get_or_set(f"key-{index}", factory)

    # Locks are held weakly, so finished ones are collectable rather than retained
    # one per URL for the life of the process.
    assert len(cache._locks) < 200


async def test_clear_empties_the_cache() -> None:
    cache = TTLCache(default_ttl=60.0)

    async def factory() -> int:
        return 7

    await cache.get_or_set("k", factory)
    assert len(cache) == 1
    cache.clear()
    assert len(cache) == 0
