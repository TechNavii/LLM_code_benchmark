"""Stress tests for progress managers: cleanup, ordering, memory growth, and thread-safety.

These tests verify that progress managers handle:
- Many subscribers with rapid churn (subscribe/unsubscribe)
- Many attempt events published in quick succession
- Correct event ordering under load
- Cleanup after unsubscribe/complete (no memory leak)
- Cross-thread publishing under load
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import threading
import time
import weakref
from typing import Any

import pytest

from server.progress import ProgressManager as CodeProgressManager
from server.qa_progress import ProgressManager as QAProgressManager


class TestManySubscribers:
    """Test creating many subscribers and publishing events to all of them."""

    @pytest.mark.asyncio
    async def test_many_subscribers_receive_all_events(self) -> None:
        """Create many subscribers and verify each receives all events in order."""
        pm = CodeProgressManager()
        run_id = "stress_many_subs"
        num_subscribers = 50
        num_events = 20

        await pm.start_run(run_id, {"kind": "stress"})

        # Create many subscribers
        queues: list[asyncio.Queue[dict[str, Any]]] = []
        for _ in range(num_subscribers):
            queue = await pm.subscribe(run_id)
            queues.append(queue)

        # Verify all subscribers got the init event
        for queue in queues:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert event["type"] == "init"

        # Publish many attempt events
        for i in range(num_events):
            pm.publish_attempt(run_id, {"task_id": f"task_{i}", "index": i})

        # Allow async dispatch to complete
        await asyncio.sleep(0.1)

        # Verify all subscribers received all events in correct order
        for queue in queues:
            for i in range(num_events):
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                assert event["type"] == "attempt"
                assert event["index"] == i, f"Expected index {i}, got {event['index']}"

        # Complete and unsubscribe all
        pm.complete(run_id, {"total": num_events})
        await asyncio.sleep(0.05)

        for queue in queues:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert event["type"] == "complete"
            await pm.unsubscribe(run_id, queue)

        # Verify cleanup
        assert run_id not in pm._runs

    @pytest.mark.asyncio
    async def test_subscriber_churn_during_publishing(self) -> None:
        """Rapidly add/remove subscribers while events are being published."""
        pm = CodeProgressManager()
        run_id = "stress_churn"
        num_events = 100

        await pm.start_run(run_id, {"kind": "churn"})

        # Keep one stable subscriber to verify all events
        stable_queue = await pm.subscribe(run_id)

        # Consume init event
        init = await asyncio.wait_for(stable_queue.get(), timeout=1.0)
        assert init["type"] == "init"

        # Churn subscribers while publishing
        async def churn_subscriber() -> None:
            for _ in range(5):
                q = await pm.subscribe(run_id)
                await asyncio.sleep(0.001)
                await pm.unsubscribe(run_id, q)

        # Start churning and publishing concurrently
        churn_tasks = [asyncio.create_task(churn_subscriber()) for _ in range(10)]

        for i in range(num_events):
            pm.publish_attempt(run_id, {"index": i})
            if i % 10 == 0:
                await asyncio.sleep(0)  # Yield to churn tasks

        await asyncio.gather(*churn_tasks)
        await asyncio.sleep(0.1)

        # Verify stable subscriber got all events in order
        received: list[int] = []
        while not stable_queue.empty():
            event = stable_queue.get_nowait()
            if event["type"] == "attempt":
                received.append(event["index"])

        assert received == list(range(num_events)), "Stable subscriber should receive all events in order"

        # Cleanup
        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, stable_queue)
        assert run_id not in pm._runs


class TestEventOrdering:
    """Test that events are delivered in the correct order."""

    @pytest.mark.asyncio
    async def test_strict_ordering_under_load(self) -> None:
        """Verify events are always delivered in publication order."""
        pm = CodeProgressManager()
        run_id = "stress_order"
        num_events = 500

        await pm.start_run(run_id, {"kind": "order"})
        queue = await pm.subscribe(run_id)

        # Consume init
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Publish many events quickly
        for i in range(num_events):
            pm.publish_attempt(run_id, {"seq": i})

        await asyncio.sleep(0.2)

        # Verify strict ordering
        for expected in range(num_events):
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert event["type"] == "attempt"
            assert event["seq"] == expected, f"Expected seq {expected}, got {event['seq']}"

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, queue)

    @pytest.mark.asyncio
    async def test_late_subscriber_gets_history(self) -> None:
        """Subscriber joining mid-run should receive all prior events."""
        pm = CodeProgressManager()
        run_id = "stress_late"
        num_events = 30

        await pm.start_run(run_id, {"kind": "late"})

        # Publish events before any subscriber
        for i in range(num_events):
            pm.publish_attempt(run_id, {"index": i})

        await asyncio.sleep(0.1)

        # Late subscriber joins
        queue = await pm.subscribe(run_id)

        # Should get init + all prior events
        init = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert init["type"] == "init"

        for i in range(num_events):
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert event["type"] == "attempt"
            assert event["index"] == i

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, queue)


class TestMemoryCleanup:
    """Test that run state is properly cleaned up to prevent memory leaks."""

    @pytest.mark.asyncio
    async def test_cleanup_after_complete_and_unsubscribe(self) -> None:
        """Verify run state is deleted after completion and last unsubscribe."""
        pm = CodeProgressManager()
        num_runs = 20

        for i in range(num_runs):
            run_id = f"cleanup_run_{i}"
            await pm.start_run(run_id, {"index": i})
            queue = await pm.subscribe(run_id)
            pm.publish_attempt(run_id, {"x": 1})
            await asyncio.sleep(0.01)
            pm.complete(run_id, {})
            await asyncio.sleep(0.01)
            await pm.unsubscribe(run_id, queue)
            assert run_id not in pm._runs, f"Run {run_id} should be cleaned up"

        # All runs should be cleaned
        assert len(pm._runs) == 0

    @pytest.mark.asyncio
    async def test_no_cleanup_with_active_subscribers(self) -> None:
        """Run state should persist while subscribers are connected."""
        pm = CodeProgressManager()
        run_id = "no_cleanup"

        await pm.start_run(run_id, {})
        q1 = await pm.subscribe(run_id)
        q2 = await pm.subscribe(run_id)

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)

        # Still active subscribers - should not cleanup
        await pm.unsubscribe(run_id, q1)
        assert run_id in pm._runs, "Run should persist with active subscriber"

        # Last subscriber unsubscribes
        await pm.unsubscribe(run_id, q2)
        assert run_id not in pm._runs, "Run should be cleaned after last unsubscribe"

    @pytest.mark.asyncio
    async def test_queue_garbage_collected_after_unsubscribe(self) -> None:
        """Queues should be garbage collected after unsubscribe."""
        pm = CodeProgressManager()
        run_id = "gc_test"

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)
        weak_queue = weakref.ref(queue)

        pm.publish_attempt(run_id, {"data": "test"})
        await asyncio.sleep(0.05)

        await pm.unsubscribe(run_id, queue)
        del queue
        gc.collect()

        # Queue should be garbage collected
        assert weak_queue() is None, "Queue should be garbage collected after unsubscribe"

        # Cleanup
        pm.complete(run_id, {})
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_many_runs_no_memory_growth(self) -> None:
        """Creating and completing many runs should not leak memory."""
        pm = CodeProgressManager()
        num_runs = 100

        initial_run_count = len(pm._runs)

        for i in range(num_runs):
            run_id = f"memory_test_{i}"
            await pm.start_run(run_id, {"i": i})
            queue = await pm.subscribe(run_id)

            # Publish a few events
            for j in range(5):
                pm.publish_attempt(run_id, {"j": j})

            await asyncio.sleep(0.01)
            pm.complete(run_id, {})
            await asyncio.sleep(0.01)
            await pm.unsubscribe(run_id, queue)

        # Should be back to initial count (0)
        assert len(pm._runs) == initial_run_count


class TestCrossThreadPublishing:
    """Test thread-safety of publishing from background threads."""

    @pytest.mark.asyncio
    async def test_concurrent_thread_publishing(self) -> None:
        """Multiple threads publishing simultaneously should not deadlock or lose events."""
        pm = CodeProgressManager()
        run_id = "thread_stress"
        num_threads = 10
        events_per_thread = 20

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)

        # Consume init
        await asyncio.wait_for(queue.get(), timeout=1.0)

        errors: list[BaseException] = []
        published_indices: list[int] = []
        lock = threading.Lock()

        def publish_from_thread(thread_idx: int) -> None:
            try:
                for i in range(events_per_thread):
                    event_idx = thread_idx * events_per_thread + i
                    pm.publish_attempt(run_id, {"thread": thread_idx, "idx": event_idx})
                    with lock:
                        published_indices.append(event_idx)
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        # Start threads
        threads = [threading.Thread(target=publish_from_thread, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Thread errors: {errors}"

        # Wait for async dispatch
        await asyncio.sleep(0.3)

        # Collect all received events
        received_indices: list[int] = []
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "attempt":
                received_indices.append(event["idx"])

        # All events should be received (order may vary across threads)
        expected = set(published_indices)
        actual = set(received_indices)
        assert actual == expected, f"Missing events: {expected - actual}"

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, queue)

    @pytest.mark.asyncio
    async def test_thread_publish_with_subscriber_churn(self) -> None:
        """Thread publishing while subscribers are added/removed."""
        pm = CodeProgressManager()
        run_id = "thread_churn"

        await pm.start_run(run_id, {})

        # Stable subscriber to verify events
        stable_queue = await pm.subscribe(run_id)
        await asyncio.wait_for(stable_queue.get(), timeout=1.0)  # init

        stop_flag = threading.Event()
        errors: list[BaseException] = []
        max_events = 2_000

        def background_publisher() -> None:
            try:
                idx = 0
                while idx < max_events and not stop_flag.is_set():
                    pm.publish_attempt(run_id, {"idx": idx})
                    idx += 1
                    if idx % 50 == 0:
                        time.sleep(0.001)
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        # Start background publisher
        publisher_thread = threading.Thread(target=background_publisher)
        publisher_thread.start()

        # Churn subscribers in foreground
        for _ in range(20):
            q = await pm.subscribe(run_id)
            await asyncio.sleep(0.01)
            await pm.unsubscribe(run_id, q)

        # Stop publishing
        stop_flag.set()
        publisher_thread.join(timeout=2)
        assert not errors

        await asyncio.sleep(0.1)

        # Verify stable subscriber received events
        received_count = 0
        while not stable_queue.empty():
            event = stable_queue.get_nowait()
            if event["type"] == "attempt":
                received_count += 1

        assert received_count > 0, "Should have received some events"

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, stable_queue)

    @pytest.mark.asyncio
    async def test_thread_pool_publish_stress(self) -> None:
        """Use thread pool to simulate heavy concurrent publishing."""
        pm = CodeProgressManager()
        run_id = "pool_stress"
        num_workers = 8
        events_per_worker = 50

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)
        await asyncio.wait_for(queue.get(), timeout=1.0)  # init

        def worker(worker_id: int) -> int:
            for i in range(events_per_worker):
                pm.publish_attempt(run_id, {"worker": worker_id, "i": i})
            return worker_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = [pool.submit(worker, i) for i in range(num_workers)]
            concurrent.futures.wait(futures)

        await asyncio.sleep(0.3)

        # Count received
        count = 0
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "attempt":
                count += 1

        expected = num_workers * events_per_worker
        assert count == expected, f"Expected {expected} events, got {count}"

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, queue)


class TestQAProgressManagerStress:
    """Stress tests for QA progress manager (same behavior, different prefix)."""

    @pytest.mark.asyncio
    async def test_qa_many_subscribers(self) -> None:
        """QA progress manager with many subscribers."""
        pm = QAProgressManager()
        run_id = "qa_stress"
        num_subscribers = 30
        num_events = 15

        await pm.start_run(run_id, {"kind": "qa"})

        queues = [await pm.subscribe(run_id) for _ in range(num_subscribers)]

        # Consume init events
        for q in queues:
            init = await asyncio.wait_for(q.get(), timeout=1.0)
            assert init["type"] == "init"

        # Publish events
        for i in range(num_events):
            pm.publish_attempt(run_id, {"question_number": i})

        await asyncio.sleep(0.1)

        # Verify all subscribers got all events
        for q in queues:
            for i in range(num_events):
                event = await asyncio.wait_for(q.get(), timeout=1.0)
                assert event["type"] == "attempt"
                assert event["question_number"] == i

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        for q in queues:
            await pm.unsubscribe(run_id, q)

        assert run_id not in pm._runs

    @pytest.mark.asyncio
    async def test_qa_thread_safety(self) -> None:
        """QA progress manager cross-thread publishing."""
        pm = QAProgressManager()
        run_id = "qa_thread"

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)
        await asyncio.wait_for(queue.get(), timeout=1.0)  # init

        errors: list[BaseException] = []

        def publish() -> None:
            try:
                for i in range(50):
                    pm.publish_attempt(run_id, {"q": i})
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=publish) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors

        await asyncio.sleep(0.2)

        count = 0
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "attempt":
                count += 1

        assert count == 250, f"Expected 250 events, got {count}"

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, queue)


class TestEdgeCases:
    """Edge case tests for robustness."""

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_run(self) -> None:
        """Unsubscribe from non-existent run should not raise."""
        pm = CodeProgressManager()
        fake_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Should not raise
        await pm.unsubscribe("nonexistent_run", fake_queue)

    @pytest.mark.asyncio
    async def test_unsubscribe_wrong_queue(self) -> None:
        """Unsubscribe with wrong queue should not raise."""
        pm = CodeProgressManager()
        run_id = "wrong_queue"

        await pm.start_run(run_id, {})
        correct_queue = await pm.subscribe(run_id)
        wrong_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        # Should not raise
        await pm.unsubscribe(run_id, wrong_queue)

        # Run should still exist (correct subscriber still active)
        assert run_id in pm._runs

        # Cleanup
        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, correct_queue)

    @pytest.mark.asyncio
    async def test_double_unsubscribe(self) -> None:
        """Double unsubscribe should not raise."""
        pm = CodeProgressManager()
        run_id = "double_unsub"

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)
        pm.complete(run_id, {})
        await asyncio.sleep(0.05)

        await pm.unsubscribe(run_id, queue)
        # Second unsubscribe on now-deleted run
        await pm.unsubscribe(run_id, queue)

    @pytest.mark.asyncio
    async def test_publish_to_nonexistent_run(self) -> None:
        """Publishing to non-existent run should not raise."""
        pm = CodeProgressManager()
        # Initialize the event loop reference by starting a real run first
        real_run = "real_run"
        await pm.start_run(real_run, {})

        # Now publishing to a non-existent run should dispatch without error
        pm.publish_attempt("nonexistent", {"data": "test"})
        pm.complete("nonexistent", {})
        pm.fail("nonexistent", "error")
        await asyncio.sleep(0.1)

        # Cleanup the real run
        pm.complete(real_run, {})
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_subscribe_to_nonexistent_run(self) -> None:
        """Subscribe to non-existent run should raise KeyError."""
        pm = CodeProgressManager()
        with pytest.raises(KeyError):
            await pm.subscribe("nonexistent")

    @pytest.mark.asyncio
    async def test_rapid_complete_fail_race(self) -> None:
        """Racing complete and fail should not cause issues."""
        pm = CodeProgressManager()
        run_id = "race"

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)
        await asyncio.wait_for(queue.get(), timeout=1.0)  # init

        # Race complete and fail
        pm.complete(run_id, {"status": "ok"})
        pm.fail(run_id, "also failed")

        await asyncio.sleep(0.1)

        # Should get at least one terminal event
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        terminal_types = {e["type"] for e in events}
        assert "complete" in terminal_types or "error" in terminal_types

        await pm.unsubscribe(run_id, queue)


class TestBoundedStress:
    """Bounded stress tests that remain CI-friendly."""

    @pytest.mark.asyncio
    async def test_bounded_rapid_subscribe_unsubscribe(self) -> None:
        """Rapidly subscribe/unsubscribe many times."""
        pm = CodeProgressManager()
        run_id = "rapid_sub"
        iterations = 200

        await pm.start_run(run_id, {})

        for _ in range(iterations):
            q = await pm.subscribe(run_id)
            await pm.unsubscribe(run_id, q)

        # Run should still exist (not done)
        assert run_id in pm._runs

        # Subscribe once more to trigger cleanup after complete
        final_q = await pm.subscribe(run_id)
        pm.complete(run_id, {})
        await asyncio.sleep(0.05)

        # Unsubscribe triggers cleanup since run is done and no more subscribers
        await pm.unsubscribe(run_id, final_q)
        assert run_id not in pm._runs

    @pytest.mark.asyncio
    async def test_bounded_many_events_single_subscriber(self) -> None:
        """Publish many events to single subscriber."""
        pm = CodeProgressManager()
        run_id = "many_events"
        num_events = 1000

        await pm.start_run(run_id, {})
        queue = await pm.subscribe(run_id)
        await asyncio.wait_for(queue.get(), timeout=1.0)  # init

        for i in range(num_events):
            pm.publish_attempt(run_id, {"i": i})

        await asyncio.sleep(0.5)

        count = 0
        while not queue.empty():
            queue.get_nowait()
            count += 1

        assert count == num_events

        pm.complete(run_id, {})
        await asyncio.sleep(0.05)
        await pm.unsubscribe(run_id, queue)
