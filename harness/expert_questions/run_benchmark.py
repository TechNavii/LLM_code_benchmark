"""Execution harness for the expert question benchmark."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency for offline runs
    requests = None

try:
    import structlog  # type: ignore
    LOGGER = structlog.get_logger(__name__)
except Exception:  # pragma: no cover - fallback when structlog is unavailable
    class _DummyLogger:
        def info(self, *args, **kwargs):
            pass
        def warning(self, *args, **kwargs):
            pass
        def exception(self, *args, **kwargs):
            pass
    class _DummyStructlog:
        @staticmethod
        def get_logger(name=None):
            return _DummyLogger()
    structlog = _DummyStructlog()  # type: ignore
    LOGGER = structlog.get_logger(__name__)

from harness.config import get_settings
from harness.exceptions import HarnessError
from harness.run_harness import (
    expand_models_with_thinking_variants,
    fetch_model_pricing,
    store_text,
)
from harness.expert_questions.dataset import Question, load_questions

SETTINGS = get_settings()
QA_RUNS_ROOT = SETTINGS.runs_root / "qa_runs"
JUDGE_MODEL = SETTINGS.expert_qa_judge_model
JUDGE_MAX_TOKENS = 256
# Retry strategy for QA completions (configurable via settings)
MAX_QA_COMPLETION_RETRIES = SETTINGS.qa_completion_max_retries
QA_RETRY_BACKOFF_SECONDS = SETTINGS.qa_retry_backoff_seconds
 # LOGGER already defined above via structlog or fallback


def _compose_reasoning_payload(level: str) -> Dict[str, Any]:
    value = (level or "").strip()
    if not value:
        return {}

    if "=" in value:
        key, raw = value.split("=", 1)
        key = key.strip().lower()
        raw_value = raw.strip()
        if key in {"budget_tokens", "tokens"}:
            try:
                return {"budget_tokens": int(raw_value)}
            except ValueError:
                pass
        if key in {"budget_seconds", "seconds"}:
            try:
                return {"budget_seconds": int(raw_value)}
            except ValueError:
                pass

    return {"effort": value}


def _call_openrouter(
    prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    preferred_provider: Optional[str] = None,
    reasoning_payload: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any], float]:
    if requests is None:
        raise HarnessError("The 'requests' library is required to call OpenRouter.")

    api_key = SETTINGS.openrouter_api_key
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "benchmark-harness-expert-qa",
        "X-Title": "benchmark-harness",
        "Content-Type": "application/json",
    }

    def wrap_content(text: str) -> List[Dict[str, str]]:
        return [{"type": "text", "text": text}]

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": wrap_content(
                    "You answer evaluation questions with exactly one word or one number. "
                    "Do not add any additional text, punctuation, or explanation."
                ),
            },
            {"role": "user", "content": wrap_content(prompt)},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if preferred_provider:
        payload["provider"] = {
            "order": [preferred_provider],
        }
    if reasoning_payload is not None:
        payload["reasoning"] = reasoning_payload

    last_error: Optional[Exception] = None
    backoff = QA_RETRY_BACKOFF_SECONDS

    for attempt in range(MAX_QA_COMPLETION_RETRIES):
        start = time.perf_counter()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.RequestException as exc:
            last_error = RuntimeError(f"Judge request failed: {exc}")
            should_retry = True
        else:
            if response.status_code >= 500:
                err_text = response.text.strip()
                last_error = RuntimeError(f"Judge request failed ({response.status_code}): {err_text}")
                should_retry = True
            elif response.status_code >= 400:
                error_message = response.text.strip()
                try:
                    error_payload = response.json()
                except ValueError:
                    error_payload = None
                if isinstance(error_payload, dict):
                    error_message = (
                        error_payload.get("error", {}).get("message")
                        or error_payload.get("message")
                        or error_payload.get("detail")
                        or error_message
                    )
                # Treat 429 (rate limit) as a transient error that can be retried
                if response.status_code == 429:
                    last_error = RuntimeError(f"Request failed ({response.status_code}): {error_message}")
                    should_retry = True
                else:
                    # Other 4xx: do not retry
                    raise RuntimeError(
                        f"Judge request failed ({response.status_code}): {error_message}"
                    )
            else:
                try:
                    data = response.json()
                except ValueError:
                    last_error = RuntimeError("Judge returned non-JSON response")
                    should_retry = True
                else:
                    # Handle nested provider error inside choices even when HTTP status is 200
                    try:
                        choices = data.get("choices")
                    except AttributeError:
                        choices = None

                    if not choices:
                        # Check for top-level error field
                        top_error = data.get("error") if isinstance(data, dict) else None
                        if isinstance(top_error, dict):
                            code = top_error.get("code")
                            message = str(top_error.get("message") or "")
                            is_transient = False
                            try:
                                code_int = int(code) if code is not None else None
                                is_transient = code_int is not None and (code_int >= 500 or code_int == 429)
                            except (TypeError, ValueError):
                                is_transient = False
                            lowered = message.lower()
                            if any(k in lowered for k in ("network", "upstream", "temporar", "timeout", "try again", "rate limit", "too many")):
                                is_transient = True
                            last_error = HarnessError(f"Provider error ({code}): {message or 'unknown error'}")
                            should_retry = is_transient
                        else:
                            last_error = HarnessError(f"Unexpected OpenRouter response payload: {data}")
                            should_retry = True
                    else:
                        first = choices[0] if choices else {}
                        choice_error = (first or {}).get("error")
                        content = (first or {}).get("message", {}).get("content", "")

                        if isinstance(choice_error, dict):
                            code = choice_error.get("code")
                            message = str(choice_error.get("message") or "")
                            # Treat 5xx, 429 (rate limit), or network/upstream issues as transient
                            is_transient = False
                            try:
                                code_int = int(code) if code is not None else None
                                is_transient = code_int is not None and (code_int >= 500 or code_int == 429)
                            except (TypeError, ValueError):
                                is_transient = False
                            lowered = message.lower()
                            if any(k in lowered for k in ("network", "upstream", "temporar", "timeout", "try again", "rate limit", "too many")):
                                is_transient = True

                            last_error = RuntimeError(
                                f"Provider error ({code}): {message or 'unknown error'}"
                            )
                            should_retry = is_transient
                        else:
                            cleaned = (content or "").strip()
                            if cleaned:
                                latency = time.perf_counter() - start
                                return cleaned, data, latency
                            last_error = RuntimeError("Judge returned empty content")
                            should_retry = True

        if attempt < MAX_QA_COMPLETION_RETRIES - 1 and should_retry:
            time.sleep(backoff)
            backoff *= 2
            continue
        break

    assert last_error is not None
    raise last_error


def _judge_answer(
    question_text: str,
    expected: str,
    observed: str,
    *,
    model: str = JUDGE_MODEL,
    max_tokens: int = JUDGE_MAX_TOKENS,
) -> Tuple[bool, Optional[str], Optional[str], Optional[Dict[str, Any]], Optional[str], Optional[float]]:
    """Ask an auxiliary model to determine if two answers are equivalent."""

    if requests is None:
        return False, None, "requests library unavailable", None, None, None

    api_key = SETTINGS.openrouter_api_key
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "benchmark-harness-expert-qa",
        "X-Title": "benchmark-harness",
        "Content-Type": "application/json",
    }

    def wrap_content(text: str) -> List[Dict[str, str]]:
        return [{"type": "text", "text": text}]

    system_prompt = (
        "You are an impartial judge. Compare an expected answer with a model's answer. "
        "Return JSON with keys 'decision' (PASS or FAIL) and 'reason'. PASS only when the "
        "two answers mean the same thing, accounting for formatting or synonymous wording."
    )
    user_prompt = (
        "Question: {question}\n"
        "Expected answer: {expected}\n"
        "Model answer: {observed}\n"
        "Reply with PASS if the answers convey the same meaning (allowing for formatting, capitalization, or equivalent synonyms). Otherwise reply FAIL."
    ).format(question=question_text, expected=expected, observed=observed)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": wrap_content(system_prompt)},
            {"role": "user", "content": wrap_content(user_prompt)},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }

    max_attempts = MAX_QA_COMPLETION_RETRIES
    total_latency = 0.0
    last_usage: Optional[Dict[str, Any]] = None
    last_raw: Optional[str] = None
    failure_reason: Optional[str] = None
    backoff = QA_RETRY_BACKOFF_SECONDS

    for attempt_index in range(1, max_attempts + 1):
        start = time.perf_counter()
        should_retry = False
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.RequestException as exc:
            failure_reason = f"Judge request failed: {exc}"
            should_retry = True
            latency = time.perf_counter() - start
            total_latency += latency
        else:
            latency = time.perf_counter() - start
            total_latency += latency
            status = response.status_code
            if status >= 500 or status == 429:
                # Transient error - retry
                failure_reason = f"Judge request failed ({status}): {response.text.strip()}"
                should_retry = True
            elif status >= 400:
                # Non-transient 4xx error - don't retry
                return (
                    False,
                    "FAIL",
                    f"Judge request failed ({status}): {response.text.strip()}",
                    None,
                    None,
                    total_latency,
                )
            else:
                try:
                    data = response.json()
                except ValueError:
                    failure_reason = "Judge returned non-JSON response"
                    should_retry = True
                else:
                    last_usage = data.get("usage")
                    try:
                        text = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError):
                        raw_text = ""
                        failure_reason = "Judge response missing content"
                    else:
                        raw_text = (text or "").strip()
                        if not raw_text:
                            failure_reason = "Judge returned empty content"
                        else:
                            last_raw = raw_text

        if last_raw:
            break

        if attempt_index < max_attempts and should_retry:
            time.sleep(backoff)
            backoff *= 2
            continue

        if attempt_index >= max_attempts:
            final_reason = failure_reason or "Judge returned empty content"
            return (
                False,
                "FAIL",
                f"{final_reason} after {max_attempts} attempts",
                last_usage,
                last_raw,
                total_latency,
            )

    raw_text = (last_raw or "").strip()

    def _attempt_parse(payload: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    parsed = _attempt_parse(raw_text)
    if parsed is None and raw_text.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*", "", raw_text)
        stripped = stripped.rstrip("`").strip()
        parsed = _attempt_parse(stripped)

    decision_label: Optional[str] = None
    rationale: Optional[str] = None

    if isinstance(parsed, dict):
        decision_label = str(parsed.get("decision", "")).strip().upper()
        rationale = parsed.get("reason") or parsed.get("rationale")
    else:
        candidate = raw_text.splitlines()[0].strip().upper()
        if candidate.startswith("PASS"):
            decision_label = "PASS"
        elif candidate.startswith("FAIL"):
            decision_label = "FAIL"
        rationale = raw_text

    is_pass = decision_label == "PASS"
    return is_pass, decision_label, rationale, last_usage, raw_text, total_latency


def _normalise_answer(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("\u2019", "'")
    cleaned = cleaned.replace("\u2018", "'")
    cleaned = cleaned.replace("\u201c", '"')
    cleaned = cleaned.replace("\u201d", '"')
    cleaned = cleaned.replace("\u2013", "-")
    cleaned = cleaned.replace("\u2014", "-")
    cleaned = cleaned.strip(" .,:;!?")
    cleaned = re.sub(r"\s+([°%])", r"\1", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned


def _extract_single_line_answer(raw: str) -> str:
    """Extract a single-line final answer from a raw model response.

    Many providers prepend hidden or visible chain-of-thought blocks such as
    <think>...</think>, <reasoning>...</reasoning>, or fenced blocks like
    ```think ...```. We strip those and then take the last non-empty line.

    Fallback: if nothing remains after stripping, return the first non-empty
    line of the original content.
    """
    text = raw or ""
    # Remove tagged reasoning blocks like <think>...</think>, <reasoning>...</reasoning>
    text = re.sub(r"(?is)<(think|reasoning|deliberate|chain)>.*?</\1>", "", text)
    # Remove bracket-tag variants like [think]...[/think]
    text = re.sub(r"(?is)\[(think|reasoning|deliberate|chain)\].*?\[/\1\]", "", text)
    # Remove fenced reasoning blocks like ```think ... ``` or ```reasoning ... ```
    text = re.sub(r"(?is)```\s*(think|reasoning|deliberate)[\s\S]*?```", "", text)

    # Now select the last non-empty line as the answer.
    lines = [ln.strip() for ln in (text.strip().splitlines() if text else [])]
    non_empty = [ln for ln in lines if ln]
    if non_empty:
        return non_empty[-1]

    # Fallback to the first non-empty line from the original content.
    orig_lines = [ln.strip() for ln in (raw.strip().splitlines() if raw else [])]
    for ln in orig_lines:
        if ln:
            return ln
    return ""


def _build_prompt(question: Question) -> str:
    return (
        "Answer the following benchmark question with a single word or number.\n"
        "Question: "
        f"{question.prompt}\n"
        "Respond with only that single word or number—no other text."  # noqa: E501
    )


def _prepare_run_directory(run_id: str, base_output: Path) -> Path:
    run_dir = base_output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


AttemptSummary = Dict[str, Any]
ProgressCallback = Callable[[str, int, int, AttemptSummary], None]


def run_question_benchmark(
    *,
    models: Iterable[str],
    samples: int = 1,
    temperature: float = 0.5,
    max_tokens: int = 200000,
    provider: Optional[str] = None,
    thinking_level: Optional[str] = None,
    include_thinking_variants: bool = False,
    sweep_thinking_levels: bool = False,
    question_limit: Optional[int] = None,
    run_id: str,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    questions = load_questions()
    if question_limit is not None:
        try:
            limit = int(question_limit)
        except (TypeError, ValueError):
            limit = None
        if limit is not None and limit > 0:
            questions = questions[:limit]
    model_list = [model.strip() for model in models if model.strip()]
    if not model_list:
        raise HarnessError("At least one model must be provided.")
    model_list = list(dict.fromkeys(model_list))
    requested_models = list(model_list)

    thinking_level = (thinking_level or "").strip() or None

    if include_thinking_variants:
        metadata_snapshot = fetch_model_pricing(model_list)
        model_list = expand_models_with_thinking_variants(model_list, metadata_snapshot)
        model_list = list(dict.fromkeys(model_list))

    samples = max(1, int(samples))
    temperature = float(temperature)
    max_tokens = int(max_tokens)

    if JUDGE_MODEL and requests is None:
        raise HarnessError("Judge model configured but requests library unavailable; aborting to avoid unjudged scores")

    judge_enabled = bool(JUDGE_MODEL) and requests is not None
    judge_status_reason = None
    pricing_models = list(dict.fromkeys(model_list + ([JUDGE_MODEL] if judge_enabled else [])))
    model_metadata = fetch_model_pricing(pricing_models)
    if judge_enabled and JUDGE_MODEL not in model_metadata:
        judge_status_reason = "pricing_unavailable"
        raise HarnessError(f"Judge model pricing unavailable for {JUDGE_MODEL}; aborting to avoid unjudged scores")
    if judge_enabled and requests is None:
        judge_status_reason = "requests_unavailable"
        raise HarnessError("requests library unavailable; cannot use judge model safely")

    base_output = Path(output_dir) if output_dir else QA_RUNS_ROOT
    base_output.mkdir(parents=True, exist_ok=True)
    run_dir = _prepare_run_directory(run_id, base_output)
    timestamp = dt.datetime.now(dt.timezone.utc)

    attempts: List[AttemptSummary] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0
    total_latency = 0.0
    total_duration = 0.0

    question_map = {question.number: question for question in questions}

    def _suggest_levels_for_model(model_id: str) -> List[str]:
        info = model_metadata.get(model_id) or {}
        params = {str(p).lower() for p in (info.get("supported_parameters") or []) if isinstance(p, str)}
        if "reasoning" not in params:
            return []
        return ["low", "medium", "high"]

    def _estimate_pass_at_k(total: int, correct: int, k: int) -> Optional[float]:
        if total <= 0 or k <= 0:
            return None
        k = min(k, total)
        if correct <= 0:
            return 0.0
        if correct >= total:
            return 1.0
        return 1.0 - math.comb(total - correct, k) / math.comb(total, k)

    for model in model_list:
        model_info = model_metadata.get(model) or {}
        supported_params = {
            param.lower()
            for param in model_info.get("supported_parameters", [])
            if isinstance(param, str)
        }
        model_supports_reasoning = "reasoning" in supported_params
        # Optional global thinking level (non-sweep mode only)
        reasoning_payload = (
            _compose_reasoning_payload(thinking_level)
            if model_supports_reasoning and thinking_level
            else None
        )

        # Determine which thinking levels to evaluate for this model
        levels: List[Optional[str]]
        if sweep_thinking_levels:
            suggested = _suggest_levels_for_model(model)
            levels = [None] + (suggested or ["low", "medium", "high"])  # fallback
        else:
            levels = [thinking_level] if thinking_level else [None]

        for sample_index in range(samples):
            for question in questions:
                attempt_dir = run_dir / f"q{question.number:03d}_{model.replace('/', '_')}__s{sample_index:02d}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                prompt = _build_prompt(question)
                store_text(attempt_dir / "prompt.txt", prompt)

                for level in levels:
                    level_suffix = (level or "base").replace("/", "_")
                    level_dir = attempt_dir / f"lvl_{level_suffix}"
                    level_dir.mkdir(parents=True, exist_ok=True)
                    attempt: AttemptSummary = {
                        "model": model,
                        "provider": provider,
                        "sample_index": sample_index,
                        "question_number": question.number,
                        "question": question.prompt,
                        "expected_answer": question.answer,
                        "status": "error",
                    }
                    if level:
                        attempt["thinking_level_requested"] = level
                        attempt["thinking_level_supported"] = model_supports_reasoning
                        if model_supports_reasoning:
                            attempt["thinking_level_applied"] = level

                    attempt_start = time.perf_counter()
                    api_latency = None
                    usage: Dict[str, Any] | None = None
                    judge_usage_data: Dict[str, Any] | None = None
                    judge_latency_value: Optional[float] = None
                    try:
                        # Adjust reasoning payload per level
                        level_reasoning = None
                        if model_supports_reasoning and level:
                            level_reasoning = _compose_reasoning_payload(level)
                        response_text, response_meta, api_latency = _call_openrouter(
                            prompt,
                            model=model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            preferred_provider=provider,
                            reasoning_payload=level_reasoning or (
                                reasoning_payload if model_supports_reasoning and thinking_level and not sweep_thinking_levels else None
                            ),
                        )
                    except Exception as exc:
                        attempt["error"] = str(exc)
                        store_text(level_dir / "error.log", str(exc))
                    else:
                        store_text(level_dir / "response.txt", response_text)
                        store_text(level_dir / "response.json", json.dumps(response_meta, indent=2))
                        usage = response_meta.get("usage") if isinstance(response_meta, dict) else None
                        # Extract the final single-token/word answer robustly (skip reasoning blocks)
                        model_answer = _extract_single_line_answer(response_text)
                        normalized_expected = _normalise_answer(question.answer)
                        normalized_observed = _normalise_answer(model_answer)
                        attempt.update(
                            {
                                "model_answer": model_answer,
                                "normalized_expected": normalized_expected,
                                "normalized_answer": normalized_observed,
                            }
                        )
                        if normalized_expected and normalized_expected == normalized_observed:
                            attempt["status"] = "passed"
                        elif judge_enabled:
                            try:
                                judge_pass, judge_decision, judge_reason, judge_usage, judge_raw, judge_latency = _judge_answer(
                                    question.prompt,
                                    normalized_expected or question.answer,
                                    normalized_observed or model_answer,
                                )
                            except Exception as exc:  # pragma: no cover - defensive guard
                                judge_enabled = False
                                judge_status_reason = judge_status_reason or f"judge_failed:{exc}"
                                LOGGER.warning(
                                    "qa.judge_failed",
                                    question_number=question.number,
                                    model=model,
                                    error=str(exc),
                                )
                                attempt["judge_error"] = str(exc)
                            else:
                                attempt["judge_model"] = JUDGE_MODEL
                                if judge_decision:
                                    attempt["judge_decision"] = judge_decision
                                if judge_reason:
                                    attempt["judge_rationale"] = judge_reason
                                    reason_lower = judge_reason.lower()
                                    if "judge returned empty content" in reason_lower or "judge response missing content" in reason_lower:
                                        attempt["judge_error"] = judge_reason
                                if judge_raw:
                                    attempt["judge_raw_response"] = judge_raw
                                if judge_usage:
                                    attempt["judge_usage"] = judge_usage
                                    judge_usage_data = judge_usage
                                if judge_latency is not None:
                                    attempt["judge_latency_seconds"] = judge_latency
                                    judge_latency_value = judge_latency
                                if judge_pass:
                                    attempt["status"] = "passed"
                                else:
                                    attempt["status"] = "failed"
                        else:
                            attempt["status"] = "failed"

                    duration = time.perf_counter() - attempt_start
                    attempt["duration_seconds"] = duration
                    if api_latency is not None:
                        attempt["api_latency_seconds"] = api_latency
                    if usage is not None:
                        attempt["usage"] = usage

                    # Per-level token accounting and cost
                    prompt_tokens = None
                    completion_tokens = None
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
                        completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
                    judge_prompt_tokens = None
                    judge_completion_tokens = None
                    if judge_usage_data:
                        judge_prompt_tokens = judge_usage_data.get("prompt_tokens") or judge_usage_data.get("input_tokens")
                        judge_completion_tokens = judge_usage_data.get("completion_tokens") or judge_usage_data.get("output_tokens")
                        attempt["judge_usage"] = judge_usage_data
                    if prompt_tokens is not None:
                        prompt_tokens = int(prompt_tokens)
                        total_prompt_tokens += prompt_tokens
                    if completion_tokens is not None:
                        completion_tokens = int(completion_tokens)
                        total_completion_tokens += completion_tokens
                    if judge_prompt_tokens is not None:
                        judge_prompt_tokens = int(judge_prompt_tokens)
                        total_prompt_tokens += judge_prompt_tokens
                        attempt["judge_prompt_tokens"] = judge_prompt_tokens
                    if judge_completion_tokens is not None:
                        judge_completion_tokens = int(judge_completion_tokens)
                        total_completion_tokens += judge_completion_tokens
                        attempt["judge_completion_tokens"] = judge_completion_tokens

                    attempt_cost = 0.0
                    pricing = model_metadata.get(model)
                    if pricing and (prompt_tokens is not None or completion_tokens is not None):
                        response_cost = 0.0
                        if prompt_tokens is not None:
                            response_cost += prompt_tokens * pricing.get("prompt", 0.0)
                        if completion_tokens is not None:
                            response_cost += completion_tokens * pricing.get("completion", 0.0)
                        if response_cost:
                            attempt["response_cost_usd"] = response_cost
                            attempt_cost += response_cost

                    judge_cost = 0.0
                    judge_pricing = model_metadata.get(JUDGE_MODEL)
                    if judge_pricing and (judge_prompt_tokens is not None or judge_completion_tokens is not None):
                        if judge_prompt_tokens is not None:
                            judge_cost += judge_prompt_tokens * judge_pricing.get("prompt", 0.0)
                        if judge_completion_tokens is not None:
                            judge_cost += judge_completion_tokens * judge_pricing.get("completion", 0.0)
                        if judge_cost:
                            attempt["judge_cost_usd"] = judge_cost
                            attempt_cost += judge_cost

                    if attempt_cost:
                        attempt["cost_usd"] = attempt_cost
                        total_cost += attempt_cost

                    total_duration += duration
                    if api_latency is not None:
                        total_latency += api_latency
                    if judge_latency_value is not None:
                        total_latency += judge_latency_value

                    # Record the attempt and emit progress for this level
                    attempts.append(attempt)
                    if progress_callback:
                        progress_callback(model, question.number, sample_index, attempt)

    per_model_stats: Dict[str, Dict[str, Any]] = {}

    def _bucket_level_for_metrics(attempt: Dict[str, Any], default_level: Optional[str] = None) -> str:
        applied = attempt.get("thinking_level_applied")
        if applied:
            return str(applied)
        if attempt.get("thinking_level_supported") is False and attempt.get("thinking_level_requested"):
            return f"unsupported ({attempt.get('thinking_level_requested')})"
        if default_level:
            return str(default_level)
        return "base"

    # Build per-level metrics similar to coding harness but at question granularity
    metrics_by_thinking_level: Dict[str, Dict[str, Dict[str, Any]]] = {}
    per_model_level: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for a in attempts:
        model = a.get("model")
        if not model:
            continue
        level = _bucket_level_for_metrics(a, thinking_level)
        per_model_level.setdefault(model, {}).setdefault(level, []).append(a)

    for model, level_map in per_model_level.items():
        metrics_by_thinking_level[model] = {}
        for level, level_attempts in level_map.items():
            total_attempts = len(level_attempts)
            passed_attempts = sum(1 for x in level_attempts if (x.get("status") or "").lower() == "passed")
            failed_attempts = sum(1 for x in level_attempts if (x.get("status") or "").lower() == "failed")
            errored_attempts = sum(1 for x in level_attempts if (x.get("status") or "").lower() == "error")

            by_question: Dict[int, List[Dict[str, Any]]] = {}
            for att in level_attempts:
                qn = att.get("question_number")
                if qn is None:
                    continue
                by_question.setdefault(int(qn), []).append(att)

            pass_at_1_values: List[float] = []
            pass_at_k_values: List[float] = []
            for attempts_for_question in by_question.values():
                total = len(attempts_for_question)
                correct = sum(1 for a in attempts_for_question if (a.get("status") or "").lower() == "passed")
                pass_at_1_values.append(_estimate_pass_at_k(total, correct, 1) or 0.0)
                pass_at_k_values.append(_estimate_pass_at_k(total, correct, min(samples, total)) or 0.0)

            question_count = len(by_question)
            accuracy = (sum(pass_at_k_values) / question_count) if question_count else None

            # Aggregate token usage and timings for this subset
            prompt_tokens = 0
            completion_tokens = 0
            duration_sum = 0.0
            latency_sum = 0.0
            cost_sum = 0.0
            for x in level_attempts:
                usage_main = x.get("usage") or {}
                prompt_tokens += int(usage_main.get("prompt_tokens") or usage_main.get("input_tokens") or 0)
                completion_tokens += int(usage_main.get("completion_tokens") or usage_main.get("output_tokens") or 0)
                prompt_tokens += int(x.get("judge_prompt_tokens") or 0)
                completion_tokens += int(x.get("judge_completion_tokens") or 0)
                duration_sum += float(x.get("duration_seconds") or 0.0)
                latency_sum += float(x.get("api_latency_seconds") or 0.0)
                latency_sum += float(x.get("judge_latency_seconds") or 0.0)
                cost_sum += float(x.get("cost_usd") or 0.0)

            metrics_by_thinking_level[model][level] = {
                "attempts": total_attempts,
                "passed_attempts": passed_attempts,
                "failed_attempts": failed_attempts,
                "error_attempts": errored_attempts,
                "questions": question_count,
                "pass_at_1": (sum(pass_at_1_values) / question_count) if question_count else None,
                "pass_at_k": (sum(pass_at_k_values) / question_count) if question_count else None,
                "accuracy": accuracy,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(cost_sum, 6) if cost_sum else 0.0,
                "duration_seconds": duration_sum,
                "api_latency_seconds": latency_sum,
            }

    for model in model_list:
        model_attempts = [attempt for attempt in attempts if attempt.get("model") == model]
        by_question: Dict[int, List[Dict[str, Any]]] = {}
        for att in model_attempts:
            qn = att.get("question_number")
            if qn is None:
                continue
            by_question.setdefault(int(qn), []).append(att)

        pass_at_1_values: List[float] = []
        pass_at_k_values: List[float] = []
        for attempts_for_question in by_question.values():
            total = len(attempts_for_question)
            correct = sum(1 for a in attempts_for_question if (a.get("status") or "").lower() == "passed")
            pass_at_1_values.append(_estimate_pass_at_k(total, correct, 1) or 0.0)
            pass_at_k_values.append(_estimate_pass_at_k(total, correct, min(samples, total)) or 0.0)

        question_total = len(by_question)
        accuracy = (sum(pass_at_k_values) / question_total) if question_total else None
        pass_at_1_overall = (sum(pass_at_1_values) / question_total) if question_total else None

        model_prompt_tokens = 0
        model_completion_tokens = 0
        for attempt in model_attempts:
            usage_main = attempt.get("usage") or {}
            model_prompt_tokens += int(
                usage_main.get("prompt_tokens")
                or usage_main.get("input_tokens")
                or 0
            )
            model_completion_tokens += int(
                usage_main.get("completion_tokens")
                or usage_main.get("output_tokens")
                or 0
            )
            model_prompt_tokens += int(attempt.get("judge_prompt_tokens") or 0)
            model_completion_tokens += int(attempt.get("judge_completion_tokens") or 0)
        cost = sum(attempt.get("cost_usd", 0.0) for attempt in model_attempts)
        model_duration = sum(float(attempt.get("duration_seconds") or 0.0) for attempt in model_attempts)
        model_latency = sum(float(attempt.get("api_latency_seconds") or 0.0) for attempt in model_attempts)
        model_latency += sum(float(attempt.get("judge_latency_seconds") or 0.0) for attempt in model_attempts)
        per_model_stats[model] = {
            "questions": question_total,
            "pass_at_1": pass_at_1_overall,
            "pass_at_k": (sum(pass_at_k_values) / question_total) if question_total else None,
            "accuracy": accuracy,
            "prompt_tokens": model_prompt_tokens,
            "completion_tokens": model_completion_tokens,
            "cost_usd": cost,
            "duration_seconds": model_duration,
            "api_latency_seconds": model_latency,
        }

    # Overall accuracy now reflects question-level pass@k across all models
    overall_questions: Dict[int, List[Dict[str, Any]]] = {}
    for att in attempts:
        qn = att.get("question_number")
        if qn is None:
            continue
        overall_questions.setdefault(int(qn), []).append(att)
    overall_pass_at_k_values: List[float] = []
    for attempts_for_question in overall_questions.values():
        total = len(attempts_for_question)
        correct = sum(1 for a in attempts_for_question if (a.get("status") or "").lower() == "passed")
        overall_pass_at_k_values.append(_estimate_pass_at_k(total, correct, min(samples, total)) or 0.0)
    overall_accuracy = (sum(overall_pass_at_k_values) / len(overall_pass_at_k_values)) if overall_pass_at_k_values else None

    # Store a machine-readable summary on disk
    summary = {
        "timestamp_utc": timestamp.isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "output_dir": str(base_output),
        "questions": [asdict(question_map[number]) for number in sorted(question_map)],
        "models": model_list,
        "requested_models": requested_models,
        "provider": provider,
        "samples": samples,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking_level": thinking_level,
        "include_thinking_variants": include_thinking_variants,
        "sweep_thinking_levels": bool(sweep_thinking_levels),
        "attempts": attempts,
        "metrics": {
            "per_model": per_model_stats,
            "overall": {
                "accuracy": overall_accuracy,
            },
        },
        "metrics_by_thinking_level": metrics_by_thinking_level,
        "timing": {
            "total_duration_seconds": total_duration,
            "total_api_latency_seconds": total_latency,
        },
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost, 6),
        },
        "pricing": {model: model_metadata.get(model) for model in model_list if model_metadata.get(model)},
        "judge_status": {
            "enabled": judge_enabled,
            "reason": judge_status_reason or (None if judge_enabled else "disabled"),
        },
    }

    summary_path = run_dir / "summary.json"
    store_text(summary_path, json.dumps(summary, indent=2))

    latest_summary = QA_RUNS_ROOT / "latest_summary.json"
    store_text(latest_summary, json.dumps(summary, indent=2))

    return summary


__all__ = ["run_question_benchmark"]
