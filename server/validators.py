"""Input validation models for the benchmark API."""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from harness.config import get_settings

_HARNESS_SETTINGS = get_settings()
_DEFAULT_ALLOW_INCOMPLETE_DIFFS = _HARNESS_SETTINGS.allow_incomplete_diffs
_DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK = _HARNESS_SETTINGS.allow_diff_rewrite_fallback
_DEFAULT_MAX_TOKENS = _HARNESS_SETTINGS.default_max_tokens
_DEFAULT_TEMPERATURE = _HARNESS_SETTINGS.default_temperature


MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9_\-/\.:]+$")
TASK_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


class ValidatedRunRequest(BaseModel):
    models: List[str] = Field(..., min_length=1)
    tasks: Optional[List[str]] = Field(default=None)
    samples: int = Field(default=1, ge=1, le=10)
    temperature: float = Field(default=_DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    max_tokens: int = Field(default=_DEFAULT_MAX_TOKENS, ge=1, le=200_000)
    provider: Optional[str] = Field(default=None, max_length=64)
    include_tests: bool = False
    install_deps: bool = False
    allow_incomplete_diffs: bool = Field(default=_DEFAULT_ALLOW_INCOMPLETE_DIFFS)
    allow_diff_rewrite_fallback: bool = Field(default=_DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK)
    response_text: Optional[str] = None
    thinking_level: Optional[str] = Field(default=None, max_length=64)
    include_thinking_variants: bool = False
    sweep_thinking_levels: bool = False

    model_allowlist: Optional[List[str]] = None

    @field_validator("models", mode="after")
    @classmethod
    def validate_models(cls, models: List[str]) -> List[str]:
        for model in models:
            if not MODEL_PATTERN.match(model):
                raise ValueError(f"Invalid model name format: {model}")
        return models

    @field_validator("tasks", mode="after")
    @classmethod
    def validate_tasks(cls, tasks: Optional[List[str]]) -> Optional[List[str]]:
        if tasks is None:
            return tasks
        for task in tasks:
            if not TASK_PATTERN.match(task):
                raise ValueError(f"Invalid task identifier: {task}")
        return tasks

    @field_validator("provider", mode="after")
    @classmethod
    def validate_provider(cls, provider: Optional[str]) -> Optional[str]:
        if provider is None:
            return None
        trimmed = provider.strip()
        if not trimmed:
            return None
        if not re.match(r"^[A-Za-z0-9._\-/]+$", trimmed):
            raise ValueError(
                "Provider must be alphanumeric with optional hyphen/underscore characters (dots and slashes allowed)"
            )
        return trimmed

    @field_validator("thinking_level", mode="after")
    @classmethod
    def validate_thinking_level(cls, level: Optional[str]) -> Optional[str]:
        if level is None:
            return None
        trimmed = level.strip()
        if not trimmed:
            return None
        if any(ord(ch) < 32 for ch in trimmed):
            raise ValueError("Thinking level must not contain control characters.")
        return trimmed

    @model_validator(mode="after")
    def enforce_allowlist(self) -> "ValidatedRunRequest":
        if self.model_allowlist:
            disallowed = sorted(set(self.models) - set(self.model_allowlist))
            if disallowed:
                raise ValueError(f"Models not allowed: {', '.join(disallowed)}")
        return self
