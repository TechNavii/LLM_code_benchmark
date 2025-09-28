"""In-memory async cache utilities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class AsyncCache:
    def __init__(self) -> None:
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired():
                return entry.value
            if entry:
                del self._cache[key]
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        async with self._lock:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)
