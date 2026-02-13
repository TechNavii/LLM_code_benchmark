"""Harness configuration management using Pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parents[1]


class HarnessSettings(BaseSettings):
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "openrouter/google/gemini-pro"
    default_temperature: float = 0.5
    default_max_tokens: int = 200000
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    include_tests_by_default: bool = False
    install_deps_by_default: bool = False
    timeout_seconds: int = 300
    max_log_chars: int = 20000
    # Disabled by default so patch fallbacks are explicit opt-ins.
    allow_incomplete_diffs: bool = False
    allow_diff_rewrite_fallback: bool = False
    tasks_root: Path = ROOT / "tasks"
    runs_root: Path = ROOT / "runs"
    expert_qa_judge_model: str | None = Field(
        default=None,
        validation_alias="EXPERT_QA_JUDGE_MODEL",
    )
    # Retry tuning (can be overridden via env)
    completion_max_retries: int = 12
    completion_retry_backoff_seconds: float = 10.0
    completion_max_backoff_seconds: float = 120.0  # Cap exponential backoff
    qa_completion_max_retries: int = 10
    qa_retry_backoff_seconds: float = 10.0
    # API call timeout (per request, not total retries)
    api_call_timeout_seconds: int = 900  # 15 minutes per API call (local LLMs can be slow)

    model_config = {
        "env_file": ROOT / ".env",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
    }


@lru_cache(maxsize=1)
def get_settings() -> HarnessSettings:
    return HarnessSettings()
