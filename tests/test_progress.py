from __future__ import annotations

import asyncio
import threading

from server.progress import ProgressManager as CodeProgressManager
from server.qa_progress import ProgressManager as QAProgressManager


def test_progress_manager_is_thread_safe() -> None:
    async def run() -> None:
        pm = CodeProgressManager()
        run_id = "run_test"
        await pm.start_run(run_id, {"kind": "code"})
        queue = await pm.subscribe(run_id)

        init_event = await asyncio.wait_for(queue.get(), timeout=1)
        assert init_event["type"] == "init"

        errors: list[BaseException] = []

        def publish() -> None:
            try:
                pm.publish_attempt(run_id, {"task_id": "t", "model": "m"})
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        thread = threading.Thread(target=publish)
        thread.start()
        thread.join(timeout=2)
        assert not errors

        attempt_event = await asyncio.wait_for(queue.get(), timeout=1)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["task_id"] == "t"

        def complete() -> None:
            pm.complete(run_id, {"ok": True})

        thread = threading.Thread(target=complete)
        thread.start()
        thread.join(timeout=2)

        complete_event = await asyncio.wait_for(queue.get(), timeout=1)
        assert complete_event["type"] == "complete"

        await pm.unsubscribe(run_id, queue)
        assert run_id not in pm._runs

    asyncio.run(run())


def test_qa_progress_manager_is_thread_safe() -> None:
    async def run() -> None:
        pm = QAProgressManager()
        run_id = "qa_test"
        await pm.start_run(run_id, {"kind": "qa"})
        queue = await pm.subscribe(run_id)

        init_event = await asyncio.wait_for(queue.get(), timeout=1)
        assert init_event["type"] == "init"

        def publish() -> None:
            pm.publish_attempt(run_id, {"question_number": 1, "model": "m"})

        thread = threading.Thread(target=publish)
        thread.start()
        thread.join(timeout=2)

        attempt_event = await asyncio.wait_for(queue.get(), timeout=1)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["question_number"] == 1

        def fail() -> None:
            pm.fail(run_id, "boom")

        thread = threading.Thread(target=fail)
        thread.start()
        thread.join(timeout=2)

        error_event = await asyncio.wait_for(queue.get(), timeout=1)
        assert error_event["type"] == "error"
        assert error_event["message"] == "boom"

        await pm.unsubscribe(run_id, queue)
        assert run_id not in pm._runs

    asyncio.run(run())
