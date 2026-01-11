"""Dedicated progress manager for the expert question benchmark."""

from __future__ import annotations

from server.progress_base import BaseProgressManager


class ProgressManager(BaseProgressManager):
    """Progress manager for QA benchmark runs."""

    _id_prefix = "qa"


qa_progress_manager = ProgressManager()

__all__ = ["qa_progress_manager", "ProgressManager"]
