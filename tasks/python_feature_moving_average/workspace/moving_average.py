"""Utility functions for computing moving averages."""

from collections import deque
from typing import Deque, Iterable, List


def simple_moving_average(series: Iterable[float], window: int) -> List[float]:
    """Return the simple moving average over ``series`` with the given window size.

    The function should return a list of averages aligned with the original
    sequence (i.e. the first (window-1) entries are ``None``). The current
    placeholder implementation is wrong and needs to be implemented.
    """
    # TODO: implement simple moving average while keeping the API intact.
    del series, window
    return []


__all__ = ["simple_moving_average"]
