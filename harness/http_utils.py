"""Small HTTP-related helpers shared by harness modules."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Parse the Retry-After header into a delay (seconds)."""

    retry_after = headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        pass

    try:
        from email.utils import parsedate_to_datetime

        retry_dt = parsedate_to_datetime(retry_after)
        delay = (retry_dt - dt.datetime.now(dt.UTC)).total_seconds()
        return max(0.0, delay)
    except (ValueError, TypeError):
        return None
