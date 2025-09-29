"""Harness configuration management using Pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parents[1]


class HarnessSettings(BaseSettings):
    openrouter_api_key: str = Field(validation_alias="OPENROUTER_API_KEY")
    default_model: str = "openrouter/google/gemini-pro"
    default_temperature: float = 0.0
    default_max_tokens: int = 32000
    include_tests_by_default: bool = False
    install_deps_by_default: bool = False
    timeout_seconds: int = 300
    max_log_chars: int = 20000
    allow_incomplete_diffs: bool = True
    allow_diff_rewrite_fallback: bool = True
    tasks_root: Path = ROOT / "tasks"
    runs_root: Path = ROOT / "runs"

    model_config = {
        "env_file": ROOT / ".env",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
    }


@lru_cache(maxsize=1)
def get_settings() -> HarnessSettings:
    return HarnessSettings()
