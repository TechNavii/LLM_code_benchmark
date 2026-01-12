"""Shared database utilities."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any


FAILED_STATUSES: set[str] = {"error", "fail", "failed", "api_error", "exception"}


def parse_timestamp(timestamp_raw: str | None) -> dt.datetime:
    """Parse an ISO timestamp string to a naive UTC datetime.

    Falls back to current UTC time if parsing fails.
    Returns a naive datetime (no tzinfo) suitable for SQLite storage.
    """
    if timestamp_raw:
        try:
            timestamp = dt.datetime.fromisoformat(timestamp_raw)
        except ValueError:
            timestamp = dt.datetime.now(dt.UTC)
    else:
        timestamp = dt.datetime.now(dt.UTC)

    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(dt.UTC).replace(tzinfo=None)

    return timestamp


def count_errors_from_summary(summary_json: str | None) -> int:
    """Count failed attempts from a summary JSON string."""
    if not summary_json:
        return 0
    try:
        summary = json.loads(summary_json)
        attempts = summary.get("attempts", [])
        return sum(1 for a in attempts if a.get("status", "").lower() in FAILED_STATUSES)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return 0


def extract_usage_tokens(usage: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """Extract prompt and completion tokens from a usage dict.

    Handles both OpenAI-style (prompt_tokens/completion_tokens) and
    Anthropic-style (input_tokens/output_tokens) keys.
    """
    if not usage:
        return None, None
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    return prompt, completion


__all__ = [
    "FAILED_STATUSES",
    "parse_timestamp",
    "count_errors_from_summary",
    "extract_usage_tokens",
]
