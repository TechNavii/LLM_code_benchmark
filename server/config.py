"""Configuration management for the benchmark server."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parents[1]


class DatabaseSettings(BaseSettings):
    url: str = Field(default=f"sqlite:///{ROOT / 'runs' / 'history.db'}")
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False


class APISettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])


class HarnessSettings(BaseSettings):
    max_concurrent_tasks: int = 5
    default_timeout: int = 300
    max_log_chars: int = 20000
    supported_languages: List[str] = Field(
        default_factory=lambda: ["python", "javascript", "go", "rust", "cpp"]
    )


class Settings(BaseSettings):
    """Top-level configuration values for the server and harness."""

    openrouter_api_key: str = Field(validation_alias="OPENROUTER_API_KEY")
    default_model: str = "openrouter/google/gemini-pro"
    default_temperature: float = 0.0

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: APISettings = Field(default_factory=APISettings)
    harness: HarnessSettings = Field(default_factory=HarnessSettings)

    tasks_root: Path = ROOT / "tasks"
    runs_root: Path = ROOT / "runs"

    model_allowlist: List[str] = Field(default_factory=list)

    cors_origins: List[str] | None = None

    @field_validator("openrouter_api_key")
    @classmethod
    def validate_api_key(cls, api_key: str) -> str:
        if not api_key or len(api_key) < 10:
            raise ValueError("OPENROUTER_API_KEY must be provided and appear valid")
        return api_key

    @field_validator("cors_origins")
    @classmethod
    def ensure_cors_origins(cls, value: List[str] | None) -> List[str] | None:
        if value is None:
            return value
        if any(origin.strip() == "" for origin in value):
            raise ValueError("CORS origins must not contain empty entries")
        return value

    model_config = {
        "env_file": ROOT / ".env",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
        "protected_namespaces": ("settings_",),
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
