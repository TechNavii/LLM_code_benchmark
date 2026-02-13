from __future__ import annotations


def test_openrouter_reasoning_models_get_higher_token_budget(monkeypatch) -> None:
    from harness.expert_questions import run_benchmark

    assert run_benchmark.requests is not None

    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_api_key", "test-openrouter-api-key")
    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_base_url", "https://example.test/api/v1")
    monkeypatch.setattr(run_benchmark.time, "sleep", lambda *_: None)
    monkeypatch.setattr(run_benchmark, "MAX_QA_COMPLETION_RETRIES", 1)

    seen_payloads: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Bob"},
                    }
                ]
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict, timeout: float):
        seen_payloads.append(dict(json))
        return FakeResponse()

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    text, _meta, _latency = run_benchmark._call_openrouter(
        "prompt",
        model="moonshotai/kimi-k2.5",
        temperature=0.0,
        max_tokens=200000,
        model_supports_reasoning=True,
    )

    assert text == "Bob"
    assert seen_payloads[0]["max_tokens"] == run_benchmark.QA_REASONING_MAX_TOKENS


def test_openrouter_bumps_token_budget_when_reasoning_truncates(monkeypatch) -> None:
    from harness.expert_questions import run_benchmark

    assert run_benchmark.requests is not None

    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_api_key", "test-openrouter-api-key")
    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_base_url", "https://example.test/api/v1")
    monkeypatch.setattr(run_benchmark.time, "sleep", lambda *_: None)
    monkeypatch.setattr(run_benchmark, "MAX_QA_COMPLETION_RETRIES", 2)

    seen_payloads: list[dict] = []

    class FakeResponse:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200
            self.text = ""
            self.headers: dict[str, str] = {}

        def json(self):
            return self._payload

    def fake_post(url: str, *, headers: dict[str, str], json: dict, timeout: float):
        seen_payloads.append(dict(json))
        if len(seen_payloads) == 1:
            return FakeResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"role": "assistant", "content": "", "reasoning": "thinking"},
                        }
                    ]
                }
            )
        return FakeResponse(
            {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Bob"}}]}
        )

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    text, _meta, _latency = run_benchmark._call_openrouter(
        "prompt",
        model="moonshotai/kimi-k2.5",
        temperature=0.0,
        max_tokens=200000,
        model_supports_reasoning=True,
    )

    assert text == "Bob"
    assert seen_payloads[0]["max_tokens"] == run_benchmark.QA_REASONING_MAX_TOKENS
    assert seen_payloads[1]["max_tokens"] == run_benchmark.QA_REASONING_MAX_TOKENS * 2


def test_openrouter_bumps_from_answer_cap_when_reasoning_appears(monkeypatch) -> None:
    from harness.expert_questions import run_benchmark

    assert run_benchmark.requests is not None

    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_api_key", "test-openrouter-api-key")
    monkeypatch.setattr(run_benchmark.SETTINGS, "openrouter_base_url", "https://example.test/api/v1")
    monkeypatch.setattr(run_benchmark.time, "sleep", lambda *_: None)
    monkeypatch.setattr(run_benchmark, "MAX_QA_COMPLETION_RETRIES", 2)

    seen_payloads: list[dict] = []

    class FakeResponse:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200
            self.text = ""
            self.headers: dict[str, str] = {}

        def json(self):
            return self._payload

    def fake_post(url: str, *, headers: dict[str, str], json: dict, timeout: float):
        seen_payloads.append(dict(json))
        if len(seen_payloads) == 1:
            return FakeResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"role": "assistant", "content": "", "reasoning": "thinking"},
                        }
                    ]
                }
            )
        return FakeResponse(
            {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Bob"}}]}
        )

    monkeypatch.setattr(run_benchmark.requests, "post", fake_post)

    text, _meta, _latency = run_benchmark._call_openrouter(
        "prompt",
        model="moonshotai/kimi-k2.5",
        temperature=0.0,
        max_tokens=200000,
        model_supports_reasoning=False,
    )

    assert text == "Bob"
    assert seen_payloads[0]["max_tokens"] == run_benchmark.QA_ANSWER_MAX_TOKENS
    assert seen_payloads[1]["max_tokens"] == run_benchmark.QA_REASONING_MAX_TOKENS
