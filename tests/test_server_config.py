from __future__ import annotations

from server.config import get_settings


def test_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("BENCHMARK_API_TOKEN", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api.host == "127.0.0.1"
    assert settings.api.cors_origins == []
    assert settings.api_token is None


def test_api_token_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_API_TOKEN", "  secret  ")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api_token == "secret"


def test_api_token_blank_becomes_none(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_API_TOKEN", "   ")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api_token is None
