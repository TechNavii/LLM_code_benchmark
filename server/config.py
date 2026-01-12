"""Configuration management for the benchmark server."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parents[1]


class DatabaseSettings(BaseSettings):
    url: str = Field(default=f"sqlite:///{ROOT / 'runs' / 'history.db'}")
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False


class APISettings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    cors_origins: list[str] = Field(default_factory=list)


class HarnessSettings(BaseSettings):
    max_concurrent_tasks: int = 5
    default_timeout: int = 300
    max_log_chars: int = 20000
    supported_languages: list[str] = Field(default_factory=lambda: ["python", "javascript", "go", "rust", "cpp"])


class Settings(BaseSettings):
    """Top-level configuration values for the server and harness."""

    api_token: str | None = Field(default=None, validation_alias="BENCHMARK_API_TOKEN")
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: APISettings = Field(default_factory=APISettings)
    harness: HarnessSettings = Field(default_factory=HarnessSettings)

    tasks_root: Path = ROOT / "tasks"
    runs_root: Path = ROOT / "runs"

    model_allowlist: list[str] = Field(default_factory=list)

    cors_origins: list[str] | None = None

    @field_validator("api_token")
    @classmethod
    def normalize_api_token(cls, token: str | None) -> str | None:
        if token is None:
            return None
        trimmed = token.strip()
        return trimmed or None

    @field_validator("cors_origins")
    @classmethod
    def ensure_cors_origins(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if any(origin.strip() == "" for origin in value):
            raise ValueError("CORS origins must not contain empty entries")
        return value

    model_config = {
        "env_file": ROOT / ".env",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
        "extra": "ignore",
        "protected_namespaces": ("settings_",),
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
