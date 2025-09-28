"""Monitoring helpers for structured logging and timing."""

from __future__ import annotations

import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Awaitable, Callable, Coroutine, TypeVar

import structlog


correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


FuncType = TypeVar("FuncType", bound=Callable[..., Awaitable[Any]])


def with_correlation_id(func: FuncType) -> FuncType:
    @wraps(func)
    async def wrapper(*args, **kwargs):
        token = correlation_id.set(str(time.time_ns()))
        try:
            return await func(*args, **kwargs)
        finally:
            correlation_id.reset(token)

    return wrapper  # type: ignore[return-value]


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

    return wrapper  # type: ignore[return-value]
