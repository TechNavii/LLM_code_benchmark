"""Shared base class for progress managers."""

from __future__ import annotations

import asyncio
import datetime as dt
import threading
import uuid
from typing import Any
from collections.abc import Coroutine


class BaseProgressManager:
    """Thread-safe progress manager that dispatches events onto the asyncio event loop.

    Subclasses should override `_id_prefix` to customize run ID generation.
    """

    _id_prefix: str = "run"

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        with self._loop_lock:
            if self._loop is None:
                self._loop = loop

    def _dispatch(self, coro: asyncio.Future[Any] | Coroutine[Any, Any, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            # Close the coroutine to avoid "coroutine was never awaited" warning
            if hasattr(coro, "close"):
                coro.close()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            asyncio.create_task(coro)
            return
        asyncio.run_coroutine_threadsafe(coro, loop)

    def generate_run_id(self) -> str:
        timestamp = dt.datetime.now(dt.UTC).strftime(f"{self._id_prefix}_%Y%m%dT%H%M%SZ")
        return f"{timestamp}_{uuid.uuid4().hex[:6]}"

    async def start_run(self, run_id: str, metadata: dict[str, Any]) -> None:
        self._ensure_loop()
        async with self._lock:
            self._runs[run_id] = {
                "queues": [],
                "events": [
                    {
                        "type": "init",
                        "run_id": run_id,
                        "metadata": metadata,
                    }
                ],
                "done": False,
            }

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        self._ensure_loop()
        async with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            queue: asyncio.Queue = asyncio.Queue()
            for event in self._runs[run_id]["events"]:
                queue.put_nowait(event)
            self._runs[run_id]["queues"].append(queue)
            return queue

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            if queue in run["queues"]:
                run["queues"].remove(queue)
            if run["done"] and not run["queues"]:
                del self._runs[run_id]

    async def _append_event(self, run_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            run["events"].append(event)
            for queue in list(run["queues"]):
                queue.put_nowait(event)
            if event.get("type") in {"complete", "error"}:
                run["done"] = True

    def publish_attempt(self, run_id: str, event: dict[str, Any]) -> None:
        payload = {"type": "attempt", **event}
        self._dispatch(self._append_event(run_id, payload))

    def complete(self, run_id: str, summary: dict[str, Any]) -> None:
        self._dispatch(self._append_event(run_id, {"type": "complete", "summary": summary}))

    def fail(self, run_id: str, message: str) -> None:
        self._dispatch(self._append_event(run_id, {"type": "error", "message": message}))


__all__ = ["BaseProgressManager"]
