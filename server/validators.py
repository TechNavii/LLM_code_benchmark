"""Input validation models for the benchmark API."""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9_\-/]+$")
TASK_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


class ValidatedRunRequest(BaseModel):
    models: List[str] = Field(..., min_length=1)
    tasks: Optional[List[str]] = Field(default=None)
    samples: int = Field(default=1, ge=1, le=10)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, ge=1, le=8000)
    include_tests: bool = False
    install_deps: bool = False
    response_text: Optional[str] = None

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

    @model_validator(mode="after")
    def enforce_allowlist(self) -> "ValidatedRunRequest":
        if self.model_allowlist:
            disallowed = sorted(set(self.models) - set(self.model_allowlist))
            if disallowed:
                raise ValueError(f"Models not allowed: {', '.join(disallowed)}")
        return self
