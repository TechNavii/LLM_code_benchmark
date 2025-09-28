import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workspace"))

from workflow import compute_schedule


def build_tasks(defs):
    return [
        {"id": task_id, "duration": duration, "deps": deps}
        for task_id, duration, deps in defs
    ]


def test_basic_timing_and_makespan():
    tasks = build_tasks(
        [
            ("ingest", 4, []),
            ("clean", 3, ["ingest"]),
            ("analyze", 5, ["clean"]),
        ]
    )
    result = compute_schedule(tasks)
    assert result["order"] == ["ingest", "clean", "analyze"]
    assert result["start_times"] == {"ingest": 0, "clean": 4, "analyze": 7}
    assert result["finish_times"] == {"ingest": 4, "clean": 7, "analyze": 12}
    assert result["total_duration"] == 12


def test_parallel_branches_and_tie_breaking():
    tasks = build_tasks(
        [
            ("model", 6, ["features"]),
            ("dashboard", 2, ["summary"]),
            ("features", 5, ["raw_a", "raw_b"]),
            ("summary", 3, ["features"]),
            ("raw_a", 2, []),
            ("raw_b", 4, []),
        ]
    )
    result = compute_schedule(tasks)

    # Independent roots should appear lexicographically (raw_a before raw_b)
    assert result["order"][:2] == ["raw_a", "raw_b"]

    assert result["start_times"]["features"] == 4  # waits for raw_b
    assert result["finish_times"]["model"] == 15
    assert result["finish_times"]["dashboard"] == 13
    assert result["total_duration"] == 15


def test_missing_dependency_raises_key_error():
    tasks = build_tasks(
        [
            ("build", 1, []),
            ("deploy", 1, ["build", "signoff"]),
        ]
    )
    with pytest.raises(KeyError) as exc:
        compute_schedule(tasks)
    assert "signoff" in str(exc.value)


def test_cycle_detection():
    tasks = build_tasks(
        [
            ("extract", 3, ["transform"]),
            ("transform", 2, ["extract"]),
        ]
    )
    with pytest.raises(ValueError) as exc:
        compute_schedule(tasks)
    assert "cycle" in str(exc.value).lower()


def test_large_shared_dependencies():
    tasks = build_tasks(
        [
            ("root", 1, []),
            ("a", 2, ["root"]),
            ("b", 2, ["root"]),
            ("c", 2, ["root"]),
            ("fanout1", 3, ["a", "b"]),
            ("fanout2", 4, ["a", "c"]),
            ("fanout3", 5, ["b", "c"]),
            ("merge", 1, ["fanout1", "fanout2", "fanout3"]),
        ]
    )
    result = compute_schedule(tasks)
    assert result["start_times"]["merge"] == 7
    assert result["total_duration"] == 8
    # Ensure deterministic order for siblings with identical ready times.
    assert result["order"][:4] == ["root", "a", "b", "c"]
