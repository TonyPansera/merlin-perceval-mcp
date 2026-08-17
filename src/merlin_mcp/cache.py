"""In-memory TTL cache with single-flight de-duplication.

This is deliberately the only caching layer in the server: values live in the
process heap and disappear with it. Nothing is written to disk, so the server has
no state to migrate, invalidate or maintain, and it always converges on whatever
upstream currently publishes once entries expire.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

T = TypeVar("T")


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    """Async cache mapping a string key to a value for a bounded time."""

    def __init__(self, default_ttl: float = 3600.0) -> None:
        self.default_ttl = default_ttl
        self._entries: dict[str, _Entry] = {}
        # Weak values so a lock disappears once nothing is waiting on it. A strong
        # dict here would grow by one lock per distinct URL for the life of the
        # process, which for a long-running server is an unbounded leak.
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._guard = asyncio.Lock()

    def _live(self, key: str) -> _Entry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._entries.pop(key, None)
            return None
        return entry

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
        ttl: float | None = None,
        ttl_for: Callable[[T], float] | None = None,
    ) -> T:
        """Return the cached value for ``key``, computing it with ``factory`` if absent.

        Concurrent callers for the same key wait on one another rather than issuing
        duplicate upstream requests. A raised exception is never cached, so a failure
        is retried on the next call rather than being served for the whole lifetime.

        Args:
            key: cache key.
            factory: coroutine producing the value when it is not cached.
            ttl: lifetime in seconds; defaults to the cache's default.
            ttl_for: optional per-value lifetime, allowing a "not found" result to be
                remembered for less time than a real one.
        """
        entry = self._live(key)
        if entry is not None:
            return cast(T, entry.value)

        # Hold a strong reference for as long as the lock is needed: the lock map
        # holds only weak references, so this local name is what keeps it alive.
        lock = await self._lock_for(key)
        async with lock:
            entry = self._live(key)
            if entry is not None:
                return cast(T, entry.value)
            value = await factory()
            lifetime = self.default_ttl if ttl is None else ttl
            if ttl_for is not None:
                lifetime = ttl_for(value)
            self._entries[key] = _Entry(value, time.monotonic() + lifetime)
            return value

    def clear(self) -> None:
        """Drop every cached value."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


cache = TTLCache()
