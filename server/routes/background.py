"""Shared helpers for running benchmark work in background tasks."""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar
from collections.abc import Callable


T = TypeVar("T")


async def run_in_thread_with_callbacks(
    func: Callable[..., T],
    *args: Any,
    on_success: Callable[[T], None],
    on_error: Callable[[Exception], None],
    **kwargs: Any,
) -> None:
    """Run a blocking function in a worker thread and invoke callbacks.

    This helper centralizes error handling for FastAPI background tasks so we
    consistently report failures to clients via progress streams.
    """

    try:
        result = await asyncio.to_thread(func, *args, **kwargs)
        on_success(result)
    except Exception as exc:  # pragma: no cover - defensive guard for background tasks
        on_error(exc)


__all__ = ["run_in_thread_with_callbacks"]
