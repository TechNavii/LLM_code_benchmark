"""Execution harness for the expert question benchmark."""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency for offline runs
    requests = None

import structlog

from harness.config import get_settings
from harness.exceptions import HarnessError
from harness.run_harness import fetch_model_pricing, store_text
from harness.expert_questions.dataset import Question, load_questions

SETTINGS = get_settings()
QA_RUNS_ROOT = SETTINGS.runs_root / "qa_runs"
JUDGE_MODEL = SETTINGS.expert_qa_judge_model
JUDGE_MAX_TOKENS = 256
LOGGER = structlog.get_logger(__name__)


def _call_openrouter(
    prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    preferred_provider: Optional[str] = None,
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

    start = time.perf_counter()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Judge request failed: {exc}") from exc

    latency = time.perf_counter() - start

    if response.status_code >= 400:
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
        raise RuntimeError(
            f"Judge request failed ({response.status_code}): {error_message}"
        )

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:  # pragma: no cover - API schema issues
        raise HarnessError(f"Unexpected OpenRouter response payload: {data}") from exc
    return content, data, latency


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

    max_attempts = 3
    total_latency = 0.0
    last_usage: Optional[Dict[str, Any]] = None
    last_raw: Optional[str] = None
    failure_reason: Optional[str] = None

    for attempt_index in range(1, max_attempts + 1):
        start = time.perf_counter()
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        latency = time.perf_counter() - start
        total_latency += latency
        response.raise_for_status()
        data = response.json()
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

        if raw_text:
            last_raw = raw_text
            break

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
    run_id: str,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    questions = load_questions()
    model_list = [model.strip() for model in models if model.strip()]
    if not model_list:
        raise HarnessError("At least one model must be provided.")

    samples = max(1, int(samples))
    temperature = float(temperature)
    max_tokens = int(max_tokens)

    judge_enabled = bool(JUDGE_MODEL) and requests is not None
    pricing_models = list(dict.fromkeys(model_list + ([JUDGE_MODEL] if judge_enabled else [])))
    pricing_table = fetch_model_pricing(pricing_models)
    if judge_enabled and JUDGE_MODEL not in pricing_table:
        LOGGER.info(
            "qa.judge_disabled",
            reason="pricing_unavailable",
            judge_model=JUDGE_MODEL,
        )
        judge_enabled = False

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

    for model in model_list:
        for sample_index in range(samples):
            for question in questions:
                attempt_dir = run_dir / f"q{question.number:03d}_{model.replace('/', '_')}__s{sample_index:02d}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                prompt = _build_prompt(question)
                store_text(attempt_dir / "prompt.txt", prompt)

                attempt: AttemptSummary = {
                    "model": model,
                    "provider": provider,
                    "sample_index": sample_index,
                    "question_number": question.number,
                    "question": question.prompt,
                    "expected_answer": question.answer,
                    "status": "error",
                }

                attempt_start = time.perf_counter()
                api_latency = None
                usage: Dict[str, Any] | None = None
                judge_usage_data: Dict[str, Any] | None = None
                judge_latency_value: Optional[float] = None
                try:
                    response_text, response_meta, api_latency = _call_openrouter(
                        prompt,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        preferred_provider=provider,
                    )
                except Exception as exc:
                    attempt["error"] = str(exc)
                    store_text(attempt_dir / "error.log", str(exc))
                else:
                    store_text(attempt_dir / "response.txt", response_text)
                    store_text(attempt_dir / "response.json", json.dumps(response_meta, indent=2))
                    usage = response_meta.get("usage") if isinstance(response_meta, dict) else None
                    model_answer = response_text.strip().splitlines()[0].strip()
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
                pricing = pricing_table.get(model)
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
                judge_pricing = pricing_table.get(JUDGE_MODEL)
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

                attempts.append(attempt)
                if progress_callback:
                    progress_callback(model, question.number, sample_index, attempt)

    per_model_stats: Dict[str, Dict[str, Any]] = {}
    for model in model_list:
        model_attempts = [attempt for attempt in attempts if attempt["model"] == model]
        correct = sum(1 for attempt in model_attempts if attempt.get("status") == "passed")
        total = len(model_attempts)
        accuracy = correct / total if total else None
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
            "correct": correct,
            "total": total,
            "accuracy": accuracy,
            "prompt_tokens": model_prompt_tokens,
            "completion_tokens": model_completion_tokens,
            "cost_usd": cost,
            "duration_seconds": model_duration,
            "api_latency_seconds": model_latency,
        }

    overall_total = len(attempts)
    overall_correct = sum(1 for attempt in attempts if attempt.get("status") == "passed")
    overall_accuracy = overall_correct / overall_total if overall_total else None

    # Store a machine-readable summary on disk
    summary = {
        "timestamp_utc": timestamp.isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "output_dir": str(base_output),
        "questions": [asdict(question_map[number]) for number in sorted(question_map)],
        "models": model_list,
        "provider": provider,
        "samples": samples,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "attempts": attempts,
        "metrics": {
            "per_model": per_model_stats,
            "overall": {
                "correct": overall_correct,
                "total": overall_total,
                "accuracy": overall_accuracy,
            },
        },
        "timing": {
            "total_duration_seconds": total_duration,
            "total_api_latency_seconds": total_latency,
        },
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost, 6),
        },
        "pricing": {model: pricing_table.get(model) for model in model_list if pricing_table.get(model)},
    }

    summary_path = run_dir / "summary.json"
    store_text(summary_path, json.dumps(summary, indent=2))

    latest_summary = QA_RUNS_ROOT / "latest_summary.json"
    store_text(latest_summary, json.dumps(summary, indent=2))

    return summary


__all__ = ["run_question_benchmark"]
