from __future__ import annotations

from typing import Any

import pytest
import requests


def test_fetch_model_metadata_uses_configured_openrouter_base_url(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None

    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_base_url", "https://example.test/api/v1")
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

    seen: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": []}

    def fake_get(url: str, *, headers: dict[str, str], timeout: int) -> FakeResponse:
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_harness.requests, "get", fake_get)

    assert run_harness.fetch_model_metadata(["openrouter/foo"]) == {}
    assert seen["url"] == "https://example.test/api/v1/models"
    assert seen["headers"]["Authorization"].startswith("Bearer ")


def test_fetch_model_metadata_skips_when_only_lmstudio_models(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None

    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", None)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("requests.get should not be called")

    monkeypatch.setattr(run_harness.requests, "get", boom)
    assert run_harness.fetch_model_metadata(["lmstudio/foo"]) == {}


def test_call_openrouter_uses_configured_openrouter_base_url(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None

    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_base_url", "https://example.test/api/v1")
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

    seen: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> FakeResponse:
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_harness.requests, "post", fake_post)

    run_harness.call_openrouter(prompt="hi", model="openrouter/foo", temperature=0.0, max_tokens=16)
    assert seen["url"] == "https://example.test/api/v1/chat/completions"
    assert seen["headers"]["Authorization"].startswith("Bearer ")


def test_call_openrouter_requires_api_key(monkeypatch) -> None:
    from harness import run_harness

    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", None)

    with pytest.raises(run_harness.HarnessError, match="OPENROUTER_API_KEY"):
        run_harness.call_openrouter(prompt="hi", model="openrouter/foo", temperature=0.0, max_tokens=16)


def test_server_settings_do_not_require_openrouter_api_key(monkeypatch) -> None:
    from server.config import get_settings

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api.host == "127.0.0.1"


def test_fetch_model_metadata_handles_request_errors(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

    def boom(*args: Any, **kwargs: Any) -> None:
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr(run_harness.requests, "get", boom)
    assert run_harness.fetch_model_metadata(["openrouter/foo"]) == {}


def test_fetch_model_metadata_handles_non_json(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            raise ValueError("not json")

    monkeypatch.setattr(run_harness.requests, "get", lambda *a, **k: FakeResponse())
    assert run_harness.fetch_model_metadata(["openrouter/foo"]) == {}


def test_fetch_model_metadata_parses_pricing(monkeypatch) -> None:
    from harness import run_harness

    assert run_harness.requests is not None
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

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
    assert meta["foo"]["supported_parameters"] == ["reasoning"]


def test_server_settings_defaults(monkeypatch) -> None:
    from server.config import get_settings

    monkeypatch.delenv("BENCHMARK_API_TOKEN", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api.host == "127.0.0.1"
    assert settings.api.cors_origins == []
    assert settings.api_token is None


def test_server_api_token_trimmed(monkeypatch) -> None:
    from server.config import get_settings

    monkeypatch.setenv("BENCHMARK_API_TOKEN", "  secret  ")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api_token == "secret"


def test_server_api_token_blank_becomes_none(monkeypatch) -> None:
    from server.config import get_settings

    monkeypatch.setenv("BENCHMARK_API_TOKEN", "   ")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.api_token is None


# =============================================================================
# LM Studio Base URL Configuration Tests
# =============================================================================


def test_server_lmstudio_base_url_configurable_via_env(monkeypatch) -> None:
    """LM Studio base URL should be configurable via LMSTUDIO_BASE_URL env var."""
    from server.config import get_settings

    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://custom-lmstudio:5678/v1")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.lmstudio_base_url == "http://custom-lmstudio:5678/v1"


def test_server_lmstudio_base_url_default(monkeypatch) -> None:
    """LM Studio base URL should default to localhost when not configured."""
    from server.config import get_settings

    monkeypatch.delenv("LMSTUDIO_BASE_URL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.lmstudio_base_url == "http://127.0.0.1:1234/v1"


def test_harness_lmstudio_base_url_configurable_via_env(monkeypatch) -> None:
    """Harness LM Studio base URL should be configurable via LMSTUDIO_BASE_URL env var."""
    from harness.config import get_settings

    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://custom-lmstudio:9999/v1")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.lmstudio_base_url == "http://custom-lmstudio:9999/v1"


def test_harness_openrouter_base_url_configurable_via_env(monkeypatch) -> None:
    """Harness OpenRouter base URL should be configurable via OPENROUTER_BASE_URL env var."""
    from harness.config import get_settings

    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://custom-openrouter.test/api/v1")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.openrouter_base_url == "https://custom-openrouter.test/api/v1"


def test_harness_openrouter_base_url_default(monkeypatch) -> None:
    """Harness OpenRouter base URL should default to openrouter.ai when not configured."""
    from harness.config import get_settings

    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"


def test_list_lmstudio_models_uses_configured_base_url(monkeypatch) -> None:
    """list_lmstudio_models endpoint should use configured LM Studio base URL."""
    import sys
    from unittest.mock import MagicMock, patch
    from urllib.error import URLError
    from urllib.request import Request

    from fastapi.testclient import TestClient

    from server.api import create_app
    from server.config import get_settings

    get_settings.cache_clear()

    # Get the router module (not the router object) via sys.modules
    router_module = sys.modules["server.routes.router"]

    # Create a mock settings object with the custom base URL
    mock_settings = MagicMock()
    mock_settings.lmstudio_base_url = "http://custom-lmstudio:7777/v1"
    monkeypatch.setattr(router_module, "settings", mock_settings)

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    seen_urls: list[str] = []

    def mock_urlopen(req: Request, *, timeout: int = 3) -> None:  # noqa: ARG001
        seen_urls.append(req.full_url)
        raise URLError("mocked - connection refused")

    with patch("server.routes.router.urlopen", mock_urlopen):
        response = client.get("/models/lmstudio")

    # Endpoint should fail (LM Studio not running) but should have tried the configured URL
    assert response.status_code == 503

    # Verify the configured URL was used, not the default
    assert any("custom-lmstudio:7777" in url for url in seen_urls)
    # Should not have used default localhost
    assert not any("127.0.0.1:1234" in url for url in seen_urls)


def test_lmstudio_endpoint_fails_when_base_url_empty(monkeypatch) -> None:
    """LM Studio endpoint should return 500 when base URL is empty."""
    import sys
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from server.api import create_app
    from server.config import get_settings

    get_settings.cache_clear()

    # Get the router module (not the router object) via sys.modules
    router_module = sys.modules["server.routes.router"]

    # Create a mock settings object with empty base URL
    mock_settings = MagicMock()
    mock_settings.lmstudio_base_url = ""
    monkeypatch.setattr(router_module, "settings", mock_settings)

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/models/lmstudio")
    assert response.status_code == 500
    assert "not configured" in response.json()["detail"]


def test_switch_lmstudio_model_invokes_lms_cli(monkeypatch) -> None:
    import sys
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from server.api import create_app
    from server.config import get_settings

    get_settings.cache_clear()

    router_module = sys.modules["server.routes.router"]

    mock_settings = MagicMock()
    mock_settings.lmstudio_base_url = "http://custom-lmstudio:7777/v1"
    monkeypatch.setattr(router_module, "settings", mock_settings)

    monkeypatch.setattr(router_module, "_resolve_lms_path", lambda: "/fake/lms")

    calls: list[list[str]] = []

    class FakeResult:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def fake_run(args: list[str], *, capture_output: bool, text: bool, timeout: int) -> FakeResult:
        assert capture_output is True
        assert text is True
        assert timeout > 0
        calls.append(args)
        return FakeResult()

    monkeypatch.setattr(router_module.subprocess, "run", fake_run)

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/models/lmstudio/switch",
        json={"model_id": "liquid/lfm2.5-1.2b"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_id"] == "liquid/lfm2.5-1.2b"

    assert calls == [
        [
            "/fake/lms",
            "unload",
            "--all",
            "--host",
            "custom-lmstudio",
            "--port",
            "7777",
        ],
        [
            "/fake/lms",
            "load",
            "liquid/lfm2.5-1.2b",
            "--exact",
            "-y",
            "--host",
            "custom-lmstudio",
            "--port",
            "7777",
        ],
    ]


def test_switch_lmstudio_model_rejects_invalid_model_id(monkeypatch) -> None:
    import sys
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from server.api import create_app
    from server.config import get_settings

    get_settings.cache_clear()

    router_module = sys.modules["server.routes.router"]

    mock_settings = MagicMock()
    mock_settings.lmstudio_base_url = "http://custom-lmstudio:7777/v1"
    monkeypatch.setattr(router_module, "settings", mock_settings)

    monkeypatch.setattr(router_module, "_resolve_lms_path", lambda: "/fake/lms")

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/models/lmstudio/switch",
        json={"model_id": "bad model"},
    )

    assert response.status_code == 400
    assert "Invalid" in response.json()["detail"]


# =============================================================================
# Expert Questions LM Studio URL Configuration Tests
# =============================================================================


def test_expert_questions_lmstudio_call_uses_configured_base_url(monkeypatch) -> None:
    """Expert questions LM Studio calls should use configured base URL."""
    from harness.expert_questions import run_benchmark

    monkeypatch.setattr(run_benchmark.SETTINGS, "lmstudio_base_url", "http://custom-expert:8888/v1")

    seen: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": "test answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> FakeResponse:
        seen["url"] = url
        return FakeResponse()

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    # Use the private function _call_lmstudio
    result = run_benchmark._call_lmstudio(
        prompt="test",
        model="lmstudio/test-model",
        temperature=0.5,
        max_tokens=100,
    )

    assert "custom-expert:8888" in seen["url"]
    assert result[0] == "test answer"


def test_expert_questions_lmstudio_allows_not_loaded_state(monkeypatch) -> None:
    """LM Studio models should be callable even when the native API reports them as not-loaded."""
    from harness.expert_questions import run_benchmark

    assert run_benchmark.requests is not None

    run_benchmark._LMSTUDIO_VALIDATED_MODELS.clear()

    monkeypatch.setattr(run_benchmark.SETTINGS, "lmstudio_base_url", "http://custom-expert:8888/v1")
    monkeypatch.setattr(
        run_benchmark,
        "_lmstudio_get_models",
        lambda: [{"id": "liquid/lfm2.5-1.2b", "state": "not-loaded"}],
    )

    seen: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {
                "model": "liquid/lfm2.5-1.2b",
                "choices": [{"message": {"content": "test answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> FakeResponse:
        seen["url"] = url
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    content, _, _ = run_benchmark._call_completion(
        "test",
        model="lmstudio/liquid/lfm2.5-1.2b",
        temperature=0.5,
        max_tokens=100,
    )

    assert "custom-expert:8888" in seen["url"]
    assert seen["json"]["model"] == "liquid/lfm2.5-1.2b"
    assert content == "test answer"


def test_expert_questions_openrouter_call_uses_configured_base_url(monkeypatch) -> None:
    """Expert questions OpenRouter calls should use configured base URL."""
    from harness.expert_questions import run_benchmark

    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_base_url", "https://custom-router.test/api/v1")
    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

    seen: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": "test answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> FakeResponse:
        seen["url"] = url
        return FakeResponse()

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    # Use the private function _call_openrouter
    result = run_benchmark._call_openrouter(
        prompt="test",
        model="openrouter/test-model",
        temperature=0.5,
        max_tokens=100,
    )

    assert "custom-router.test" in seen["url"]
    assert result[0] == "test answer"


def test_expert_questions_judge_uses_configured_base_url(monkeypatch) -> None:
    """Expert questions judge model calls should use configured OpenRouter base URL."""
    from harness.expert_questions import run_benchmark

    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_base_url", "https://judge-router.test/api/v1")
    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")
    monkeypatch.setattr(run_benchmark.SETTINGS, "expert_qa_judge_model", "openai/gpt-4")

    seen: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": "PASS"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> FakeResponse:
        seen["url"] = url
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    # Use the private function _judge_answer with correct parameter names
    result = run_benchmark._judge_answer(
        question_text="What is 2+2?",
        expected="4",
        observed="4",
    )

    assert "judge-router.test" in seen["url"]
    # Result is a tuple: (is_pass, decision, error, usage, reasoning_content, latency)
    assert result[0] is True  # is_pass


# =============================================================================
# No Silent Fallback Tests
# =============================================================================


def test_no_fallback_to_default_openrouter_url(monkeypatch) -> None:
    """OpenRouter calls should never silently fall back to default URL when configured."""
    from harness import run_harness

    # Set a custom URL
    custom_url = "https://never-fallback.test/api/v1"
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_base_url", custom_url)
    monkeypatch.setattr(run_harness.SETTINGS, "openrouter_api_key", "test-openrouter-api-key-1234567890")

    all_urls: list[str] = []

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "data": [],
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    def capture_url(url: str, **kwargs: Any) -> FakeResponse:
        all_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(run_harness.requests, "post", capture_url)
    monkeypatch.setattr(run_harness.requests, "get", capture_url)

    # Make API calls
    run_harness.call_openrouter(prompt="hi", model="openrouter/foo", temperature=0.0, max_tokens=16)
    run_harness.fetch_model_metadata(["openrouter/bar"])

    # Verify all URLs used the custom URL, never the default
    default_url = "https://openrouter.ai/api/v1"
    for url in all_urls:
        assert default_url not in url, f"Found default URL in: {url}"
        assert "never-fallback.test" in url, f"Custom URL not used in: {url}"


def test_no_fallback_to_default_lmstudio_url(monkeypatch) -> None:
    """LM Studio calls should never silently fall back to default URL when configured."""
    import sys
    from unittest.mock import MagicMock, patch
    from urllib.request import Request

    from fastapi.testclient import TestClient

    from server.api import create_app
    from server.config import get_settings

    get_settings.cache_clear()

    custom_url = "http://never-fallback-lmstudio:9999/v1"

    # Get the router module (not the router object) via sys.modules
    router_module = sys.modules["server.routes.router"]

    # Create a mock settings object with the custom base URL
    mock_settings = MagicMock()
    mock_settings.lmstudio_base_url = custom_url
    monkeypatch.setattr(router_module, "settings", mock_settings)

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    all_urls: list[str] = []

    def capture_urlopen(req: Request, *, timeout: int = 3) -> Any:  # noqa: ARG001
        all_urls.append(req.full_url)
        # Return valid JSON response
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"data": []}'
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = lambda s, *args: None
        return mock_response

    with patch("server.routes.router.urlopen", capture_urlopen):
        client.get("/models/lmstudio")

    # Verify all URLs used the custom URL, never the default
    default_url = "127.0.0.1:1234"
    for url in all_urls:
        assert default_url not in url, f"Found default URL in: {url}"
        assert "never-fallback-lmstudio:9999" in url, f"Custom URL not used in: {url}"
