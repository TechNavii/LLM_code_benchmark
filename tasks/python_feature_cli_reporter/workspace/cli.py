"""Entry point for generating task reports."""

from reporting import load_entries, summarize_entries


def generate_report(raw: str) -> str:
    """Build a summary report from raw text input."""

    entries = load_entries(raw)
    return summarize_entries(entries)


__all__ = ["generate_report"]
