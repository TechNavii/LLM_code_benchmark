"""Data loading helpers for the reporting CLI."""

from typing import List, TypedDict


class Entry(TypedDict):
    assignee: str
    stage: str
    duration_minutes: int


def load_entries(raw: str) -> List[Entry]:
    """Parse CSV-like text into entry dictionaries.

    The expected format is one record per line, with comma-separated fields:
        name, stage, duration_minutes

    The placeholder implementation is intentionally incorrect.
    """

    del raw
    return []
