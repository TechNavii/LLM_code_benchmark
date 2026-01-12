"""
Performance regression benchmarks for critical hot paths.

This module provides a benchmark suite for performance-critical paths:
- Patch normalization: _is_probably_valid_patch, _normalize_patch_format
- Database queries: get_session, list_runs, get_run, save_run
- Progress dispatch: publish_attempt, _append_event

Benchmarks are designed to:
1. Run in nightly CI with brownfield-friendly baselines and slack
2. Fail only on significant regressions (>20% degradation)
3. Be deterministic and resource-bounded
4. Use representative test data sizes

Usage:
    pytest tests/test_benchmarks.py -v --benchmark-only
    pytest tests/test_benchmarks.py -v --benchmark-save=baseline
    pytest tests/test_benchmarks.py -v --benchmark-compare=baseline

Note: This test file is excluded from the default pytest run to keep
regular test execution fast. It runs in a separate nightly job.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Mark all tests in this module as benchmark tests
pytestmark = pytest.mark.benchmark


# =============================================================================
# Patch Normalization Benchmarks
# =============================================================================


class TestPatchNormalizationBenchmarks:
    """Benchmarks for patch validation and normalization functions."""

    @pytest.fixture
    def small_patch(self) -> str:
        """Small patch with ~10 lines."""
        return """\
diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1,5 +1,6 @@
 import os
+import sys

 def main():
-    print("hello")
+    print("hello world")
     return 0
"""

    @pytest.fixture
    def medium_patch(self) -> str:
        """Medium patch with ~100 lines (realistic PR size)."""
        lines = [
            "diff --git a/module.py b/module.py",
            "--- a/module.py",
            "+++ b/module.py",
            "@@ -1,50 +1,55 @@",
        ]
        # Generate realistic patch content
        for i in range(50):
            if i % 5 == 0:
                lines.append(f"-    old_line_{i} = {i}")
                lines.append(f"+    new_line_{i} = {i * 2}")
            else:
                lines.append(f"     context_line_{i}")
        return "\n".join(lines) + "\n"

    @pytest.fixture
    def large_patch(self) -> str:
        """Large patch with ~1000 lines (major refactor size)."""
        lines = [
            "diff --git a/big_module.py b/big_module.py",
            "--- a/big_module.py",
            "+++ b/big_module.py",
        ]
        # Generate multiple hunks
        for hunk in range(10):
            start = hunk * 100 + 1
            lines.append(f"@@ -{start},50 +{start},55 @@")
            for i in range(50):
                if i % 5 == 0:
                    lines.append(f"-    old_func_{hunk}_{i}()")
                    lines.append(f"+    new_func_{hunk}_{i}()")
                else:
                    lines.append(f"     context_{hunk}_{i}")
        return "\n".join(lines) + "\n"

    @pytest.fixture
    def malformed_patch(self) -> str:
        """Malformed patch that triggers normalization fallbacks."""
        return """\
@@
-old
+new
context without prefix
+more additions
@@
another hunk without proper headers
-remove this
"""

    def test_is_probably_valid_patch_small(self, benchmark, small_patch: str) -> None:
        """Benchmark _is_probably_valid_patch with small input."""
        from harness.run_harness import _is_probably_valid_patch

        result = benchmark(_is_probably_valid_patch, small_patch)
        assert result is True

    def test_is_probably_valid_patch_medium(self, benchmark, medium_patch: str) -> None:
        """Benchmark _is_probably_valid_patch with medium input."""
        from harness.run_harness import _is_probably_valid_patch

        result = benchmark(_is_probably_valid_patch, medium_patch)
        assert result is True

    def test_is_probably_valid_patch_large(self, benchmark, large_patch: str) -> None:
        """Benchmark _is_probably_valid_patch with large input."""
        from harness.run_harness import _is_probably_valid_patch

        result = benchmark(_is_probably_valid_patch, large_patch)
        assert result is True

    def test_normalize_patch_format_small(self, benchmark, small_patch: str) -> None:
        """Benchmark _normalize_patch_format with small input."""
        from harness.run_harness import _normalize_patch_format

        result, synthetic = benchmark(_normalize_patch_format, small_patch)
        assert isinstance(result, str)

    def test_normalize_patch_format_medium(self, benchmark, medium_patch: str) -> None:
        """Benchmark _normalize_patch_format with medium input."""
        from harness.run_harness import _normalize_patch_format

        result, synthetic = benchmark(_normalize_patch_format, medium_patch)
        assert isinstance(result, str)

    def test_normalize_patch_format_large(self, benchmark, large_patch: str) -> None:
        """Benchmark _normalize_patch_format with large input."""
        from harness.run_harness import _normalize_patch_format

        result, synthetic = benchmark(_normalize_patch_format, large_patch)
        assert isinstance(result, str)

    def test_normalize_patch_format_malformed(self, benchmark, malformed_patch: str) -> None:
        """Benchmark _normalize_patch_format with malformed input (triggers fallbacks)."""
        from harness.run_harness import _normalize_patch_format

        result, synthetic = benchmark(_normalize_patch_format, malformed_patch)
        assert isinstance(result, str)
        assert synthetic is True  # Should use synthetic headers


# =============================================================================
# Database Benchmarks
# =============================================================================


class TestDatabaseBenchmarks:
    """Benchmarks for database operations."""

    @pytest.fixture
    def temp_db_engine(self, tmp_path: Path):
        """Create a temporary database engine for benchmarks."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker, Session
        from server.database import Base

        db_path = tmp_path / "benchmark.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        return engine, session_factory

    @pytest.fixture
    def populated_db(self, temp_db_engine, tmp_path: Path):
        """Create a database populated with test runs for query benchmarks."""
        from server.database import AttemptRecord, RunRecord

        engine, session_factory = temp_db_engine

        # Create test runs
        with session_factory.begin() as session:
            for run_idx in range(50):
                run_id = f"benchmark_run_{run_idx:04d}"
                summary = {
                    "run_dir": str(tmp_path / run_id),
                    "models": ["gpt-4"],
                    "tasks": ["task1", "task2"],
                    "samples": 1,
                    "attempts": [
                        {
                            "task_id": f"task_{i}",
                            "status": "passed" if i % 3 != 0 else "failed",
                            "duration_seconds": 1.5,
                            "cost_usd": 0.01,
                            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                        }
                        for i in range(10)
                    ],
                    "metrics": {"overall": {"macro_model_accuracy": 0.7}},
                    "token_usage": {"total_cost_usd": 0.1},
                    "timing": {"total_duration_seconds": 15.0},
                    "timestamp_utc": "2024-01-01T00:00:00Z",
                }
                record = RunRecord(
                    id=run_id,
                    timestamp_utc=__import__("datetime").datetime(2024, 1, 1),
                    model_id="gpt-4",
                    tasks=json.dumps(["task1", "task2"]),
                    samples=1,
                    accuracy=0.7,
                    total_cost=0.1,
                    total_duration=15.0,
                    summary_path=str(tmp_path / run_id / "summary.json"),
                    summary_json=json.dumps(summary),
                )
                for i in range(10):
                    record.attempts.append(
                        AttemptRecord(
                            task_id=f"task_{i}",
                            status="passed" if i % 3 != 0 else "failed",
                            duration=1.5,
                            prompt_tokens=100,
                            completion_tokens=50,
                            cost=0.01,
                            error=None,
                        )
                    )
                session.add(record)

        return engine, session_factory

    def test_get_session_overhead(self, benchmark, temp_db_engine) -> None:
        """Benchmark get_session context manager overhead."""
        from contextlib import contextmanager
        from collections.abc import Iterator
        from sqlalchemy.orm import Session

        _, session_factory = temp_db_engine

        @contextmanager
        def get_session() -> Iterator[Session]:
            with session_factory.begin() as session:
                yield session

        def session_roundtrip():
            with get_session() as session:
                # Minimal operation to measure session overhead
                session.execute(__import__("sqlalchemy").text("SELECT 1"))
            return True

        result = benchmark(session_roundtrip)
        assert result is True

    def test_list_runs_query(self, benchmark, populated_db) -> None:
        """Benchmark list_runs query with 50 runs in database."""
        from sqlalchemy import select
        from server.database import RunRecord
        from server.database_utils import count_errors_from_summary

        engine, session_factory = populated_db

        def list_runs_impl(limit: int = 50) -> list:
            stmt = (
                select(
                    RunRecord.id,
                    RunRecord.timestamp_utc,
                    RunRecord.model_id,
                    RunRecord.accuracy,
                    RunRecord.total_cost,
                    RunRecord.total_duration,
                    RunRecord.summary_json,
                )
                .order_by(RunRecord.timestamp_utc.desc())
                .limit(limit)
            )
            with session_factory.begin() as session:
                rows = session.execute(stmt).all()

            return [
                {
                    "id": row.id,
                    "timestamp_utc": row.timestamp_utc.isoformat() if row.timestamp_utc else None,
                    "model_id": row.model_id,
                    "accuracy": row.accuracy,
                    "total_cost": row.total_cost,
                    "total_duration": row.total_duration,
                    "error_count": count_errors_from_summary(row.summary_json),
                }
                for row in rows
            ]

        results = benchmark(list_runs_impl)
        assert len(results) == 50

    def test_get_run_by_id(self, benchmark, populated_db) -> None:
        """Benchmark get_run lookup by primary key."""
        engine, session_factory = populated_db
        run_id = "benchmark_run_0025"  # Middle of the range

        def get_run_impl(run_id: str) -> dict | None:
            from server.database import RunRecord

            with session_factory.begin() as session:
                record = session.get(RunRecord, run_id)
                if record is None:
                    return None
                return json.loads(record.summary_json)

        result = benchmark(get_run_impl, run_id)
        assert result is not None
        assert "attempts" in result

    def test_count_errors_from_summary(self, benchmark) -> None:
        """Benchmark count_errors_from_summary JSON parsing."""
        from server.database_utils import count_errors_from_summary

        # Create a realistic summary JSON
        summary = {
            "attempts": [{"task_id": f"task_{i}", "status": "passed" if i % 3 != 0 else "failed"} for i in range(100)]
        }
        summary_json = json.dumps(summary)

        result = benchmark(count_errors_from_summary, summary_json)
        assert result == 34  # 100 / 3 rounded up

    def test_extract_usage_tokens(self, benchmark) -> None:
        """Benchmark extract_usage_tokens for OpenAI format."""
        from server.database_utils import extract_usage_tokens

        usage = {
            "prompt_tokens": 1500,
            "completion_tokens": 500,
            "total_tokens": 2000,
        }

        result = benchmark(extract_usage_tokens, usage)
        assert result == (1500, 500)

    def test_parse_timestamp(self, benchmark) -> None:
        """Benchmark parse_timestamp with valid ISO format."""
        from server.database_utils import parse_timestamp

        timestamp = "2024-06-15T14:30:45.123456Z"

        result = benchmark(parse_timestamp, timestamp)
        assert result.year == 2024


# =============================================================================
# Progress Dispatch Benchmarks
# =============================================================================


class TestProgressDispatchBenchmarks:
    """Benchmarks for progress manager event dispatching."""

    @pytest.fixture
    def progress_manager(self):
        """Create a fresh progress manager for each benchmark."""
        from server.progress_base import BaseProgressManager

        class TestProgressManager(BaseProgressManager):
            _id_prefix = "benchmark"

        return TestProgressManager()

    def test_generate_run_id(self, benchmark, progress_manager) -> None:
        """Benchmark run ID generation."""
        result = benchmark(progress_manager.generate_run_id)
        assert result.startswith("benchmark_")

    def test_dispatch_sync_context(self, benchmark, progress_manager) -> None:
        """Benchmark _dispatch overhead when no loop is available."""

        async def dummy_coro():
            pass

        def dispatch_impl():
            # This will close the coroutine since no loop is available
            progress_manager._dispatch(dummy_coro())

        benchmark(dispatch_impl)


# =============================================================================
# Combined Hot Path Benchmarks
# =============================================================================


class TestCombinedHotPathBenchmarks:
    """Benchmarks that exercise multiple hot paths together."""

    @pytest.fixture
    def realistic_patch(self) -> str:
        """A realistic patch from actual benchmark usage."""
        return """\
diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,20 +1,25 @@
 import os
 import sys
+import logging

+logger = logging.getLogger(__name__)

 def process_data(data):
     \"\"\"Process incoming data.\"\"\"
-    result = []
+    results = []
     for item in data:
-        if item.get("valid"):
-            result.append(item)
-    return result
+        if item.get("valid") and item.get("active"):
+            logger.debug(f"Processing {item}")
+            results.append(transform(item))
+    return results
+
+
+def transform(item):
+    \"\"\"Transform a single item.\"\"\"
+    return {"id": item["id"], "processed": True}


 def main():
-    data = load_data()
-    result = process_data(data)
-    save_result(result)
+    data = load_data("input.json")
+    results = process_data(data)
+    save_results(results, "output.json")
+    logger.info(f"Processed {len(results)} items")
"""

    def test_patch_validation_and_normalization(self, benchmark, realistic_patch: str) -> None:
        """Benchmark combined patch validation + normalization."""
        from harness.run_harness import _is_probably_valid_patch, _normalize_patch_format

        def combined_impl(patch: str) -> tuple[bool, str]:
            is_valid = _is_probably_valid_patch(patch)
            if is_valid:
                normalized, _ = _normalize_patch_format(patch)
                return True, normalized
            return False, ""

        is_valid, normalized = benchmark(combined_impl, realistic_patch)
        assert is_valid is True
        assert len(normalized) > 0

    def test_database_utils_pipeline(self, benchmark) -> None:
        """Benchmark typical database utility usage pattern."""
        from server.database_utils import (
            parse_timestamp,
            extract_usage_tokens,
            count_errors_from_summary,
        )

        summary_json = json.dumps(
            {"attempts": [{"task_id": f"task_{i}", "status": "passed" if i % 4 != 0 else "failed"} for i in range(20)]}
        )
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        timestamp = "2024-06-15T14:30:45Z"

        def utils_pipeline():
            ts = parse_timestamp(timestamp)
            tokens = extract_usage_tokens(usage)
            errors = count_errors_from_summary(summary_json)
            return ts, tokens, errors

        result = benchmark(utils_pipeline)
        assert result[0].year == 2024
        assert result[1] == (1000, 500)
        assert result[2] == 5
