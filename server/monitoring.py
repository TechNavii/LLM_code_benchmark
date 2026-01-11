"""Monitoring helpers for structured logging and timing."""

from __future__ import annotations

import inspect
import time
from functools import wraps
from typing import Any, TypeVar
from collections.abc import Awaitable, Callable, Coroutine

import structlog


FuncType = TypeVar("FuncType", bound=Callable[..., Awaitable[Any]])


def timed(func: FuncType) -> FuncType:
    @wraps(func)
    async def wrapper(*args, **kwargs):
        logger = structlog.get_logger(func.__module__)
        started = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration = time.perf_counter() - started
            logger.info("function.complete", function=func.__name__, duration_seconds=duration)
            return result
        except Exception as exc:
            duration = time.perf_counter() - started
            logger.exception(
                "function.error",
                function=func.__name__,
                duration_seconds=duration,
                error=str(exc),
            )
            raise

    wrapper.__signature__ = inspect.signature(func)  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
