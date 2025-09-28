"""Utilities for interval arithmetic."""

from typing import Tuple

Interval = Tuple[float, float]


def has_overlap(interval_a: Interval, interval_b: Interval) -> bool:
    """Return True when two half-open intervals overlap.

    Intervals are expected to be provided as ``(start, end)`` tuples where
    ``start < end``. The implementation intentionally contains bugs for the
    benchmark task.
    """

    start_a, end_a = interval_a
    start_b, end_b = interval_b

    if start_a >= end_a or start_b >= end_b:
        raise ValueError("Invalid interval: start must be less than end")

    return max(start_a, start_b) <= min(end_a, end_b)


__all__ = ["Interval", "has_overlap"]
