from __future__ import annotations

import pytest

from server.validators import ValidatedRunRequest


def test_valid_request_passes() -> None:
    request = ValidatedRunRequest(models=["openrouter/gpt"], samples=2)
    assert request.models == ["openrouter/gpt"]
    assert request.samples == 2


def test_invalid_model_name() -> None:
    with pytest.raises(ValueError):
        ValidatedRunRequest(models=["invalid model"], samples=1)


def test_allowlist_enforced() -> None:
    with pytest.raises(ValueError):
        ValidatedRunRequest(models=["model-a"], samples=1, model_allowlist=["model-b"])
