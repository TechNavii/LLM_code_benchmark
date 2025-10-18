from __future__ import annotations

import pytest

from server.validators import ValidatedRunRequest


def test_valid_request_passes() -> None:
    request = ValidatedRunRequest(models=["openrouter/gpt"], samples=2)
    assert request.models == ["openrouter/gpt"]
    assert request.samples == 2


def test_model_with_colon_allowed() -> None:
    request = ValidatedRunRequest(models=["anthropic/claude-3.7-sonnet:thinking"], samples=1)
    assert request.models == ["anthropic/claude-3.7-sonnet:thinking"]


def test_invalid_model_name() -> None:
    with pytest.raises(ValueError):
        ValidatedRunRequest(models=["invalid model"], samples=1)


def test_allowlist_enforced() -> None:
    with pytest.raises(ValueError):
        ValidatedRunRequest(models=["model-a"], samples=1, model_allowlist=["model-b"])


def test_provider_allows_slash() -> None:
    request = ValidatedRunRequest(models=["model-a"], samples=1, provider="novita/fp8")
    assert request.provider == "novita/fp8"


def test_provider_invalid_characters() -> None:
    with pytest.raises(ValueError):
        ValidatedRunRequest(models=["model-a"], samples=1, provider="invalid provider")


def test_thinking_level_trimmed() -> None:
    request = ValidatedRunRequest(models=["model-a"], samples=1, thinking_level="  medium  ")
    assert request.thinking_level == "medium"
