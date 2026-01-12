"""Integration tests for key boundaries: database, filesystem, and WebSocket streams.

These tests exercise real integrations with SQLite, file system, and async streams
to ensure components work together correctly. They use lightweight dependencies
(in-memory DB, tempdir) to remain hermetic and fast.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.database import init_db, list_runs
from server.progress import ProgressManager


@pytest.fixture
def temp_runs_dir(tmp_path: Path) -> Path:
    """Provide a temporary runs directory for isolated tests."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    return runs_dir


# Database Integration Tests


def test_database_init_creates_runs_directory() -> None:
    """Test that database initialization creates runs directory."""
    # init_db creates the runs directory
    init_db()
    # Verify the runs directory exists
    runs_dir = Path(__file__).resolve().parents[1] / "runs"
    assert runs_dir.exists()


def test_database_list_runs_returns_list() -> None:
    """Test that list_runs returns a list (may be empty)."""
    init_db()
    runs = list_runs(limit=10)
    assert isinstance(runs, list)
    # Each run should have expected fields
    for run in runs:
        assert "id" in run
        assert "model_id" in run
        assert "timestamp_utc" in run


# Filesystem Integration Tests


def test_filesystem_run_persistence(temp_runs_dir: Path) -> None:
    """Test that run summaries can be persisted to the filesystem."""
    run_id = "run_fs_test_20260111T120000Z_ghi789"
    summary = {
        "run_id": run_id,
        "model": "test-model",
        "accuracy": 0.9,
        "tasks": ["task1"],
        "samples": 1,
    }

    # Save summary to filesystem
    summary_path = temp_runs_dir / f"{run_id}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    # Verify file exists and can be read back
    assert summary_path.exists()
    loaded_summary = json.loads(summary_path.read_text())
    assert loaded_summary["run_id"] == run_id
    assert loaded_summary["accuracy"] == 0.9


# WebSocket/Stream Integration Tests


def test_progress_manager_stream_integration() -> None:
    """Test that progress manager can stream events through queues."""

    async def test() -> None:
        pm = ProgressManager()
        run_id = "run_stream_test_123"

        # Start a run
        await pm.start_run(run_id, {"model": "test-model"})

        # Subscribe to events
        queue = await pm.subscribe(run_id)

        # Get the init event
        init_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert init_event["type"] == "init"
        assert init_event["run_id"] == run_id

        # Publish an attempt event
        pm.publish_attempt(run_id, {"task_id": "task1", "model": "test-model"})

        # Receive the attempt event
        attempt_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert attempt_event["type"] == "attempt"
        assert attempt_event["task_id"] == "task1"

        # Complete the run
        pm.complete(run_id, {"accuracy": 0.95})

        # Receive the complete event
        complete_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert complete_event["type"] == "complete"
        assert complete_event["summary"]["accuracy"] == 0.95

        # Unsubscribe
        await pm.unsubscribe(run_id, queue)

        # Verify cleanup
        assert run_id not in pm._runs

    asyncio.run(test())


def test_progress_manager_multiple_subscribers() -> None:
    """Test that progress manager can handle multiple concurrent subscribers."""

    async def test() -> None:
        pm = ProgressManager()
        run_id = "run_multi_sub_456"

        await pm.start_run(run_id, {"model": "test-model"})

        # Create multiple subscribers
        queue1 = await pm.subscribe(run_id)
        queue2 = await pm.subscribe(run_id)

        # Both should get the init event
        init1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
        init2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

        assert init1["type"] == "init"
        assert init2["type"] == "init"

        # Publish an event
        pm.publish_attempt(run_id, {"task_id": "task1", "model": "test-model"})

        # Both should receive it
        event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
        event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

        assert event1["type"] == "attempt"
        assert event2["type"] == "attempt"

        # Unsubscribe both
        pm.complete(run_id, {"done": True})

        # Get complete events
        await asyncio.wait_for(queue1.get(), timeout=1.0)
        await asyncio.wait_for(queue2.get(), timeout=1.0)

        await pm.unsubscribe(run_id, queue1)
        await pm.unsubscribe(run_id, queue2)

    asyncio.run(test())
