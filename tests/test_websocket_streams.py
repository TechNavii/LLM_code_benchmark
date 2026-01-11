"""WebSocket stream contract tests for run and QA progress endpoints.

These tests verify the WebSocket streaming behavior for /runs/{run_id}/stream
and /qa/runs/{run_id}/stream endpoints, including event ordering, event shape,
and error handling.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from server.api import create_app
from server.progress import ProgressManager
from server.qa_progress import ProgressManager as QAProgressManager


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


# Benchmark Run WebSocket Tests


def test_run_stream_missing_run_id_closes_with_4404(client: TestClient) -> None:
    """Test that connecting to a non-existent run_id closes with code 4404."""
    with client.websocket_connect("/runs/nonexistent_run/stream") as websocket:
        # The server should close the connection with code 4404
        # when the run_id is not found
        data = websocket.receive()
        assert data["type"] == "websocket.close"
        assert data["code"] == 4404


def test_run_stream_event_shape() -> None:
    """Test event ordering: init -> attempt(s) -> complete for run stream."""

    async def test() -> None:
        pm = ProgressManager()
        run_id = pm.generate_run_id()

        # Start a run
        await pm.start_run(
            run_id,
            {
                "models": ["test-model"],
                "tasks": ["task1"],
                "timestamp": "2026-01-11T12:00:00Z",
            },
        )

        # Subscribe
        queue = await pm.subscribe(run_id)

        # Event 1: init event
        init_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert init_event["type"] == "init"
        assert init_event["run_id"] == run_id
        assert "metadata" in init_event
        assert init_event["metadata"]["models"] == ["test-model"]

        # Publish attempt
        pm.publish_attempt(
            run_id,
            {
                "model": "test-model",
                "task_id": "task1",
                "sample_index": 0,
                "status": "success",
            },
        )

        # Event 2: attempt event
        attempt_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["model"] == "test-model"
        assert attempt_event["task_id"] == "task1"
        assert attempt_event["sample_index"] == 0
        assert attempt_event["status"] == "success"

        # Complete
        pm.complete(run_id, {"run_id": run_id, "accuracy": 0.85})

        # Event 3: complete event
        complete_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert complete_event["type"] == "complete"
        assert "summary" in complete_event
        assert complete_event["summary"]["accuracy"] == 0.85

        # Unsubscribe
        await pm.unsubscribe(run_id, queue)

    asyncio.run(test())


def test_run_stream_error_event_shape() -> None:
    """Test event ordering: init -> attempt(s) -> error for run stream."""

    async def test() -> None:
        pm = ProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(run_id, {"models": ["test-model"], "tasks": ["task1"]})
        queue = await pm.subscribe(run_id)

        # Event 1: init
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Publish attempt with error
        pm.publish_attempt(
            run_id,
            {
                "model": "test-model",
                "task_id": "task1",
                "sample_index": 0,
                "status": "api_error",
                "error": "Connection timeout",
            },
        )

        # Event 2: attempt with error
        attempt_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["status"] == "api_error"
        assert attempt_event["error"] == "Connection timeout"

        # Fail the run
        pm.fail(run_id, "Run failed due to API error")

        # Event 3: error event
        error_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert error_event["type"] == "error"
        assert error_event["message"] == "Run failed due to API error"

        await pm.unsubscribe(run_id, queue)

    asyncio.run(test())


def test_run_stream_multiple_attempts() -> None:
    """Test that multiple attempt events are delivered in order."""

    async def test() -> None:
        pm = ProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(run_id, {"models": ["model1", "model2"]})
        queue = await pm.subscribe(run_id)

        # Get init event
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Publish multiple attempts
        for i in range(3):
            pm.publish_attempt(
                run_id,
                {
                    "model": f"model-{i}",
                    "task_id": f"task-{i}",
                    "sample_index": i,
                    "status": "success",
                },
            )

        # Receive all three attempts
        for i in range(3):
            attempt = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert attempt["type"] == "attempt"
            assert attempt["model"] == f"model-{i}"
            assert attempt["task_id"] == f"task-{i}"
            assert attempt["sample_index"] == i

        # Complete
        pm.complete(run_id, {})
        complete_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert complete_event["type"] == "complete"

        await pm.unsubscribe(run_id, queue)

    asyncio.run(test())


def test_run_stream_cleanup_after_disconnect() -> None:
    """Test that unsubscribe is called and cleanup occurs when done."""

    async def test() -> None:
        pm = ProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(run_id, {"models": ["test-model"]})
        queue = await pm.subscribe(run_id)

        # Get init event
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Complete the run
        pm.complete(run_id, {})

        # Get complete event
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Unsubscribe
        await pm.unsubscribe(run_id, queue)

        # Verify cleanup - run should be removed after last subscriber unsubscribes
        # and run is done
        assert run_id not in pm._runs

    asyncio.run(test())


# QA Run WebSocket Tests


def test_qa_stream_missing_run_id_closes_with_4404(client: TestClient) -> None:
    """Test that connecting to a non-existent QA run_id closes with code 4404."""
    with client.websocket_connect("/qa/runs/nonexistent_qa_run/stream") as websocket:
        data = websocket.receive()
        assert data["type"] == "websocket.close"
        assert data["code"] == 4404


def test_qa_stream_event_shape() -> None:
    """Test event ordering: init -> attempt(s) -> complete for QA stream."""

    async def test() -> None:
        pm = QAProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(
            run_id,
            {
                "models": ["test-model"],
                "question_count": 5,
                "timestamp": "2026-01-11T12:00:00Z",
            },
        )

        queue = await pm.subscribe(run_id)

        # Event 1: init
        init_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert init_event["type"] == "init"
        assert init_event["run_id"] == run_id
        assert init_event["metadata"]["question_count"] == 5

        # Publish QA attempt
        pm.publish_attempt(
            run_id,
            {
                "model": "test-model",
                "question_number": 1,
                "sample_index": 0,
                "status": "success",
                "judge_decision": "correct",
            },
        )

        # Event 2: attempt
        attempt_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["question_number"] == 1
        assert attempt_event["judge_decision"] == "correct"

        # Complete
        pm.complete(run_id, {"accuracy": 0.9})

        # Event 3: complete
        complete_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert complete_event["type"] == "complete"
        assert complete_event["summary"]["accuracy"] == 0.9

        await pm.unsubscribe(run_id, queue)

    asyncio.run(test())


def test_qa_stream_error_event_shape() -> None:
    """Test event ordering: init -> attempt(s) -> error for QA stream."""

    async def test() -> None:
        pm = QAProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(
            run_id,
            {"models": ["test-model"], "question_count": 3},
        )

        queue = await pm.subscribe(run_id)

        # Event 1: init
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Publish attempt with error
        pm.publish_attempt(
            run_id,
            {
                "model": "test-model",
                "question_number": 1,
                "sample_index": 0,
                "status": "api_error",
                "error": "Rate limit exceeded",
            },
        )

        # Event 2: attempt
        attempt_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["status"] == "api_error"
        assert attempt_event["error"] == "Rate limit exceeded"

        # Fail the run
        pm.fail(run_id, "QA run failed")

        # Event 3: error
        error_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert error_event["type"] == "error"
        assert error_event["message"] == "QA run failed"

        await pm.unsubscribe(run_id, queue)

    asyncio.run(test())


def test_qa_stream_multiple_attempts() -> None:
    """Test that multiple QA attempt events are delivered in order."""

    async def test() -> None:
        pm = QAProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(
            run_id,
            {"models": ["test-model"], "question_count": 3},
        )

        queue = await pm.subscribe(run_id)

        # Get init
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Publish multiple QA attempts
        for question_num in range(1, 4):
            pm.publish_attempt(
                run_id,
                {
                    "model": "test-model",
                    "question_number": question_num,
                    "sample_index": 0,
                    "status": "success",
                    "judge_decision": "correct" if question_num % 2 == 1 else "incorrect",
                },
            )

        # Receive all attempts
        for question_num in range(1, 4):
            attempt = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert attempt["type"] == "attempt"
            assert attempt["question_number"] == question_num
            expected_decision = "correct" if question_num % 2 == 1 else "incorrect"
            assert attempt["judge_decision"] == expected_decision

        # Complete
        pm.complete(run_id, {})
        complete_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert complete_event["type"] == "complete"

        await pm.unsubscribe(run_id, queue)

    asyncio.run(test())


def test_qa_stream_cleanup_after_disconnect() -> None:
    """Test that unsubscribe is called and cleanup occurs when QA run is done."""

    async def test() -> None:
        pm = QAProgressManager()
        run_id = pm.generate_run_id()

        await pm.start_run(run_id, {"models": ["test-model"]})
        queue = await pm.subscribe(run_id)

        # Get init
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Complete to trigger cleanup
        pm.complete(run_id, {})

        # Get complete
        await asyncio.wait_for(queue.get(), timeout=1.0)

        # Unsubscribe
        await pm.unsubscribe(run_id, queue)

        # Should be cleaned up
        assert run_id not in pm._runs

    asyncio.run(test())
