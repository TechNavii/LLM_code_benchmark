"""Async resource cache with intentionally naive implementation."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict


class AsyncResourceCache:
    """Cache that stores async loader results by key."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._store: Dict[str, Any] = {}

    async def get(self, key: str, loader: Callable[[], Awaitable[Any]]) -> Any:
        if key in self._store:
            return self._store[key]
        value = await loader()
        self._store[key] = value
        return value

    def invalidate(self, key: str) -> None:
        if key in self._store:
            del self._store[key]

    async def close(self) -> None:
        self._store.clear()
