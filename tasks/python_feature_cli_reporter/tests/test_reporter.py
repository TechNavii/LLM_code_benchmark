import pytest

from cli import generate_report
from reporting import load_entries, summarize_entries

RAW_INPUT = """
Alice, Completed, 30
Bob, In_Progress, 50
Cara, completed, 40

# comment line should be ignored
Dana, Review, 60
""".strip()


def test_load_entries_parses_records():
    entries = load_entries(RAW_INPUT)
    assert len(entries) == 4
    assert entries[0] == {"assignee": "Alice", "stage": "completed", "duration_minutes": 30}
    assert entries[-1] == {"assignee": "Dana", "stage": "review", "duration_minutes": 60}


def test_summarize_entries_formats_output():
    entries = load_entries(RAW_INPUT)
    summary = summarize_entries(entries)
    lines = summary.splitlines()
    assert lines[0] == "total_tasks: 4"
    assert lines[1:] == ["completed: 2", "in_progress: 1", "review: 1", "avg_duration_minutes: 45.0"]


def test_generate_report_matches_helpers():
    report = generate_report(RAW_INPUT)
    assert "total_tasks: 4" in report
    assert report.endswith("avg_duration_minutes: 45.0")


def test_invalid_duration_raises():
    bad_raw = "Alice, Completed, twelve"
    with pytest.raises(ValueError):
        load_entries(bad_raw)


def test_empty_input_results_in_zero_summary():
    report = generate_report("\n   \n")
    assert report == "total_tasks: 0\navg_duration_minutes: 0.0"
