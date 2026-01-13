from __future__ import annotations

import requests
from typing import Any, NoReturn


def test_fetch_model_metadata_handles_request_errors(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None

    def boom(*args: Any, **kwargs: Any) -> NoReturn:
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr(run_harness.requests, "get", boom)
    assert run_harness.fetch_model_metadata(["openrouter/foo"]) == {}


def test_fetch_model_metadata_handles_non_json(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> NoReturn:
            raise ValueError("not json")

    monkeypatch.setattr(run_harness.requests, "get", lambda *a, **k: FakeResponse())
    assert run_harness.fetch_model_metadata(["openrouter/foo"]) == {}


def test_fetch_model_metadata_parses_pricing(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": [
                    {
                        "id": "foo",
                        "pricing": {"prompt": "0.01", "completion": "0.02"},
                        "supported_parameters": ["reasoning"],
                        "default_parameters": {"temperature": 0.0},
                    }
                ]
            }

    monkeypatch.setattr(run_harness.requests, "get", lambda *a, **k: FakeResponse())
    meta = run_harness.fetch_model_metadata(["openrouter/foo"])

    assert meta["foo"]["prompt"] == 0.01
    assert meta["foo"]["completion"] == 0.02
    assert meta["openrouter/foo"]["prompt"] == 0.01
    assert meta["openrouter/foo"]["supported_parameters"] == ["reasoning"]
