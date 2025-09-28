"""Cache utilities for the server layer."""

from __future__ import annotations

from server.infrastructure.caching import AsyncCache


cache = AsyncCache()

__all__ = ["cache", "AsyncCache"]