from __future__ import annotations

import pytest

from server.routes.qa_router import QARunRequest


def test_qa_provider_allows_slash() -> None:
    request = QARunRequest(models=["model-a"], provider="novita/fp8")
    assert request.provider == "novita/fp8"


def test_qa_provider_invalid_characters() -> None:
    with pytest.raises(ValueError):
        QARunRequest(models=["model-a"], provider="invalid provider")
