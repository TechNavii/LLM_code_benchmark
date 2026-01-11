"""Progress manager for the code benchmark harness."""

from __future__ import annotations

from server.progress_base import BaseProgressManager


class ProgressManager(BaseProgressManager):
    """Progress manager for code task runs."""

    _id_prefix = "run"


progress_manager = ProgressManager()

__all__ = ["progress_manager", "ProgressManager"]
