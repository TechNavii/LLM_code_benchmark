"""Dedicated progress manager for the expert question benchmark."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any, Dict


class ProgressManager:
    def __init__(self) -> None:
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def generate_run_id(self) -> str:
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("qa_%Y%m%dT%H%M%SZ")
        return f"{timestamp}_{uuid.uuid4().hex[:6]}"

    async def start_run(self, run_id: str, metadata: Dict[str, Any]) -> None:
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

    def _publish(self, run_id: str, event: Dict[str, Any]) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run["events"].append(event)
        for queue in list(run["queues"]):
            queue.put_nowait(event)

    def publish_attempt(self, run_id: str, event: Dict[str, Any]) -> None:
        payload = {"type": "attempt", **event}
        self._publish(run_id, payload)

    def complete(self, run_id: str, summary: Dict[str, Any]) -> None:
        self._publish(run_id, {"type": "complete", "summary": summary})
        run = self._runs.get(run_id)
        if run:
            run["done"] = True

    def fail(self, run_id: str, message: str) -> None:
        self._publish(run_id, {"type": "error", "message": message})
        run = self._runs.get(run_id)
        if run:
            run["done"] = True


qa_progress_manager = ProgressManager()

__all__ = ["qa_progress_manager", "ProgressManager"]
