"""Formatting helpers for task summaries."""

from typing import Iterable, Mapping


def summarize_entries(entries: Iterable[Mapping[str, object]]) -> str:
    """Return a human-readable summary string.

    The output should contain:
    - total task count
    - counts per stage
    - average duration (rounded to one decimal place)

    The placeholder implementation is intentionally incorrect.
    """

    del entries
    return ""
