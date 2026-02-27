#!/usr/bin/env python3
"""Benchmark harness for evaluating multiple tasks/models via OpenRouter."""

from __future__ import annotations

import argparse
import difflib
import datetime as dt
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from urllib.parse import urlparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterable

try:
    import requests
except ImportError:  # pragma: no cover - optional for offline dry runs
    requests = None


ROOT = Path(__file__).resolve().parents[1]

logger = logging.getLogger(__name__)


def _cli_echo(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(f"{message}\n")


from harness.config import get_settings
from harness.exceptions import (
    HarnessError,
    APIError,
    RateLimitError,
    EmptyResponseError,
    ProviderError,
)
from harness.http_utils import parse_retry_after
from harness.secure_execution import secure_run


SETTINGS = get_settings()

TASKS_ROOT = SETTINGS.tasks_root
RUN_ARTIFACTS = SETTINGS.runs_root
DEFAULT_MODEL = SETTINGS.default_model
DEFAULT_MAX_TOKENS = SETTINGS.default_max_tokens
SUPPORTED_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".html",
    ".inl",
    ".py",
    ".js",
    ".json",
    ".ts",
    ".tsx",
    ".go",
    ".md",
    ".rs",
    ".txt",
    ".toml",
    ".sh",
    ".yaml",
    ".yml",
}
MAX_LOG_CHARS = SETTINGS.max_log_chars
DEFAULT_ALLOW_INCOMPLETE_DIFFS = SETTINGS.allow_incomplete_diffs
DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK = SETTINGS.allow_diff_rewrite_fallback

TASK_HINTS: dict[str, str] = {
    "cpp_expert_sparse_matrix": textwrap.dedent(
        """
        Update the existing SparseMatrix class in-place. Do not introduce a second class definition or duplicate the declarations already present in sparse_matrix.{h,cpp}. Edit the current methods to use CSR storage and keep header/implementation aligned. Tests require: set(…,0) removes entries, get throws std::out_of_range for invalid indices, multiply enforces shape compatibility, transpose returns a new matrix, and nnz reflects stored entries.
        """
    ).strip(),
    "cpp_expert_thread_pool": textwrap.dedent(
        """
        Maintain the existing ThreadPool class definition and member names (e.g., `condition_`, `stop_`, `workers_`). Update behaviour by reusing those members instead of introducing alternative fields, renaming them, or duplicating the class in the header/source. Tests expect the destructor to join workers, enqueue to throw once stop_ is set, and condition_.wait to use a predicate preventing lost tasks.
        """
    ).strip(),
    "go_expert_lru_cache": textwrap.dedent(
        """
        Implement the LRU cache without relying on package-level variables. Define helper structs with `type` declarations and keep the public API identical. Avoid importing fmt unless you actually need formatted errors; prefer returning errors or panicking only when capacity <= 0. Tests check eviction order, Len(), and concurrent Set/Get behaviour.
        """
    ).strip(),
    "go_expert_scheduler": textwrap.dedent(
        """
        Preserve the existing Scheduler type and its fields. Change only the coordination logic so priority and concurrency constraints hold; avoid renaming fields or introducing new exported types. Tests assert high-priority tasks run before lower ones and that the concurrency limit is never exceeded.
        """
    ).strip(),
    "go_expert_token_bucket": textwrap.dedent(
        """
        Keep all executable code inside functions/methods—Go does not permit statements at the top level. Ensure the bucket's fields are stored on the struct and guard state with mutexes so concurrent callers compile and pass go test. Tests cover fractional refill, burst allowance, rejecting non-positive tokens, and concurrency safety.
        """
    ).strip(),
    "python_bugfix_prime_checker": "Non-positive integers (<= 1) must always return False from is_prime.",
    "html_expert_form_validator": "Always call event.preventDefault() in the submit handler before performing validation feedback.",
    "javascript_bugfix_titlecase": "Ensure punctuation and spacing from the original string are preserved when converting words to title case.",
    "javascript_expert_worker_scheduler": "Keep the existing module exports intact—modify the current scheduler implementation without renaming the exported function or moving the file.",
    "python_feature_batched_iterator": "The iterator must yield batches lazily without loading the entire input. Preserve input order and batch sizes per the tests.",
    "python_feature_cli_reporter": "Tests expect grouped reports sorted by project name with exact formatting; match the fixture strings precisely.",
    "python_feature_moving_average": "Emit None until the window is full, then produce averages using the latest window; tests check float precision and sliding behaviour.",
    "python_tool_weather_cli": "Parse arguments as tests expect (city, optional units flag) and render output using the provided template so snapshots match.",
    "rust_expert_time_bucketer": "Reuse the existing module structure; only adjust logic for bucketing without renaming modules or removing public functions. Tests validate bucket boundaries and cumulative totals.",
    "rust_bugfix_prime_checker": "Treat 0 and 1 as non-prime while confirming known primes remain true; avoid integer overflow when checking upper bounds.",
}

_PATCH_LINE_PREFIXES = (
    "diff --git",
    "index ",
    "---",
    "+++",
    "@@",
    "+",
    "-",
    " ",
    "new file mode",
    "deleted file mode",
    "rename from",
    "rename to",
    "similarity index",
    "dissimilarity index",
    "Binary files",
    "\\ No newline at end of file",
)

STRICT_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _is_probably_valid_patch(patch: str) -> bool:
    lines = patch.splitlines()
    if not lines:
        return False

    add_lines = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    remove_lines = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    hunk_lines = sum(1 for line in lines if line.startswith("@@"))
    header_lines = sum(
        1 for line in lines if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ ")
    )

    if header_lines >= 2 and (add_lines or remove_lines or hunk_lines):
        return True
    if hunk_lines and (add_lines or remove_lines):
        return True
    if add_lines + remove_lines >= 2:
        return True
    return False


def _normalize_patch_format(patch: str) -> tuple[str, bool]:
    lines = patch.splitlines()
    normalized: list[str] = []
    in_hunk = False
    current_old_line = 1
    current_new_line = 1
    synthetic_headers = False
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped in {"---", "+++"} and i + 1 < len(lines):
            next_stripped = lines[i + 1].lstrip()
            if stripped == "---" and next_stripped.startswith("--- "):
                i += 1
                continue
            if stripped == "+++" and next_stripped.startswith("+++ "):
                i += 1
                continue
        if stripped.startswith("diff --git") or stripped.startswith("index "):
            normalized.append(line)
            in_hunk = False
            current_old_line = 1
            current_new_line = 1
            i += 1
            continue

        if stripped.startswith("--- "):
            normalized.append(line)
            in_hunk = False
            current_old_line = 1
            current_new_line = 1
            i += 1
            continue

        if stripped.startswith("+++ "):
            normalized.append(line)
            in_hunk = False
            current_old_line = 1
            current_new_line = 1
            i += 1
            continue

        if stripped.startswith("@@"):
            in_hunk = True
            # look ahead to measure hunk span
            j = i + 1
            measured_old = 0
            measured_new = 0
            while j < len(lines):
                candidate = lines[j]
                candidate_stripped = candidate.lstrip()
                if (
                    candidate_stripped.startswith("@@")
                    or candidate_stripped.startswith("diff --git")
                    or candidate_stripped.startswith("--- ")
                    or candidate_stripped.startswith("+++ ")
                ):
                    break
                if candidate.startswith(" "):
                    measured_old += 1
                    measured_new += 1
                elif candidate.startswith("-") and not candidate.startswith("---"):
                    measured_old += 1
                elif candidate.startswith("+") and not candidate.startswith("+++"):
                    measured_new += 1
                elif candidate.startswith("\\"):
                    pass
                else:
                    # treat malformed lines as context
                    measured_old += 1
                    measured_new += 1
                j += 1

            prefix = line[: len(line) - len(stripped)]
            match = HUNK_HEADER_RE.match(stripped)
            suffix = ""
            parsed_old_len_val: int | None = None
            parsed_new_len_val: int | None = None
            old_start = current_old_line if current_old_line > 0 else 1
            new_start = current_new_line if current_new_line > 0 else 1
            old_len = measured_old
            new_len = measured_new
            if match:
                old_start = int(match.group("old_start"))
                new_start = int(match.group("new_start"))
                parsed_old_len = match.group("old_len")
                parsed_new_len = match.group("new_len")
                if parsed_old_len:
                    parsed_old_len_val = int(parsed_old_len)
                if parsed_new_len:
                    parsed_new_len_val = int(parsed_new_len)
                if parsed_old_len_val is not None and parsed_old_len_val != measured_old and measured_old:
                    synthetic_headers = True
                if parsed_new_len_val is not None and parsed_new_len_val != measured_new and measured_new:
                    synthetic_headers = True
                if measured_old == 0 and parsed_old_len_val is not None:
                    old_len = parsed_old_len_val
                if measured_new == 0 and parsed_new_len_val is not None:
                    new_len = parsed_new_len_val
                suffix = stripped[match.end() :].strip()
            else:
                synthetic_headers = True
                suffix = stripped[2:].strip()
                old_start = current_old_line if current_old_line > 0 else 1
                new_start = current_new_line if current_new_line > 0 else 1
                # default lengths for degenerate hunks
                if old_len == 0 and new_len == 0:
                    old_len = 0
                    new_len = 0
                if old_len == 0 and new_len > 0 and parsed_old_len_val is not None:
                    old_len = parsed_old_len_val
                if new_len == 0 and old_len > 0 and parsed_new_len_val is not None:
                    new_len = parsed_new_len_val
            header = f"@@ -{old_start},{old_len} +{new_start},{new_len} @@"
            if suffix:
                header = f"{header} {suffix}"
            line = prefix + header

            advance_old = old_len if old_len > 0 else (1 if new_len > 0 else 0)
            advance_new = new_len if new_len > 0 else (1 if old_len > 0 else 0)
            current_old_line = max(old_start + advance_old, 1)
            current_new_line = max(new_start + advance_new, 1)

            normalized.append(line)
            i += 1
            continue

        if in_hunk and not line.startswith(("+", "-", " ", "\\")):
            line = f" {line}"

        normalized.append(line)
        i += 1

    result = "\n".join(normalized)
    if patch.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, synthetic_headers


def _extract_incomplete_patch(candidate: str) -> str:
    lines = []
    for raw_line in candidate.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            lines.append("")
            continue
        if any(line.startswith(prefix) for prefix in _PATCH_LINE_PREFIXES):
            lines.append(line)
            continue
        break
    patch = "\n".join(lines).strip()
    if patch and not patch.endswith("\n"):
        patch += "\n"
    return patch


def _normalize_model_id(model: str) -> str:
    if model.startswith("openrouter/"):
        return model.split("openrouter/", 1)[1]
    return model


def _is_lmstudio_model(model: str) -> bool:
    return model.startswith("lmstudio/")


def _normalize_lmstudio_model_id(model: str) -> str:
    if model.startswith("lmstudio/"):
        return model.split("lmstudio/", 1)[1]
    return model


def _resolve_lms_path() -> str | None:
    resolved = shutil.which("lms")
    if resolved:
        return resolved
    fallback = Path.home() / ".lmstudio" / "bin" / "lms"
    if fallback.exists():
        return str(fallback)
    return None


def _lmstudio_cli_instance_args(base_url: str) -> list[str]:
    trimmed = (base_url or "").strip()
    if not trimmed:
        return []
    if "://" not in trimmed:
        trimmed = f"http://{trimmed}"
    parsed = urlparse(trimmed)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1234
    return ["--host", host, "--port", str(port)]


def _truncate_cli_output(value: str, *, limit: int = 2000) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) > limit:
        return f"{cleaned[:limit]}..."
    return cleaned


def unload_lmstudio_models(*, base_url: str | None = None, timeout: int = 30) -> bool:
    """Best-effort cleanup of loaded LM Studio models.

    Returns True when the unload command succeeds; otherwise logs a warning and returns False.
    """

    resolved_base_url = (base_url or SETTINGS.lmstudio_base_url or "").strip()
    if not resolved_base_url:
        logger.warning("LM Studio base URL is not configured; skipping model unload")
        return False

    lms_path = _resolve_lms_path()
    if not lms_path:
        logger.warning("LM Studio CLI 'lms' not found; skipping model unload")
        return False

    instance_args = _lmstudio_cli_instance_args(resolved_base_url)
    try:
        unload = subprocess.run(
            [lms_path, "unload", "--all", *instance_args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timed out unloading LM Studio models")
        return False
    except OSError as exc:
        logger.warning("Unable to unload LM Studio models: %s", exc)
        return False

    if unload.returncode != 0:
        detail = _truncate_cli_output(unload.stderr or unload.stdout)
        logger.warning("Unable to unload LM Studio models: %s", detail or "unknown error")
        return False

    return True


def _store_model_metadata(
    registry: dict[str, dict[str, Any]],
    model_id: str,
    metadata: dict[str, Any],
) -> None:
    existing = registry.get(model_id, {})
    if existing:
        merged = {**existing, **metadata}
    else:
        merged = metadata
    registry[model_id] = merged


def fetch_model_metadata(models: list[str]) -> dict[str, dict[str, Any]]:
    if requests is None:
        return {}

    if not models:
        return {}

    if all(_is_lmstudio_model(model) for model in models):
        return {}

    api_key = SETTINGS.openrouter_api_key
    if not api_key:
        logger.warning("OPENROUTER_API_KEY is not set; skipping model metadata fetch")
        return {}

    requested = {_normalize_model_id(model) for model in models}
    try:
        base_url = SETTINGS.openrouter_base_url.rstrip("/")
        models_url = f"{base_url}/models"
        response = requests.get(
            models_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "benchmark-harness",
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        logger.warning("Failed to fetch OpenRouter model metadata: %s", exc)
        return {}
    except ValueError as exc:
        logger.warning("OpenRouter returned non-JSON response for models list: %s", exc)
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for entry in data.get("data", []):
        model_id = entry.get("id")
        if not model_id:
            continue
        is_thinking_variant = model_id.endswith(":thinking")
        base_id = model_id.rsplit(":thinking", 1)[0] if is_thinking_variant else None
        should_include = model_id in requested
        if base_id and base_id in requested:
            should_include = True
        if not should_include:
            continue

        model_pricing = entry.get("pricing") or {}
        try:
            prompt_rate = float(model_pricing.get("prompt", 0))
            completion_rate = float(model_pricing.get("completion", 0))
        except (TypeError, ValueError):
            prompt_rate = 0.0
            completion_rate = 0.0

        metadata = {
            "prompt": prompt_rate,
            "completion": completion_rate,
            "supported_parameters": entry.get("supported_parameters") or [],
            "default_parameters": entry.get("default_parameters") or {},
        }

        _store_model_metadata(registry, model_id, metadata)
        _store_model_metadata(registry, f"openrouter/{model_id}", metadata)
        if is_thinking_variant and base_id:
            _store_model_metadata(
                registry,
                base_id,
                {"thinking_variant": model_id},
            )
            _store_model_metadata(
                registry,
                f"openrouter/{base_id}",
                {"thinking_variant": model_id},
            )
    return registry


# Backwards compatibility for any external imports relying on the old helper name.
fetch_model_pricing = fetch_model_metadata


def expand_models_with_thinking_variants(
    models: list[str],
    metadata: dict[str, dict[str, Any]],
) -> list[str]:
    """Return a model list expanded with thinking variants where available."""
    expanded: list[str] = []
    seen: set[str] = set()

    for model in models:
        if model not in seen:
            expanded.append(model)
            seen.add(model)

        info = metadata.get(model)
        thinking_variant = (info or {}).get("thinking_variant")
        if not thinking_variant:
            continue
        variant_id = f"openrouter/{thinking_variant}" if model.startswith("openrouter/") else thinking_variant
        if variant_id not in seen:
            expanded.append(variant_id)
            seen.add(variant_id)

    return expanded


def _compose_reasoning_payload(level: str) -> dict[str, Any]:
    """Translate CLI input into the OpenRouter reasoning payload."""
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


def discover_tasks() -> list[str]:
    if not TASKS_ROOT.exists():
        return []
    return sorted(
        task_dir.name
        for task_dir in TASKS_ROOT.iterdir()
        if task_dir.is_dir() and (task_dir / "metadata.json").exists()
    )


def load_metadata(task_id: str) -> dict:
    metadata_path = TASKS_ROOT / task_id / "metadata.json"
    if not metadata_path.exists():
        raise HarnessError(f"metadata.json not found for task {task_id}")
    with metadata_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def should_include_in_prompt(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def build_prompt(task_id: str, metadata: dict, include_tests: bool = False) -> str:
    task_dir = TASKS_ROOT / task_id
    instructions_path = task_dir / metadata["instructions_file"]
    if not instructions_path.exists():
        raise HarnessError(f"Instructions file missing: {instructions_path}")
    instructions = instructions_path.read_text(encoding="utf-8").strip()

    workspace_dir = task_dir / metadata.get("workspace_dir", "workspace")
    contextual_snippets: list[str] = []

    for source in sorted(workspace_dir.rglob("*")):
        if source.is_file() and should_include_in_prompt(source):
            rel_path = source.relative_to(workspace_dir)
            snippet = source.read_text(encoding="utf-8")
            contextual_snippets.append(
                textwrap.dedent(
                    f"""
                    File: {rel_path}
                    ```
                    {snippet}
                    ```
                    """
                ).strip()
            )

    if include_tests:
        tests_dir = task_dir / metadata.get("tests_dir", "tests")
        if tests_dir.exists():
            for source in sorted(tests_dir.rglob("*")):
                if source.is_file() and should_include_in_prompt(source):
                    rel_path = Path("tests") / source.relative_to(tests_dir)
                    snippet = source.read_text(encoding="utf-8")
                    contextual_snippets.append(
                        textwrap.dedent(
                            f"""
                            File: {rel_path}
                            ```
                            {snippet}
                            ```
                            """
                        ).strip()
                    )

    diff_guide = textwrap.dedent(
        """
        Diff requirements:
        - Emit a unified diff that cleanly applies with `patch`.
        - Use the existing file paths exactly as shown in the repository (no leading `workspace/`, absolute paths, or new files).
        - Preserve existing identifiers and members unless the instructions say otherwise—avoid renaming fields, functions, or types when a targeted fix will do.
        - When you keep a line unchanged, include it as a leading space context line; when you remove a line, include it with a leading `-` so the hunk still shows what was removed.
        - Only touch the regions you need to change. Do not reformat or reorder unrelated code.
        - Prefer updating the existing definitions instead of rewriting whole files.

        Example unified diff:
        ```diff
        --- foo.py
        +++ foo.py
        @@ -1,4 +1,4 @@
         def add(a, b):
-            return a - b
+            return a + b

         def subtract(a, b):
             return a - b
        ```
        """
    ).strip()

    task_hint = TASK_HINTS.get(task_id)
    hint_block = f"\n\nTask-specific guidance:\n{task_hint}" if task_hint else ""

    prompt = textwrap.dedent(
        f"""
        You are an autonomous software developer. Apply a minimal fix to satisfy the task instructions and existing tests.

        Task instructions:
        {instructions}

        {diff_guide}

        {hint_block}

        Return a unified diff patch enclosed in a single ```diff fenced code block and nothing else.

        Project context:
        {os.linesep.join(contextual_snippets)}
        """
    ).strip()

    return prompt


# Number of times to retry transient completion failures before giving up.
MAX_COMPLETION_RETRIES = SETTINGS.completion_max_retries
RETRY_BACKOFF_SECONDS = SETTINGS.completion_retry_backoff_seconds
MAX_BACKOFF_SECONDS = SETTINGS.completion_max_backoff_seconds


def _classify_error(
    status: int,
    error_message: str,
    retry_after: float | None = None,
    is_empty_content: bool = False,
) -> HarnessError:
    """Classify an API error into the appropriate exception type."""
    if is_empty_content:
        return EmptyResponseError("OpenRouter returned empty content", retry_after=retry_after)
    if status == 429:
        return RateLimitError(
            f"OpenRouter rate limited ({status}): {error_message}",
            retry_after=retry_after,
        )
    if status >= 500:
        return ProviderError(
            f"OpenRouter server error ({status}): {error_message}",
            retry_after=retry_after,
        )
    # For other transient errors (network issues, upstream failures)
    lowered = error_message.lower()
    if any(k in lowered for k in ("network", "upstream", "temporar", "timeout", "try again", "rate limit", "too many")):
        return ProviderError(f"Provider error: {error_message}", retry_after=retry_after)
    return HarnessError(f"OpenRouter request failed ({status}): {error_message}")


def call_openrouter(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    preferred_provider: str | None = None,
    *,
    thinking_level: str | None = None,
    model_info: dict[str, Any] | None = None,
) -> tuple[str, dict, float]:
    if requests is None:
        raise HarnessError("The 'requests' library is required to call OpenRouter.")

    api_key = SETTINGS.openrouter_api_key
    if not api_key:
        raise HarnessError("OPENROUTER_API_KEY must be set to run OpenRouter models")

    base_url = SETTINGS.openrouter_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "benchmark-harness",
        "Content-Type": "application/json",
    }

    def wrap_content(content: str):
        return [{"type": "text", "text": content}]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": wrap_content("You produce clean, minimal patches.")},
            {"role": "user", "content": wrap_content(prompt)},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if preferred_provider:
        payload["provider"] = {
            "order": [preferred_provider],
        }

    supported_params: set[str] = set()
    if model_info:
        supported_params = {
            param.lower() for param in model_info.get("supported_parameters", []) if isinstance(param, str)
        }
    if thinking_level and "reasoning" in supported_params:
        reasoning_payload = _compose_reasoning_payload(thinking_level)
        if reasoning_payload:
            payload["reasoning"] = reasoning_payload
            if "include_reasoning" in supported_params:
                payload["include_reasoning"] = True

    last_error: HarnessError | None = None
    backoff = RETRY_BACKOFF_SECONDS

    for attempt in range(MAX_COMPLETION_RETRIES):
        should_retry = False
        retry_after: float | None = None

        try:
            start_time = time.perf_counter()
            response = requests.post(url, headers=headers, json=payload, timeout=SETTINGS.api_call_timeout_seconds)
            duration = time.perf_counter() - start_time
        except requests.exceptions.Timeout as exc:  # pragma: no cover - timeout
            last_error = ProviderError(
                f"OpenRouter request timed out after {SETTINGS.api_call_timeout_seconds}s: {exc}"
            )
            should_retry = True
        except requests.exceptions.RequestException as exc:  # pragma: no cover - network failures
            last_error = ProviderError(f"OpenRouter request failed: {exc}")
            should_retry = True
        else:
            status = response.status_code
            retry_after = parse_retry_after(response.headers)

            if status >= 500:
                error_message = response.text.strip()
                last_error = _classify_error(status, error_message, retry_after)
                should_retry = True
            elif status >= 400:
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
                if status == 429:
                    last_error = _classify_error(status, error_message, retry_after)
                    should_retry = True
                else:
                    raise HarnessError(f"OpenRouter request failed ({status}): {error_message}")
            else:
                try:
                    data = response.json()
                except (requests.exceptions.JSONDecodeError, ValueError):
                    content_type = response.headers.get("content-type", "unknown")
                    body_preview = response.text.strip()
                    if len(body_preview) > 512:
                        body_preview = f"{body_preview[:512]}..."
                    last_error = ProviderError(
                        "OpenRouter returned a non-JSON response payload. "
                        f"status={status} content-type={content_type} preview={body_preview!r}"
                    )
                    should_retry = True
                else:
                    # Handle provider-nested error responses that still return HTTP 200
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
                            if any(
                                k in lowered
                                for k in (
                                    "network",
                                    "upstream",
                                    "temporar",
                                    "timeout",
                                    "try again",
                                    "rate limit",
                                    "too many",
                                )
                            ):
                                is_transient = True
                            # Use appropriate error type based on code
                            if code_int == 429:
                                last_error = RateLimitError(
                                    f"Provider rate limited ({code}): {message or 'unknown error'}",
                                    retry_after=retry_after,
                                )
                            elif is_transient:
                                last_error = ProviderError(
                                    f"Provider error ({code}): {message or 'unknown error'}", retry_after=retry_after
                                )
                            else:
                                last_error = HarnessError(f"Provider error ({code}): {message or 'unknown error'}")
                            should_retry = is_transient
                        else:
                            last_error = ProviderError(f"Unexpected OpenRouter response payload: {data}")
                            should_retry = True
                    else:
                        first = choices[0] if choices else {}
                        choice_error = (first or {}).get("error")
                        content = (first or {}).get("message", {}).get("content", "")

                        # If the provider surfaced an error inside choices, decide whether to retry
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
                            if any(
                                k in lowered
                                for k in (
                                    "network",
                                    "upstream",
                                    "temporar",
                                    "timeout",
                                    "try again",
                                    "rate limit",
                                    "too many",
                                )
                            ):
                                is_transient = True

                            # Use appropriate error type based on code
                            if code_int == 429:
                                last_error = RateLimitError(
                                    f"OpenRouter provider rate limited ({code}): {message or 'unknown error'}",
                                    retry_after=retry_after,
                                )
                            elif is_transient:
                                last_error = ProviderError(
                                    f"OpenRouter provider error ({code}): {message or 'unknown error'}",
                                    retry_after=retry_after,
                                )
                            else:
                                last_error = HarnessError(
                                    f"OpenRouter provider error ({code}): {message or 'unknown error'}"
                                )
                            should_retry = is_transient
                        else:
                            cleaned = (content or "").strip()
                            if cleaned:
                                return cleaned, data, duration
                            # Empty content with no explicit error: retry once or twice
                            last_error = EmptyResponseError("OpenRouter returned empty content")
                            should_retry = True

        if attempt < MAX_COMPLETION_RETRIES - 1 and should_retry:
            # Use Retry-After header if available, otherwise use exponential backoff
            if retry_after is not None and retry_after > 0:
                wait_time = min(retry_after, MAX_BACKOFF_SECONDS)
            else:
                wait_time = min(backoff, MAX_BACKOFF_SECONDS)
            time.sleep(wait_time)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue
        break

    assert last_error is not None  # for type checkers
    raise last_error


def call_lmstudio(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> tuple[str, dict, float]:
    if requests is None:
        raise HarnessError("The 'requests' library is required to call LM Studio.")

    base_url = SETTINGS.lmstudio_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You produce clean, minimal patches."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        start_time = time.perf_counter()
        response = requests.post(url, headers=headers, json=payload, timeout=SETTINGS.api_call_timeout_seconds)
        duration = time.perf_counter() - start_time
    except requests.exceptions.Timeout as exc:  # pragma: no cover
        raise ProviderError(f"LM Studio request timed out after {SETTINGS.api_call_timeout_seconds}s: {exc}") from exc
    except requests.exceptions.RequestException as exc:  # pragma: no cover
        raise ProviderError(f"LM Studio request failed: {exc}") from exc

    status = response.status_code
    if status >= 500:
        raise ProviderError(f"LM Studio server error ({status}): {response.text.strip()}")
    if status >= 400:
        message = response.text.strip()
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = None
        if isinstance(error_payload, dict):
            message = (
                error_payload.get("error", {}).get("message")
                or error_payload.get("message")
                or error_payload.get("detail")
                or message
            )
        raise HarnessError(f"LM Studio request failed ({status}): {message}")

    try:
        data = response.json()
    except (requests.exceptions.JSONDecodeError, ValueError):
        content_type = response.headers.get("content-type", "unknown")
        body_preview = response.text.strip()
        if len(body_preview) > 512:
            body_preview = f"{body_preview[:512]}..."
        raise ProviderError(
            "LM Studio returned a non-JSON response payload. "
            f"status={status} content-type={content_type} preview={body_preview!r}"
        )

    choices = data.get("choices") if isinstance(data, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else {}
    message_obj = (first or {}).get("message") or {}
    content = message_obj.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        content = "".join(parts)

    cleaned = str(content or "").strip()
    if not cleaned:
        raise EmptyResponseError("LM Studio returned empty content")

    return cleaned, data, duration


def extract_patch(raw_response: str, allow_incomplete_diffs: bool = False) -> str:
    fence = "```diff"
    if fence not in raw_response:
        raise HarnessError("Model response does not contain a ```diff fenced block.")
    start = raw_response.index(fence) + len(fence)
    # Find closing ``` that is at the start of a line (not embedded in code)
    # This handles cases where generated code contains ``` strings
    end = None
    search_pos = start
    while search_pos < len(raw_response):
        try:
            candidate = raw_response.index("```", search_pos)
        except ValueError:
            break
        # Check if this ``` is at the start of a line (preceded by newline or at start)
        if candidate == 0 or raw_response[candidate - 1] == "\n":
            end = candidate
            break
        search_pos = candidate + 3
    if end is None:
        if not allow_incomplete_diffs:
            raise HarnessError("Model response does not contain closing ``` fence.") from None
        fallback_patch = _extract_incomplete_patch(raw_response[start:])
        if not fallback_patch or not _is_probably_valid_patch(fallback_patch):
            raise HarnessError("Model response diff block is incomplete or untrustworthy (missing closing ``` fence).")
        return fallback_patch
    patch = raw_response[start:end]
    return patch.strip() + "\n"


def clean_patch_text(patch_text: str) -> tuple[str, bool, bool]:
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    cleaned = ansi_escape.sub("", patch_text)
    if "\x1b" in cleaned:
        raise HarnessError("Patch contains unsupported control characters.")
    cleaned, synthetic_headers = _normalize_patch_format(cleaned)
    git_style = cleaned.startswith("--- a/") or cleaned.startswith("diff --git")
    return cleaned, git_style, synthetic_headers


def prepare_run_directory(task_id: str, metadata: dict) -> Path:
    task_dir = TASKS_ROOT / task_id
    workspace_dir = task_dir / metadata.get("workspace_dir", "workspace")
    tests_dir = task_dir / metadata.get("tests_dir", "tests")

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"{task_id}_"))
    run_workspace = tmp_dir / "workspace"
    shutil.copytree(workspace_dir, run_workspace)
    if tests_dir.exists():
        shutil.copytree(tests_dir, run_workspace / "tests")

    nested_workspace = run_workspace / "workspace"
    if not nested_workspace.exists():
        try:
            nested_workspace.symlink_to(".")
        except OSError:
            pass

    requirements = task_dir / "requirements.txt"
    if requirements.exists():
        shutil.copy(requirements, run_workspace / "requirements.txt")

    return run_workspace


def install_requirements(workspace_path: Path) -> None:
    requirements = workspace_path / "requirements.txt"
    if not requirements.exists():
        return
    process = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workspace_path),
        check=False,
    )
    if process.returncode != 0:
        raise HarnessError(
            f"Failed to install requirements:\nSTDOUT:\n{process.stdout.decode()}\nSTDERR:\n{process.stderr.decode()}"
        )


def _run_patch_command(args: list[str], patch_bytes: bytes, workspace_path: Path, timeout: int = 60):
    try:
        return subprocess.run(
            args,
            input=patch_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace_path),
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise HarnessError("Failed to apply patch: patch command timed out") from exc


def _normalize_patch_path(path: str) -> str | None:
    path = path.strip()
    if not path or path in {"/dev/null", "dev/null"}:
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    path = path.lstrip("./")
    if path.startswith("workspace/"):
        path = path[len("workspace/") :]
    return path.lstrip("./")


def _extract_full_file_rewrites(cleaned_patch: str) -> dict[str, str] | None:
    lines = cleaned_patch.splitlines()
    rewrites: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git"):
            i += 1
            continue
        if not line.startswith("--- "):
            i += 1
            continue
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            return None
        new_path = lines[i][4:].strip()
        i += 1
        content_lines: list[str] = []
        has_minus = False
        while i < len(lines):
            current = lines[i]
            if current.startswith("diff --git") or current.startswith("--- "):
                break
            if current.startswith("@@"):
                i += 1
                continue
            if current.startswith("-") and not current.startswith("---"):
                has_minus = True
                i += 1
                continue
            if current.startswith("+") and not current.startswith("+++"):
                content_lines.append(current[1:])
                i += 1
                continue
            if current.startswith(" "):
                content_lines.append(current[1:])
                i += 1
                continue
            if current.startswith("\\"):
                i += 1
                continue
            i += 1
        if has_minus:
            return None
        target_path = _normalize_patch_path(new_path)
        if target_path is None:
            return None
        content = "\n".join(content_lines)
        if content_lines:
            content += "\n"
        rewrites[target_path] = content
    return rewrites or None


HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_len>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_len>\d+))? @@"
)


def _parse_unified_diff(cleaned_patch: str):
    lines = cleaned_patch.splitlines()
    files = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git"):
            i += 1
            continue
        if not line.startswith("--- "):
            i += 1
            continue
        old_path = line[4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            return None
        new_path = lines[i][4:].strip()
        i += 1
        hunks = []
        while i < len(lines):
            current = lines[i]
            if current.startswith("diff --git") or current.startswith("--- "):
                break
            if current.startswith("@@"):
                match = HUNK_HEADER_RE.match(current)
                if not match:
                    return None
                start_old = int(match.group("old_start"))
                len_old = int(match.group("old_len") or "1")
                start_new = int(match.group("new_start"))
                len_new = int(match.group("new_len") or "1")
                i += 1
                hunk_lines: list[str] = []
                while i < len(lines):
                    candidate = lines[i]
                    if candidate.startswith("diff --git") or candidate.startswith("--- ") or candidate.startswith("@@"):
                        break
                    hunk_lines.append(candidate)
                    i += 1
                hunks.append((start_old, len_old, start_new, len_new, hunk_lines))
            else:
                i += 1
        files.append((old_path, new_path, hunks))
    return files or None


def _apply_parsed_unified_diff(file_diffs, workspace_path: Path) -> list[str] | None:
    rewritten: list[str] = []
    for old_path, new_path, hunks in file_diffs:
        target_rel = _normalize_patch_path(new_path)
        if target_rel is None:
            return None
        source_rel = _normalize_patch_path(old_path)
        if source_rel is None:
            original_lines: list[str] = []
        else:
            source_file = workspace_path / source_rel
            if source_file.exists():
                original_lines = source_file.read_text(encoding="utf-8").splitlines()
            else:
                original_lines = []
        result_lines: list[str] = []
        orig_index = 0
        for start_old, len_old, start_new, len_new, hunk_lines in hunks:
            zero_based = max(start_old - 1, 0)
            zero_based = min(zero_based, len(original_lines))
            if zero_based > orig_index:
                result_lines.extend(original_lines[orig_index:zero_based])
                orig_index = zero_based
            for line in hunk_lines:
                if not line:
                    result_lines.append("")
                    continue
                tag = line[0]
                text = line[1:] if len(line) > 1 else ""
                if tag == " ":
                    result_lines.append(text)
                    if orig_index < len(original_lines):
                        orig_index += 1
                elif tag == "-":
                    if orig_index < len(original_lines):
                        orig_index += 1
                elif tag == "+":
                    result_lines.append(text)
                elif tag == "\\":
                    continue
                else:
                    continue
        result_lines.extend(original_lines[orig_index:])
        content = "\n".join(result_lines)
        if result_lines:
            content += "\n"
        target_file = workspace_path / target_rel
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8")
        rewritten.append(target_rel)
    return rewritten


def _parse_loose_unified_diff(cleaned_patch: str):
    lines = cleaned_patch.splitlines()
    files = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git"):
            i += 1
            continue
        if not line.startswith("--- "):
            i += 1
            continue
        old_path = line[4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            return None
        new_path = lines[i][4:].strip()
        i += 1
        hunks = []
        while i < len(lines):
            current = lines[i]
            if current.startswith("diff --git") or current.startswith("--- "):
                break
            if current.startswith("@@"):
                header = current
                i += 1
                hunk_ops: list[tuple[str, str]] = []
                while i < len(lines):
                    candidate = lines[i]
                    if candidate.startswith("diff --git") or candidate.startswith("--- ") or candidate.startswith("@@"):
                        break
                    if candidate.startswith("\\"):
                        i += 1
                        continue
                    if not candidate:
                        hunk_ops.append((" ", ""))
                        i += 1
                        continue
                    prefix = candidate[0]
                    if prefix in {"+", "-", " "}:
                        hunk_ops.append((prefix, candidate[1:]))
                    else:
                        hunk_ops.append((" ", candidate))
                    i += 1
                if hunk_ops:
                    hunks.append((header, hunk_ops))
                continue
            i += 1
        files.append((old_path, new_path, hunks))
    return files or None


def _find_subsequence(haystack: list[str], needle: list[str], start: int) -> int | None:
    if not needle:
        return start
    end_limit = len(haystack) - len(needle)
    if end_limit < 0:
        return None
    start = max(start, 0)
    for idx in range(start, end_limit + 1):
        if haystack[idx : idx + len(needle)] == needle:
            return idx
    return None


_COMPARE_STRATEGIES: tuple[Callable[[str], str], ...] = (
    lambda s: s,
    lambda s: s.expandtabs(4),
    lambda s: re.sub(r"\s+", " ", s.strip()),
)


def _lines_equivalent(left: str, right: str) -> bool:
    if left == right:
        return True
    for transform in _COMPARE_STRATEGIES:
        if transform(left) == transform(right):
            return True
    return False


def _locate_hunk(updated_lines: list[str], pattern: list[str], search_start: int) -> int | None:
    for transform in _COMPARE_STRATEGIES:
        haystack = [transform(line) for line in updated_lines]
        needle = [transform(line) for line in pattern]
        start_index = _find_subsequence(haystack, needle, search_start)
        if start_index is None and search_start:
            start_index = _find_subsequence(haystack, needle, 0)
        if start_index is not None:
            return start_index
    if pattern:
        pattern_text = "\n".join(pattern)
        best_index = None
        best_ratio = 0.0
        window = len(pattern)
        if window <= 0:
            return search_start
        lower_bound = max(search_start - 50, 0)
        upper_bound = len(updated_lines) - window + 1
        if upper_bound < 0:
            return None
        for idx in range(lower_bound, upper_bound):
            segment = "\n".join(updated_lines[idx : idx + window])
            ratio = difflib.SequenceMatcher(None, pattern_text, segment).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_index = idx
        min_ratio = 0.9
        if window <= 6:
            min_ratio = 0.8
        elif window <= 10:
            min_ratio = 0.85
        if best_index is not None and best_ratio >= min_ratio:
            return best_index
    return None


def _apply_loose_unified_diff(file_diffs, workspace_path: Path) -> list[str] | None:
    planned_writes: list[tuple[str, str]] = []
    for old_path, new_path, hunks in file_diffs:
        if not hunks:
            continue
        target_rel = _normalize_patch_path(new_path)
        if target_rel is None:
            return None
        source_rel = _normalize_patch_path(old_path)
        source_candidate = source_rel or target_rel
        source_path = workspace_path / source_candidate
        if source_path.exists():
            original_text = source_path.read_text(encoding="utf-8")
        else:
            original_text = ""
        original_lines = original_text.splitlines()
        updated_lines = original_lines[:]
        search_start = 0
        for _header, hunk_ops in hunks:
            if not any(tag in ("+", "-") for tag, _ in hunk_ops):
                continue
            pattern = [text for tag, text in hunk_ops if tag in (" ", "-")]
            start_index = _locate_hunk(updated_lines, pattern, search_start)
            if start_index is None:
                if all(tag == "-" for tag, _ in hunk_ops if tag in (" ", "-")):
                    start_index = search_start
                else:
                    return None
            new_segment: list[str] = []
            cursor = start_index
            for tag, text in hunk_ops:
                if tag == " ":
                    if text == "":
                        while cursor < len(updated_lines) and updated_lines[cursor].strip() == "":
                            new_segment.append(updated_lines[cursor])
                            cursor += 1
                        continue
                    search_cursor = cursor
                    temp_buffer: list[str] = []
                    found = False
                    while search_cursor < len(updated_lines):
                        existing_line = updated_lines[search_cursor]
                        if _lines_equivalent(text, existing_line):
                            new_segment.extend(temp_buffer)
                            new_segment.append(existing_line)
                            cursor = search_cursor + 1
                            found = True
                            break
                        if existing_line.strip() == "":
                            temp_buffer.append(existing_line)
                            search_cursor += 1
                            continue
                        break
                    if not found:
                        return None
                elif tag == "-":
                    temp_segment: list[str] = []
                    temp_cursor = cursor
                    removed = False
                    while temp_cursor < len(updated_lines):
                        existing_line = updated_lines[temp_cursor]
                        if _lines_equivalent(text, existing_line):
                            cursor = temp_cursor + 1
                            new_segment.extend(temp_segment)
                            removed = True
                            break
                        if existing_line.strip() == "":
                            temp_segment.append(existing_line)
                            temp_cursor += 1
                            continue
                        break
                    if not removed:
                        # minus line not present; leave original text untouched
                        continue
                elif tag == "+":
                    new_segment.append(text)
                    if cursor < len(updated_lines) and _lines_equivalent(text, updated_lines[cursor]):
                        cursor += 1
                else:
                    return None
            updated_lines = updated_lines[:start_index] + new_segment + updated_lines[cursor:]
            search_start = start_index + len(new_segment)
        updated_text = "\n".join(updated_lines)
        if updated_lines:
            updated_text += "\n"
        planned_writes.append((target_rel, updated_text))
    if not planned_writes:
        return None
    rewritten: list[str] = []
    for rel_path, content in planned_writes:
        target_path = workspace_path / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        rewritten.append(rel_path)
    return rewritten


def _apply_diff_rewrite_fallback(
    cleaned_patch: str,
    workspace_path: Path,
    *,
    allow_strict_parse: bool,
) -> list[str] | None:
    rewrites = _extract_full_file_rewrites(cleaned_patch)
    if rewrites:
        rewritten_files: list[str] = []
        for rel_path, content in rewrites.items():
            target_path = workspace_path / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            rewritten_files.append(rel_path)
        return rewritten_files

    loose_parsed = _parse_loose_unified_diff(cleaned_patch)
    if loose_parsed:
        rewritten = _apply_loose_unified_diff(loose_parsed, workspace_path)
        if rewritten:
            return rewritten
        return None

    if not allow_strict_parse:
        return None

    parsed = _parse_unified_diff(cleaned_patch)
    if parsed:
        return _apply_parsed_unified_diff(parsed, workspace_path)
    return None


def _should_attempt_diff_rewrite(diagnostic: str) -> bool:
    lowered = diagnostic.lower()
    return any(
        keyword in lowered
        for keyword in (
            "malformed patch",
            "unexpected end of file",
            "hunks ignored",
            "no file to patch",
            # Accept both singular and plural forms reported by different patch versions
            "hunk failed",
            "hunks failed",
            # Generic phrasing used by GNU/BSD patch output
            "failed while patching",
            # Flexible match for counts: e.g., "1 out of 2 hunks failed"
            "out of",
            "can't seem to find a patch",
            "cannot find a patch",
        )
    )


def apply_patch(
    patch_text: str,
    workspace_path: Path,
    *,
    allow_diff_rewrite_fallback: bool,
    attempt_summary: dict,
    attempt_dir: Path,
) -> None:
    cleaned_patch, git_style, synthetic_headers = clean_patch_text(patch_text)
    patch_bytes = cleaned_patch.encode("utf-8")

    patch_args = ["patch", "--force", "-p1" if git_style else "-p0"]
    dry_run_args = ["patch", "--dry-run", "--force", "-p1" if git_style else "-p0"]

    dry_run = _run_patch_command(dry_run_args, patch_bytes, workspace_path)
    if dry_run.returncode != 0:
        stdout_text = dry_run.stdout.decode()
        stderr_text = dry_run.stderr.decode()
        diagnostic = f"{stdout_text}\n{stderr_text}" if stdout_text or stderr_text else ""
        if allow_diff_rewrite_fallback and _should_attempt_diff_rewrite(diagnostic):
            rewritten_files = _apply_diff_rewrite_fallback(
                cleaned_patch,
                workspace_path,
                allow_strict_parse=not synthetic_headers,
            )
            if rewritten_files:
                attempt_summary["diff_rewrite_fallback_used"] = True
                attempt_summary["diff_rewrite_files"] = sorted(rewritten_files)
                store_text(
                    attempt_dir / "diff_rewrite_fallback.log",
                    "Applied diff rewrite fallback to:\n" + "\n".join(sorted(rewritten_files)),
                )
                return
        raise HarnessError(f"Patch failed dry-run validation:\nSTDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}")

    apply_process = _run_patch_command(patch_args, patch_bytes, workspace_path)
    if apply_process.returncode != 0:
        raise HarnessError(
            "Failed to apply patch:\n"
            f"STDOUT:\n{apply_process.stdout.decode()}\n"
            f"STDERR:\n{apply_process.stderr.decode()}"
        )


def run_evaluation(
    command: list[str],
    workspace_path: Path,
    timeout: int,
    env_updates: dict[str, str] | None = None,
    working_dir: str | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    if env_updates:
        env.update(env_updates)
    if command[:2] == ["go", "test"]:
        go_root = workspace_path
        if working_dir:
            go_root = workspace_path / working_dir
        go_root = go_root.resolve()
        if not any((go_root / candidate).exists() for candidate in ("go.mod", "go.work")):
            env.setdefault("GO111MODULE", "off")
    workdir = workspace_path if working_dir is None else workspace_path / working_dir

    return secure_run(
        command,
        workspace_path=workspace_path,
        timeout=timeout,
        env=env,
        cwd=workdir,
    )


def truncate_log(text: str) -> str:
    if len(text) <= MAX_LOG_CHARS:
        return text
    return text[:MAX_LOG_CHARS] + "\n...[truncated]"


def create_run_directory(output_root: Path) -> Path:
    timestamp = dt.datetime.now(dt.UTC).strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = output_root / f"{timestamp}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def store_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def evaluate_attempt(
    task_id: str,
    metadata: dict,
    model: str,
    sample_index: int,
    temperature: float,
    max_tokens: int,
    preferred_provider: str | None,
    thinking_level: str | None,
    model_metadata: dict[str, dict[str, Any]],
    include_tests: bool,
    install_deps_flag: bool,
    response_override: str | None,
    allow_incomplete_diffs: bool,
    allow_diff_rewrite_fallback: bool,
    run_dir: Path,
) -> dict:
    prompt = build_prompt(task_id, metadata, include_tests=include_tests)

    # Use the requested thinking level for artifact directory suffix so that
    # base/low/medium/high attempts never collide, even when reasoning is unsupported.
    def _sanitize_level_for_dir(level: str | None) -> str:
        if not level:
            return "base"
        # Keep it filesystem-friendly
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(level))
        return safe.strip("-_") or "base"

    level_suffix = _sanitize_level_for_dir(thinking_level)
    attempt_id = f"{task_id}__{model.replace('/', '_')}__sample{sample_index:02d}__lvl_{level_suffix}"
    attempt_dir = run_dir / attempt_id
    store_text(attempt_dir / "prompt.txt", prompt)
    attempt_timer = time.perf_counter()
    api_latency = None
    usage = None

    attempt_summary = {
        "task_id": task_id,
        "model": model,
        "provider": preferred_provider,
        "sample_index": sample_index,
        "status": "error",
        "return_code": None,
        "error": None,
        "attempt_dir": str(attempt_dir.relative_to(run_dir)),
        "attempt_dir_abs": str(attempt_dir),
    }

    model_info = model_metadata.get(model) or {}
    supported_params = {param.lower() for param in model_info.get("supported_parameters", []) if isinstance(param, str)}
    if thinking_level:
        attempt_summary["thinking_level_requested"] = thinking_level
        attempt_summary["thinking_level_supported"] = "reasoning" in supported_params
        if "reasoning" in supported_params:
            attempt_summary["thinking_level_applied"] = thinking_level

    try:
        if response_override is not None:
            raw_response = response_override
            response_meta = None
            api_latency = None
        else:
            if _is_lmstudio_model(model):
                raw_response, response_meta, api_latency = call_lmstudio(
                    prompt,
                    _normalize_lmstudio_model_id(model),
                    temperature,
                    max_tokens,
                )
            else:
                raw_response, response_meta, api_latency = call_openrouter(
                    prompt,
                    model,
                    temperature,
                    max_tokens,
                    preferred_provider,
                    thinking_level=thinking_level if "reasoning" in supported_params else None,
                    model_info=model_info,
                )
    except APIError as exc:
        # API errors (rate limits, empty responses, provider failures) are transient
        # and should not count against LLM evaluation
        error_type = type(exc).__name__
        attempt_summary.update(
            {
                "status": "api_error",
                "error": str(exc),
                "error_type": error_type,
                "is_transient": True,
            }
        )
        store_text(attempt_dir / "error.log", f"[{error_type}] {exc}")
        return attempt_summary
    except HarnessError as exc:
        attempt_summary.update({"error": str(exc)})
        store_text(attempt_dir / "error.log", str(exc))
        return attempt_summary

    store_text(attempt_dir / "response.txt", raw_response)
    if response_meta is not None:
        store_text(attempt_dir / "response.json", json.dumps(response_meta, indent=2))
        usage = response_meta.get("usage")

    workspace_path: Path | None = None
    try:
        patch_text = extract_patch(raw_response, allow_incomplete_diffs=allow_incomplete_diffs)
        store_text(attempt_dir / "patch.diff", patch_text)

        workspace_path = prepare_run_directory(task_id, metadata)
        if install_deps_flag:
            install_requirements(workspace_path)
        apply_patch(
            patch_text,
            workspace_path,
            allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
            attempt_summary=attempt_summary,
            attempt_dir=attempt_dir,
        )

        eval_config = metadata.get("eval", {})
        timeout = eval_config.get("timeout_seconds", 300)
        command = eval_config.get("command", ["pytest", "-q"])
        env_updates = eval_config.get("env")
        working_dir = eval_config.get("working_dir")
        process = run_evaluation(command, workspace_path, timeout, env_updates, working_dir)

        stdout_text = truncate_log(process.stdout.decode("utf-8"))
        stderr_text = truncate_log(process.stderr.decode("utf-8"))
        store_text(attempt_dir / "stdout.log", stdout_text)
        store_text(attempt_dir / "stderr.log", stderr_text)

        attempt_summary.update(
            {
                "status": "passed" if process.returncode == 0 else "failed",
                "return_code": process.returncode,
                "eval_command": command,
                "eval_timeout_seconds": timeout,
                "eval_working_dir": str((workspace_path / working_dir).resolve())
                if working_dir
                else str(workspace_path),
                "eval_env_overrides": env_updates or {},
                "stdout_excerpt": stdout_text[:2000],
                "stderr_excerpt": stderr_text[:2000],
            }
        )

    except HarnessError as exc:
        attempt_summary.update({"status": "error", "error": str(exc)})
        store_text(attempt_dir / "error.log", str(exc))
    finally:
        if workspace_path is not None:
            shutil.rmtree(workspace_path.parent, ignore_errors=True)

    attempt_summary["usage"] = usage
    attempt_summary["api_latency_seconds"] = api_latency
    attempt_summary["duration_seconds"] = time.perf_counter() - attempt_timer
    return attempt_summary


def compute_metrics(attempts: Iterable[dict], models: list[str], tasks: list[str], samples: int) -> dict:
    def _estimate_pass_at_k(total: int, correct: int, k: int) -> float | None:
        if total <= 0 or k <= 0:
            return None
        k = min(k, total)
        if correct <= 0:
            return 0.0
        if correct >= total:
            return 1.0
        return 1.0 - math.comb(total - correct, k) / math.comb(total, k)

    # Convert to list to allow multiple iterations
    attempts_list = list(attempts)

    # Count api_errors separately for reporting
    api_error_count = sum(1 for a in attempts_list if a.get("status") == "api_error")

    metrics: dict[str, dict[str, float | None]] = {
        "model_accuracy": {},
        "model_attempt_success": {},
    }
    pass_at_1: dict[str, float | None] = {}
    pass_at_k: dict[str, float | None] = {}
    api_errors_by_model: dict[str, int] = {}

    for model in models:
        model_attempts = [a for a in attempts_list if a["model"] == model]
        # Exclude api_error attempts from LLM evaluation metrics
        evaluable_attempts = [a for a in model_attempts if a.get("status") != "api_error"]
        api_errors_by_model[model] = len(model_attempts) - len(evaluable_attempts)

        if not evaluable_attempts:
            metrics["model_accuracy"][model] = None
            metrics["model_attempt_success"][model] = None
            pass_at_1[model] = None
            pass_at_k[model] = None
            continue

        # Attempt-level success rate (excluding api_error)
        successes = sum(1 for a in evaluable_attempts if a["status"] == "passed")
        metrics["model_attempt_success"][model] = successes / len(evaluable_attempts)

        task_pass_at_1: list[float] = []
        task_pass_at_k: list[float] = []

        for task in tasks:
            # Exclude api_error attempts from pass@k calculation
            task_attempts = [a for a in evaluable_attempts if a["task_id"] == task]
            if not task_attempts:
                continue
            total = len(task_attempts)
            correct = sum(1 for a in task_attempts if a["status"] == "passed")
            task_pass_at_1.append(_estimate_pass_at_k(total, correct, 1) or 0.0)
            task_pass_at_k.append(_estimate_pass_at_k(total, correct, min(samples, total)) or 0.0)

        metrics["model_accuracy"][model] = sum(task_pass_at_k) / len(task_pass_at_k) if task_pass_at_k else None
        pass_at_1[model] = sum(task_pass_at_1) / len(task_pass_at_1) if task_pass_at_1 else None
        pass_at_k[model] = sum(task_pass_at_k) / len(task_pass_at_k) if task_pass_at_k else None

    overall_accuracy_values = [v for v in metrics["model_accuracy"].values() if v is not None]
    overall_attempt_success_values = [v for v in metrics["model_attempt_success"].values() if v is not None]

    overall = {
        "macro_model_accuracy": sum(overall_accuracy_values) / len(overall_accuracy_values)
        if overall_accuracy_values
        else None,
        "macro_attempt_success": sum(overall_attempt_success_values) / len(overall_attempt_success_values)
        if overall_attempt_success_values
        else None,
    }

    metrics["pass_at_1"] = pass_at_1
    metrics["pass_at_k"] = pass_at_k
    metrics["overall"] = overall
    metrics["api_errors_excluded"] = api_error_count
    metrics["api_errors_by_model"] = api_errors_by_model
    return metrics


def _bucket_level_for_metrics(attempt: dict, default_level: str | None = None) -> str:
    # Mirror server/database._determine_model_level logic for consistency
    applied = attempt.get("thinking_level_applied")
    if applied:
        return str(applied)
    if attempt.get("thinking_level_supported") is False and attempt.get("thinking_level_requested"):
        return f"unsupported ({attempt.get('thinking_level_requested')})"
    if default_level:
        return str(default_level)
    return "base"


def compute_metrics_by_thinking_level(
    attempts: Iterable[dict],
    models: list[str],
    tasks: list[str],
    samples: int,
    default_level: str | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    def _estimate_pass_at_k(total: int, correct: int, k: int) -> float | None:
        if total <= 0 or k <= 0:
            return None
        k = min(k, total)
        if correct <= 0:
            return 0.0
        if correct >= total:
            return 1.0
        return 1.0 - math.comb(total - correct, k) / math.comb(total, k)

    result: dict[str, dict[str, dict[str, float]]] = {}
    # Pre-index attempts per (model, level)
    per_model_level: dict[str, dict[str, list[dict]]] = {}
    for a in attempts:
        model = a.get("model")
        if not model:
            continue
        level = _bucket_level_for_metrics(a, default_level)
        per_model_level.setdefault(model, {}).setdefault(level, []).append(a)

    for model, level_map in per_model_level.items():
        result[model] = {}
        for level, level_attempts in level_map.items():
            # Attempt-level counts (including api_error for transparency)
            total_all = len(level_attempts)
            api_errored = sum(1 for x in level_attempts if (x.get("status") or "").lower() == "api_error")

            # Exclude api_error from LLM evaluation metrics
            evaluable_attempts = [x for x in level_attempts if (x.get("status") or "").lower() != "api_error"]
            total = len(evaluable_attempts)
            passed = sum(1 for x in evaluable_attempts if (x.get("status") or "").lower() == "passed")
            failed = sum(1 for x in evaluable_attempts if (x.get("status") or "").lower() == "failed")
            errored = sum(1 for x in evaluable_attempts if (x.get("status") or "").lower() == "error")

            # Task-level pass@k accuracy for this level (excluding api_error)
            tasks_for_level: dict[str, list[dict]] = {}
            for x in evaluable_attempts:
                tid = x.get("task_id")
                if not tid:
                    continue
                tasks_for_level.setdefault(tid, []).append(x)
            task_ids = list(tasks_for_level.keys())
            pass_at_1_values: list[float] = []
            pass_at_k_values: list[float] = []
            for tid in task_ids:
                attempts_for_task = tasks_for_level[tid]
                task_total = len(attempts_for_task)
                correct = sum(1 for a in attempts_for_task if (a.get("status") or "").lower() == "passed")
                pass_at_1_values.append(_estimate_pass_at_k(task_total, correct, 1) or 0.0)
                pass_at_k_values.append(_estimate_pass_at_k(task_total, correct, min(samples, task_total)) or 0.0)

            task_count = len(task_ids)
            model_accuracy = (sum(pass_at_k_values) / task_count) if task_count else None
            attempt_success = (passed / total) if total else None
            pass_at_1 = (sum(pass_at_1_values) / task_count) if task_count else None
            pass_at_k = (sum(pass_at_k_values) / task_count) if task_count else None

            result[model][level] = {
                "attempts": total,
                "attempts_including_api_errors": total_all,
                "passed": passed,
                "failed": failed,
                "error": errored,
                "api_error": api_errored,
                "model_attempt_success": attempt_success,
                "model_accuracy": model_accuracy,
                "pass_at_1": pass_at_1,
                "pass_at_k": pass_at_k,
            }
    return result


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value))
    return safe.strip("._-") or "default"


def update_task_latest(task_id: str, attempt_summary: dict) -> None:
    RUN_ARTIFACTS.mkdir(exist_ok=True)
    model = _safe_name(attempt_summary.get("model", "unknown"))
    output_path = RUN_ARTIFACTS / f"{task_id}__{model}_latest.json"

    legacy_path = RUN_ARTIFACTS / f"{task_id}_latest.json"
    index_path = RUN_ARTIFACTS / "latest_index.json"

    status_rank = {"passed": 2, "failed": 1, "error": 0}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
        if existing is not None:
            current_rank = status_rank.get(existing.get("status"), -1)
            new_rank = status_rank.get(attempt_summary.get("status"), -1)
            if current_rank > new_rank:
                return
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(attempt_summary, fh, indent=2)

    # Maintain an index of latest artifacts to avoid legacy task-only bleed.
    index_entry = {
        "task": task_id,
        "model": attempt_summary.get("model"),
        "path": output_path.name,
        "legacy_path": legacy_path.name,
    }
    try:
        current_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except json.JSONDecodeError:
        current_index = {}
    current_index[f"{task_id}::{model}"] = index_entry
    store_text(index_path, json.dumps(current_index, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenRouter benchmark harness")
    parser.add_argument("--task", help="Evaluate a single task identifier")
    parser.add_argument("--tasks", nargs="+", help="Evaluate multiple tasks or 'all' for every available task")
    parser.add_argument("--models", nargs="+", default=[DEFAULT_MODEL], help="List of OpenRouter model identifiers")
    parser.add_argument("--samples", type=int, default=1, help="Number of samples per task/model")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--provider", help="Prefer a specific OpenRouter provider (e.g., Groq)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--thinking-level",
        dest="thinking_level",
        help="Optional reasoning effort (e.g., low, medium, high) for thinking-capable models",
    )
    parser.add_argument(
        "--include-thinking-variants",
        action="store_true",
        help="Also evaluate :thinking variants for models that support them.",
    )
    parser.add_argument(
        "--sweep-thinking-levels",
        action="store_true",
        help="Evaluate base plus low/medium/high thinking levels where supported.",
    )
    parser.add_argument("--response-file", type=Path, help="Replay a stored model response (single-task runs only)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts only, skip model calls and evaluation")
    parser.add_argument("--include-tests", action="store_true", help="Include test files in the model prompt context")
    parser.add_argument(
        "--install-deps", action="store_true", help="Install requirements.txt inside each attempt workspace"
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_ARTIFACTS, help="Directory to write run artifacts")
    parser.add_argument(
        "--allow-incomplete-diffs",
        dest="allow_incomplete_diffs",
        action="store_true",
        help="Allow truncated diff fences when the heuristic and dry-run validation succeed",
    )
    parser.add_argument(
        "--no-allow-incomplete-diffs",
        dest="allow_incomplete_diffs",
        action="store_false",
        help="Disallow truncated diff fences regardless of configuration",
    )
    parser.add_argument(
        "--allow-diff-rewrite-fallback",
        dest="allow_diff_rewrite_fallback",
        action="store_true",
        help="Allow rewrite fallback for malformed diffs emitted by the model",
    )
    parser.add_argument(
        "--no-allow-diff-rewrite-fallback",
        dest="allow_diff_rewrite_fallback",
        action="store_false",
        help="Disable rewrite fallback for malformed diffs",
    )
    parser.add_argument(
        "--resume-from",
        dest="resume_from",
        type=Path,
        help="Resume from a previous run by re-running only api_error attempts. "
        "Provide run directory path (e.g., runs/run_20251222T193052Z_a2ca88)",
    )
    parser.add_argument(
        "--retry-api-errors",
        dest="retry_api_errors",
        action="store_true",
        help="When used with --resume-from, retry only api_error attempts",
    )
    parser.add_argument(
        "--resume-incomplete",
        dest="resume_incomplete",
        action="store_true",
        help="When used with --resume-from, resume only incomplete attempts (started but didn't finish)",
    )
    parser.set_defaults(allow_incomplete_diffs=None, allow_diff_rewrite_fallback=None)
    return parser.parse_args(argv)


def load_failed_attempts(run_dir: Path) -> list[dict]:
    """Load attempts from a previous run that failed (error, fail, api_error).

    Supports both completed runs (with attempts.json/summary.json) and
    incomplete runs (by scanning attempt directories).
    """
    failed_statuses = {"error", "fail", "failed", "api_error", "exception"}
    attempts_file = run_dir / "attempts.json"
    summary_file = run_dir / "summary.json"

    if attempts_file.exists():
        with attempts_file.open("r", encoding="utf-8") as f:
            attempts = json.load(f)
        return [a for a in attempts if a.get("status", "").lower() in failed_statuses]

    if summary_file.exists():
        with summary_file.open("r", encoding="utf-8") as f:
            summary = json.load(f)
            attempts = summary.get("attempts", [])
        return [a for a in attempts if a.get("status", "").lower() in failed_statuses]

    return []


def load_api_error_attempts(run_dir: Path) -> list[dict]:
    """Load attempts from a previous run that had api_error status.

    Supports both completed runs (with attempts.json/summary.json) and
    incomplete runs (by scanning error.log files in attempt directories).
    """
    attempts_file = run_dir / "attempts.json"
    summary_file = run_dir / "summary.json"

    if attempts_file.exists():
        with attempts_file.open("r", encoding="utf-8") as f:
            attempts = json.load(f)
        # Filter to only api_error attempts
        return [a for a in attempts if a.get("status") == "api_error"]

    if summary_file.exists():
        with summary_file.open("r", encoding="utf-8") as f:
            summary = json.load(f)
            attempts = summary.get("attempts", [])
        # Filter to only api_error attempts
        return [a for a in attempts if a.get("status") == "api_error"]

    # For incomplete runs, scan attempt directories for error.log files
    # that contain API error patterns
    api_error_patterns = [
        "RateLimitError",
        "EmptyResponseError",
        "ProviderError",
        "rate limit",
        "429",
        "empty content",
        "OpenRouter request failed (429)",
        "OpenRouter returned empty content",
    ]

    api_error_attempts: list[dict] = []
    for attempt_dir in run_dir.iterdir():
        if not attempt_dir.is_dir():
            continue
        error_log = attempt_dir / "error.log"
        if not error_log.exists():
            continue

        error_content = error_log.read_text(encoding="utf-8")
        is_api_error = any(pattern in error_content for pattern in api_error_patterns)
        if not is_api_error:
            continue

        # Parse attempt info from directory name
        # Format: {task_id}__{model}__sample{N}__lvl_{level}
        dir_name = attempt_dir.name
        parts = dir_name.split("__")
        if len(parts) >= 3:
            task_id = parts[0]
            model = parts[1].replace("_", "/")  # Reverse the / -> _ conversion
            sample_match = re.search(r"sample(\d+)", parts[2])
            sample_index = int(sample_match.group(1)) if sample_match else 0
            level_match = re.search(r"lvl_(.+)", dir_name)
            thinking_level = level_match.group(1) if level_match else None
            if thinking_level == "base":
                thinking_level = None

            api_error_attempts.append(
                {
                    "task_id": task_id,
                    "model": model,
                    "sample_index": sample_index,
                    "thinking_level_requested": thinking_level,
                    "status": "api_error",
                    "error": error_content.strip(),
                    "attempt_dir": str(attempt_dir.relative_to(run_dir)),
                }
            )

    if not api_error_attempts and not any(run_dir.iterdir()):
        raise HarnessError(
            f"Cannot find attempts.json, summary.json, or attempt directories in {run_dir}. "
            "Make sure the run directory is correct."
        )

    return api_error_attempts


def _load_run_summary_if_exists(run_dir: Path) -> dict[str, Any]:
    summary_file = run_dir / "summary.json"
    if not summary_file.exists():
        return {}
    with summary_file.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    return summary if isinstance(summary, dict) else {}


def _load_all_attempts_for_run(run_dir: Path, summary: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    attempts_file = run_dir / "attempts.json"
    if attempts_file.exists():
        with attempts_file.open("r", encoding="utf-8") as f:
            attempts = json.load(f)
        if isinstance(attempts, list):
            return [a for a in attempts if isinstance(a, dict)]
        return []

    summary_data = summary if summary is not None else _load_run_summary_if_exists(run_dir)
    attempts = summary_data.get("attempts", []) if isinstance(summary_data, dict) else []
    if isinstance(attempts, list):
        return [a for a in attempts if isinstance(a, dict)]
    return []


def _attempt_identity_key(attempt: dict[str, Any]) -> tuple[str | None, str | None, int, str]:
    sample_index_raw = attempt.get("sample_index", 0)
    try:
        sample_index = int(sample_index_raw)
    except (TypeError, ValueError):
        sample_index = 0

    level = (
        attempt.get("thinking_level_applied")
        or attempt.get("thinking_level_requested")
        or attempt.get("thinking_level")
        or "base"
    )
    return (attempt.get("task_id"), attempt.get("model"), sample_index, str(level))


def _merge_attempt_retries(
    original_attempts: list[dict[str, Any]],
    replacement_pairs: Iterable[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    merged_attempts = list(original_attempts)
    index_by_key = {_attempt_identity_key(attempt): idx for idx, attempt in enumerate(merged_attempts)}

    for original_attempt, retried_attempt in replacement_pairs:
        original_key = _attempt_identity_key(original_attempt)
        idx = index_by_key.get(original_key)
        if idx is None:
            retried_key = _attempt_identity_key(retried_attempt)
            idx = index_by_key.get(retried_key)
            if idx is None:
                merged_attempts.append(retried_attempt)
                index_by_key[retried_key] = len(merged_attempts) - 1
                continue
        merged_attempts[idx] = retried_attempt
        index_by_key[_attempt_identity_key(retried_attempt)] = idx

    return merged_attempts


def _ordered_unique_strings(values: Iterable[Any]) -> list[str]:
    ordered = dict.fromkeys(value for value in values if isinstance(value, str) and value)
    return list(ordered)


def _compute_attempt_totals(attempts: Iterable[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    total_duration = 0.0
    total_api_latency = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    for attempt in attempts:
        duration = attempt.get("duration_seconds")
        if duration is not None:
            try:
                total_duration += float(duration)
            except (TypeError, ValueError):
                pass

        api_latency = attempt.get("api_latency_seconds")
        if api_latency is not None:
            try:
                total_api_latency += float(api_latency)
            except (TypeError, ValueError):
                pass

        usage = attempt.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = usage.get("output_tokens")

        if prompt_tokens is not None:
            try:
                total_prompt_tokens += int(prompt_tokens)
            except (TypeError, ValueError):
                pass
        if completion_tokens is not None:
            try:
                total_completion_tokens += int(completion_tokens)
            except (TypeError, ValueError):
                pass

        cost = attempt.get("cost_usd")
        if cost is not None:
            try:
                total_cost += float(cost)
            except (TypeError, ValueError):
                pass

    return {
        "timing": {
            "total_duration_seconds": total_duration,
            "total_api_latency_seconds": total_api_latency,
        },
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost, 6),
        },
    }


def retry_api_error_attempts(
    *,
    original_run_dir: Path,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    preferred_provider: str | None = None,
    include_tests: bool = False,
    install_deps: bool = False,
    output_dir: Path = RUN_ARTIFACTS,
    allow_incomplete_diffs: bool | None = None,
    allow_diff_rewrite_fallback: bool | None = None,
    progress_callback: Callable[[str, str, int, dict], None] | None = None,
    filter_task_id: str | None = None,
    filter_model: str | None = None,
    filter_sample_index: int | None = None,
    run_id: str | None = None,
) -> dict:
    """
    Retry only the api_error attempts from a previous run.
    Creates a new run directory with retried attempts merged with successful ones.

    Optional filters:
      filter_task_id: Only retry attempts for this specific task
      filter_model: Only retry attempts for this specific model
      filter_sample_index: Only retry attempts with this sample index
    """
    api_error_attempts = load_api_error_attempts(original_run_dir)
    if not api_error_attempts:
        logger.info("No api_error attempts found in %s. Nothing to retry.", original_run_dir)
        return {"retried": 0, "message": "No api_error attempts to retry"}

    # Apply filters if specified
    if filter_task_id is not None:
        api_error_attempts = [a for a in api_error_attempts if a.get("task_id") == filter_task_id]
    if filter_model is not None:
        api_error_attempts = [a for a in api_error_attempts if a.get("model") == filter_model]
    if filter_sample_index is not None:
        api_error_attempts = [a for a in api_error_attempts if a.get("sample_index") == filter_sample_index]

    if not api_error_attempts:
        logger.info("No api_error attempts match the filter criteria. Nothing to retry.")
        return {"retried": 0, "message": "No matching api_error attempts to retry"}

    logger.info("Found %d api_error attempts to retry", len(api_error_attempts))

    original_summary = _load_run_summary_if_exists(original_run_dir)
    original_attempts = _load_all_attempts_for_run(original_run_dir, original_summary)

    # Create new run directory (use provided run_id if given)
    output_dir = Path(output_dir)
    RUN_ARTIFACTS.mkdir(exist_ok=True)
    if run_id:
        run_dir = output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = create_run_directory(output_dir)
        run_id = run_dir.name

    # Collect unique models for metadata fetch
    retry_models = list({a["model"] for a in api_error_attempts})
    model_metadata = fetch_model_metadata(retry_models)

    if allow_incomplete_diffs is None:
        allow_incomplete_diffs = DEFAULT_ALLOW_INCOMPLETE_DIFFS
    if allow_diff_rewrite_fallback is None:
        allow_diff_rewrite_fallback = DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK

    retried_attempts: list[dict] = []
    replacement_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for i, original_attempt in enumerate(api_error_attempts, 1):
        task_id = original_attempt["task_id"]
        model = original_attempt["model"]
        sample_index = original_attempt.get("sample_index", 0)
        thinking_level = original_attempt.get("thinking_level_applied") or original_attempt.get(
            "thinking_level_requested"
        )

        logger.info(
            "[%d/%d] Retrying %s with %s (sample %s)",
            i,
            len(api_error_attempts),
            task_id,
            model,
            sample_index,
        )

        try:
            metadata = load_metadata(task_id)
        except HarnessError as e:
            logger.warning("Skipping %s: %s", task_id, e)
            continue

        attempt_summary = evaluate_attempt(
            task_id=task_id,
            metadata=metadata,
            model=model,
            sample_index=sample_index,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_provider=preferred_provider or original_attempt.get("provider"),
            thinking_level=thinking_level,
            model_metadata=model_metadata,
            include_tests=include_tests,
            install_deps_flag=install_deps,
            response_override=None,
            allow_incomplete_diffs=allow_incomplete_diffs,
            allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
            run_dir=run_dir,
        )
        retried_attempts.append(attempt_summary)
        replacement_pairs.append((original_attempt, attempt_summary))
        update_task_latest(task_id, attempt_summary)

        if progress_callback:
            progress_callback(model=model, task_id=task_id, sample_index=sample_index, summary=attempt_summary)

        status = attempt_summary.get("status", "unknown")
        logger.info("Result: %s", status)

    # Build merged view so accuracy reflects the full run with replacements.
    all_attempts = (
        _merge_attempt_retries(original_attempts, replacement_pairs) if original_attempts else list(retried_attempts)
    )
    summary_tasks = _ordered_unique_strings(original_summary.get("tasks", [])) or _ordered_unique_strings(
        a.get("task_id") for a in all_attempts
    )
    summary_models = _ordered_unique_strings(original_summary.get("models", [])) or _ordered_unique_strings(
        a.get("model") for a in all_attempts
    )
    samples = int(original_summary.get("samples", 1) or 1)
    status_counts = Counter(a.get("status") for a in all_attempts)
    totals = _compute_attempt_totals(all_attempts)

    summary = {
        "timestamp_utc": dt.datetime.now(dt.UTC).isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "original_run_dir": str(original_run_dir),
        "retry_mode": True,
        "retried_count": len(retried_attempts),
        "original_api_errors": len(api_error_attempts),
        "tasks": summary_tasks,
        "models": summary_models,
        "samples": samples,
        "attempts": all_attempts,
        "status_counts": dict(status_counts),
        "metrics": compute_metrics(all_attempts, summary_models, summary_tasks, samples),
        "metrics_by_thinking_level": compute_metrics_by_thinking_level(
            all_attempts,
            summary_models,
            summary_tasks,
            samples,
            original_summary.get("thinking_level"),
        ),
        "timing": totals["timing"],
        "token_usage": totals["token_usage"],
    }

    for key in [
        "provider",
        "temperature",
        "max_tokens",
        "include_tests",
        "install_deps",
        "allow_incomplete_diffs",
        "allow_diff_rewrite_fallback",
        "thinking_level",
        "sweep_thinking_levels",
        "include_thinking_variants",
        "requested_models",
    ]:
        if key in original_summary:
            summary[key] = original_summary[key]

    # Save results
    store_text(run_dir / "summary.json", json.dumps(summary, indent=2))
    store_text(run_dir / "attempts.json", json.dumps(all_attempts, indent=2))

    logger.info("Retry complete. Results saved to %s", run_dir)
    logger.info("Retried: %d attempts", len(retried_attempts))
    logger.info("Merged total attempts: %d", len(all_attempts))
    logger.info("Status breakdown: %s", dict(status_counts))

    if any(_is_lmstudio_model(model) for model in summary_models):
        unload_lmstudio_models()

    return summary


def retry_failed_attempts(
    *,
    original_run_dir: Path,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    preferred_provider: str | None = None,
    include_tests: bool = False,
    install_deps: bool = False,
    output_dir: Path = RUN_ARTIFACTS,
    allow_incomplete_diffs: bool | None = None,
    allow_diff_rewrite_fallback: bool | None = None,
    progress_callback: Callable[[str, str, int, dict], None] | None = None,
    filter_task_id: str | None = None,
    filter_model: str | None = None,
    filter_sample_index: int | None = None,
    run_id: str | None = None,
) -> dict:
    """
    Retry any failed attempts (error, fail, api_error) from a previous run.
    Creates a new run directory with retried attempts merged into the original run.
    """
    failed_attempts = load_failed_attempts(original_run_dir)
    if not failed_attempts:
        logger.info("No failed attempts found in %s. Nothing to retry.", original_run_dir)
        return {"retried": 0, "message": "No failed attempts to retry"}

    # Apply filters if specified
    if filter_task_id is not None:
        failed_attempts = [a for a in failed_attempts if a.get("task_id") == filter_task_id]
    if filter_model is not None:
        failed_attempts = [a for a in failed_attempts if a.get("model") == filter_model]
    if filter_sample_index is not None:
        failed_attempts = [a for a in failed_attempts if a.get("sample_index") == filter_sample_index]

    if not failed_attempts:
        logger.info("No failed attempts match the filter criteria. Nothing to retry.")
        return {"retried": 0, "message": "No matching failed attempts to retry"}

    logger.info("Found %d failed attempts to retry", len(failed_attempts))

    original_summary = _load_run_summary_if_exists(original_run_dir)
    original_attempts = _load_all_attempts_for_run(original_run_dir, original_summary)

    # Create new run directory (use provided run_id if given)
    output_dir = Path(output_dir)
    RUN_ARTIFACTS.mkdir(exist_ok=True)
    if run_id:
        run_dir = output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = create_run_directory(output_dir)
        run_id = run_dir.name

    # Collect unique models for metadata fetch
    retry_models = list({a["model"] for a in failed_attempts})
    model_metadata = fetch_model_metadata(retry_models)

    if allow_incomplete_diffs is None:
        allow_incomplete_diffs = DEFAULT_ALLOW_INCOMPLETE_DIFFS
    if allow_diff_rewrite_fallback is None:
        allow_diff_rewrite_fallback = DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK

    retried_attempts: list[dict] = []
    replacement_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for i, original_attempt in enumerate(failed_attempts, 1):
        task_id = original_attempt["task_id"]
        model = original_attempt["model"]
        sample_index = original_attempt.get("sample_index", 0)
        thinking_level = original_attempt.get("thinking_level_applied") or original_attempt.get(
            "thinking_level_requested"
        )

        logger.info(
            "[%d/%d] Retrying %s with %s (sample %s)",
            i,
            len(failed_attempts),
            task_id,
            model,
            sample_index,
        )

        try:
            metadata = load_metadata(task_id)
        except HarnessError as e:
            logger.warning("Skipping %s: %s", task_id, e)
            continue

        attempt_summary = evaluate_attempt(
            task_id=task_id,
            metadata=metadata,
            model=model,
            sample_index=sample_index,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_provider=preferred_provider or original_attempt.get("provider"),
            thinking_level=thinking_level,
            model_metadata=model_metadata,
            include_tests=include_tests,
            install_deps_flag=install_deps,
            response_override=None,
            allow_incomplete_diffs=allow_incomplete_diffs,
            allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
            run_dir=run_dir,
        )
        retried_attempts.append(attempt_summary)
        replacement_pairs.append((original_attempt, attempt_summary))
        update_task_latest(task_id, attempt_summary)

        if progress_callback:
            progress_callback(model=model, task_id=task_id, sample_index=sample_index, summary=attempt_summary)

        status = attempt_summary.get("status", "unknown")
        logger.info("Result: %s", status)

    # Build merged view so accuracy reflects the full run with replacements.
    all_attempts = (
        _merge_attempt_retries(original_attempts, replacement_pairs) if original_attempts else list(retried_attempts)
    )
    summary_tasks = _ordered_unique_strings(original_summary.get("tasks", [])) or _ordered_unique_strings(
        a.get("task_id") for a in all_attempts
    )
    summary_models = _ordered_unique_strings(original_summary.get("models", [])) or _ordered_unique_strings(
        a.get("model") for a in all_attempts
    )
    samples = int(original_summary.get("samples", 1) or 1)
    status_counts = Counter(a.get("status") for a in all_attempts)
    totals = _compute_attempt_totals(all_attempts)

    summary = {
        "timestamp_utc": dt.datetime.now(dt.UTC).isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "original_run_dir": str(original_run_dir),
        "retry_mode": True,
        "retried_count": len(retried_attempts),
        "original_failed": len(failed_attempts),
        "tasks": summary_tasks,
        "models": summary_models,
        "samples": samples,
        "attempts": all_attempts,
        "status_counts": dict(status_counts),
        "metrics": compute_metrics(all_attempts, summary_models, summary_tasks, samples),
        "metrics_by_thinking_level": compute_metrics_by_thinking_level(
            all_attempts,
            summary_models,
            summary_tasks,
            samples,
            original_summary.get("thinking_level"),
        ),
        "timing": totals["timing"],
        "token_usage": totals["token_usage"],
    }

    for key in [
        "provider",
        "temperature",
        "max_tokens",
        "include_tests",
        "install_deps",
        "allow_incomplete_diffs",
        "allow_diff_rewrite_fallback",
        "thinking_level",
        "sweep_thinking_levels",
        "include_thinking_variants",
        "requested_models",
    ]:
        if key in original_summary:
            summary[key] = original_summary[key]

    # Save results
    store_text(run_dir / "summary.json", json.dumps(summary, indent=2))
    store_text(run_dir / "attempts.json", json.dumps(all_attempts, indent=2))

    logger.info("Retry complete. Results saved to %s", run_dir)
    logger.info("Retried: %d attempts", len(retried_attempts))
    logger.info("Merged total attempts: %d", len(all_attempts))
    logger.info("Status breakdown: %s", dict(status_counts))

    if any(_is_lmstudio_model(model) for model in summary_models):
        unload_lmstudio_models()

    return summary


def load_incomplete_attempts(run_dir: Path) -> list[dict]:
    """Load attempts from a run that were started but didn't complete.

    An incomplete attempt has:
    - prompt.txt exists (attempt started)
    - No response.txt/response.json (API call didn't finish)
    - No status in summary.json for this attempt

    Returns list of dicts with task_id, model, sample_index, thinking_level info.
    """
    incomplete: list[dict] = []

    # Get completed attempts from summary if it exists
    summary_file = run_dir / "summary.json"
    completed_keys: set = set()

    if summary_file.exists():
        with summary_file.open("r", encoding="utf-8") as f:
            summary = json.load(f)
        for a in summary.get("attempts", []):
            key = (
                a.get("task_id"),
                a.get("model"),
                a.get("sample_index", 0),
                a.get("thinking_level_applied") or a.get("thinking_level_requested") or "base",
            )
            completed_keys.add(key)

    # Scan attempt directories
    for attempt_dir in run_dir.iterdir():
        if not attempt_dir.is_dir():
            continue

        # Parse directory name: task_id__model__sampleNN__lvl_level
        dir_name = attempt_dir.name

        # Check if this is an attempt directory (has prompt.txt)
        prompt_file = attempt_dir / "prompt.txt"
        if not prompt_file.exists():
            continue

        # Check if incomplete (no response.txt or response.json)
        response_txt = attempt_dir / "response.txt"
        response_json = attempt_dir / "response.json"

        if response_txt.exists() or response_json.exists():
            continue  # This attempt completed

        # Parse attempt info from directory name
        # Format: task_id__model__sampleNN__lvl_level
        parts = dir_name.split("__")
        if len(parts) < 3:
            continue

        task_id = parts[0]
        model_part = parts[1].replace("_", "/")  # Restore / from _

        sample_index = 0
        thinking_level = "base"

        for part in parts[2:]:
            if part.startswith("sample"):
                try:
                    sample_index = int(part.replace("sample", ""))
                except ValueError:
                    pass
            elif part.startswith("lvl_"):
                thinking_level = part.replace("lvl_", "").replace("_", "/")

        # Check if already completed
        key = (task_id, model_part, sample_index, thinking_level)
        if key in completed_keys:
            continue

        incomplete.append(
            {
                "task_id": task_id,
                "model": model_part,
                "sample_index": sample_index,
                "thinking_level": thinking_level if thinking_level != "base" else None,
                "attempt_dir": str(attempt_dir),
            }
        )

    return incomplete


def resume_incomplete_run(
    *,
    run_dir: Path,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    preferred_provider: str | None = None,
    include_tests: bool = False,
    install_deps: bool = False,
    allow_incomplete_diffs: bool | None = None,
    allow_diff_rewrite_fallback: bool | None = None,
    progress_callback: Callable[[str, str, int, dict], None] | None = None,
) -> dict:
    """
    Resume an incomplete run by retrying attempts that didn't finish.
    Updates the original run directory with completed attempts.
    """
    incomplete_attempts = load_incomplete_attempts(run_dir)

    if not incomplete_attempts:
        logger.info("No incomplete attempts found in %s.", run_dir)

        # Check if there's a summary.json
        summary_file = run_dir / "summary.json"
        if summary_file.exists():
            with summary_file.open("r", encoding="utf-8") as f:
                return json.load(f)

        return {"resumed": 0, "message": "No incomplete attempts to resume"}

    logger.info("Found %d incomplete attempts to resume", len(incomplete_attempts))

    # Load existing summary or create new one
    summary_file = run_dir / "summary.json"
    existing_attempts: list[dict] = []
    existing_summary: dict = {}

    if summary_file.exists():
        with summary_file.open("r", encoding="utf-8") as f:
            existing_summary = json.load(f)
            existing_attempts = existing_summary.get("attempts", [])

    # Collect unique models and tasks
    models = list({a["model"] for a in incomplete_attempts})
    tasks = list({a["task_id"] for a in incomplete_attempts})
    model_metadata = fetch_model_metadata(models)

    if allow_incomplete_diffs is None:
        allow_incomplete_diffs = DEFAULT_ALLOW_INCOMPLETE_DIFFS
    if allow_diff_rewrite_fallback is None:
        allow_diff_rewrite_fallback = DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK

    new_attempts: list[dict] = []

    for i, incomplete in enumerate(incomplete_attempts, 1):
        task_id = incomplete["task_id"]
        model = incomplete["model"]
        sample_index = incomplete["sample_index"]
        thinking_level = incomplete.get("thinking_level")

        logger.info(
            "[%d/%d] Resuming %s with %s (sample %s)",
            i,
            len(incomplete_attempts),
            task_id,
            model,
            sample_index,
        )

        try:
            metadata = load_metadata(task_id)
        except HarnessError as e:
            logger.warning("Skipping %s: %s", task_id, e)
            continue

        attempt_summary = evaluate_attempt(
            task_id=task_id,
            metadata=metadata,
            model=model,
            sample_index=sample_index,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_provider=preferred_provider,
            thinking_level=thinking_level,
            model_metadata=model_metadata,
            include_tests=include_tests,
            install_deps_flag=install_deps,
            response_override=None,
            allow_incomplete_diffs=allow_incomplete_diffs,
            allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
            run_dir=run_dir,
        )
        new_attempts.append(attempt_summary)
        update_task_latest(task_id, attempt_summary)

        if progress_callback:
            progress_callback(model=model, task_id=task_id, sample_index=sample_index, summary=attempt_summary)

        status = attempt_summary.get("status", "unknown")
        logger.info("Result: %s", status)

    # Merge with existing attempts
    all_attempts = existing_attempts + new_attempts
    all_tasks = list({a["task_id"] for a in all_attempts})
    all_models = list({a["model"] for a in all_attempts})

    # Compute metrics
    status_counts = Counter(a.get("status") for a in all_attempts)

    # Update or create summary
    run_id = run_dir.name
    summary = {
        "timestamp_utc": existing_summary.get("timestamp_utc", dt.datetime.now(dt.UTC).isoformat()),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "tasks": all_tasks,
        "models": all_models,
        "samples": existing_summary.get("samples", 1),
        "temperature": existing_summary.get("temperature", temperature),
        "max_tokens": existing_summary.get("max_tokens", max_tokens),
        "attempts": all_attempts,
        "status_counts": dict(status_counts),
        "metrics": compute_metrics(all_attempts, all_models, all_tasks, existing_summary.get("samples", 1)),
        "resumed_at": dt.datetime.now(dt.UTC).isoformat(),
        "resumed_count": len(new_attempts),
    }

    # Preserve other fields from existing summary
    for key in [
        "provider",
        "include_tests",
        "install_deps",
        "allow_incomplete_diffs",
        "allow_diff_rewrite_fallback",
        "thinking_level",
        "sweep_thinking_levels",
        "include_thinking_variants",
        "requested_models",
    ]:
        if key in existing_summary:
            summary[key] = existing_summary[key]

    # Save updated summary
    store_text(summary_file, json.dumps(summary, indent=2))
    store_text(run_dir / "attempts.json", json.dumps(all_attempts, indent=2))

    logger.info("Resume complete. Results saved to %s", run_dir)
    logger.info("Resumed: %d attempts", len(new_attempts))
    logger.info("Total: %d attempts", len(all_attempts))
    logger.info("Status breakdown: %s", dict(status_counts))

    if any(_is_lmstudio_model(model) for model in all_models):
        unload_lmstudio_models()

    return summary


def resolve_task_list(args: argparse.Namespace) -> list[str]:
    if args.task and args.tasks:
        raise HarnessError("Use either --task or --tasks, not both.")
    if args.task:
        return [args.task]
    if args.tasks:
        if len(args.tasks) == 1 and args.tasks[0].lower() == "all":
            tasks = discover_tasks()
            if not tasks:
                raise HarnessError("No tasks found under tasks/ directory.")
            return tasks
        return args.tasks
    raise HarnessError("No tasks specified. Use --task <id> or --tasks all/ID ...")


def run_tasks(
    *,
    tasks: list[str],
    models: list[str],
    samples: int = 1,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    preferred_provider: str | None = None,
    thinking_level: str | None = None,
    sweep_thinking_levels: bool = False,
    include_thinking_variants: bool = False,
    include_tests: bool = False,
    install_deps: bool = False,
    output_dir: Path = RUN_ARTIFACTS,
    response_file: Path | None = None,
    response_text: str | None = None,
    allow_incomplete_diffs: bool | None = None,
    allow_diff_rewrite_fallback: bool | None = None,
    progress_callback: Callable[[str, str, int, dict], None] | None = None,
    run_id: str | None = None,
) -> dict:
    samples = max(1, samples)
    if response_file and (len(tasks) != 1 or len(models) != 1 or samples != 1):
        raise HarnessError("--response-file is only supported for single-task, single-model, single-sample runs.")
    output_dir = Path(output_dir)
    RUN_ARTIFACTS.mkdir(exist_ok=True)
    if run_id:
        run_dir = output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = create_run_directory(output_dir)
        run_id = run_dir.name

    original_models = list(models)
    model_metadata = fetch_model_metadata(models)
    if include_thinking_variants:
        models = expand_models_with_thinking_variants(models, model_metadata)
        # Refresh metadata to ensure newly added variants have full entries.
        model_metadata = fetch_model_metadata(models)

    response_override = None
    if response_file:
        response_override = Path(response_file).read_text(encoding="utf-8")
    elif response_text is not None:
        response_override = response_text

    if allow_incomplete_diffs is None:
        allow_incomplete_diffs = DEFAULT_ALLOW_INCOMPLETE_DIFFS
    if allow_diff_rewrite_fallback is None:
        allow_diff_rewrite_fallback = DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK

    attempts: list[dict] = []
    patch_fallbacks_used: list[str] = []

    def _suggest_levels_for_model(model_id: str) -> list[str]:
        info = model_metadata.get(model_id) or {}
        params = {p.lower() for p in (info.get("supported_parameters") or []) if isinstance(p, str)}
        if "reasoning" not in params:
            return []
        # Default suggestion set; providers typically accept these effort levels
        return ["low", "medium", "high"]

    for model in models:
        # Determine which thinking levels to evaluate for this model
        levels: list[str | None]
        if sweep_thinking_levels:
            suggested = _suggest_levels_for_model(model)
            levels = [None] + (suggested or ["low", "medium", "high"])  # fallback if unknown
        else:
            levels = [thinking_level] if thinking_level else [None]

        # Run per task → per level so you see all levels for each task earlier
        for task_id in tasks:
            metadata = load_metadata(task_id)
            for level in levels:
                for sample_idx in range(samples):
                    attempt_summary = evaluate_attempt(
                        task_id=task_id,
                        metadata=metadata,
                        model=model,
                        sample_index=sample_idx,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        preferred_provider=preferred_provider,
                        thinking_level=level,
                        model_metadata=model_metadata,
                        include_tests=include_tests,
                        install_deps_flag=install_deps,
                        response_override=response_override,
                        allow_incomplete_diffs=allow_incomplete_diffs,
                        allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
                        run_dir=run_dir,
                    )
                    attempts.append(attempt_summary)
                    update_task_latest(task_id, attempt_summary)
                    if progress_callback:
                        progress_callback(
                            model=model, task_id=task_id, sample_index=sample_idx, summary=attempt_summary
                        )
                    if attempt_summary.get("diff_rewrite_fallback_used"):
                        patch_fallbacks_used.append(attempt_summary["attempt_dir"])

    try:
        run_dir_relative = str(run_dir.relative_to(output_dir))
    except ValueError:
        run_dir_relative = None

    total_duration = 0.0
    total_api_latency = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    for attempt in attempts:
        duration = attempt.get("duration_seconds")
        if duration is not None:
            total_duration += duration
        api_latency = attempt.get("api_latency_seconds")
        if api_latency is not None:
            total_api_latency += api_latency
        usage = attempt.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = usage.get("output_tokens")

        if prompt_tokens is not None:
            prompt_tokens = int(prompt_tokens)
            total_prompt_tokens += prompt_tokens
        if completion_tokens is not None:
            completion_tokens = int(completion_tokens)
            total_completion_tokens += completion_tokens

        pricing = model_metadata.get(attempt["model"])
        if pricing and (prompt_tokens is not None or completion_tokens is not None):
            attempt_cost = 0.0
            if prompt_tokens is not None:
                attempt_cost += prompt_tokens * pricing["prompt"]
            if completion_tokens is not None:
                attempt_cost += completion_tokens * pricing["completion"]
            attempt["cost_usd"] = attempt_cost
            total_cost += attempt_cost

    status_counts = Counter(attempt.get("status") for attempt in attempts)
    model_status_counts: dict[str, dict[str, int]] = {}
    task_status: dict[str, str] = {}
    attempt_manifest: list[dict[str, Any]] = []

    for attempt in attempts:
        model_status_counts.setdefault(attempt["model"], {}).setdefault(attempt.get("status"), 0)
        model_status_counts[attempt["model"]][attempt.get("status")] += 1
        task_status[attempt["task_id"]] = attempt.get("status")
        attempt_manifest.append(
            {
                "task_id": attempt.get("task_id"),
                "model": attempt.get("model"),
                "provider": attempt.get("provider"),
                "status": attempt.get("status"),
                "attempt_dir": attempt.get("attempt_dir"),
                "sample_index": attempt.get("sample_index"),
            }
        )

    summary = {
        "timestamp_utc": dt.datetime.now(dt.UTC).isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "run_dir_relative_to_output": run_dir_relative,
        "output_dir": str(output_dir),
        "tasks": tasks,
        "models": models,
        "provider": preferred_provider,
        "samples": samples,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "include_tests": include_tests,
        "install_deps": install_deps,
        "allow_incomplete_diffs": allow_incomplete_diffs,
        "allow_diff_rewrite_fallback": allow_diff_rewrite_fallback,
        "thinking_level": thinking_level,
        "sweep_thinking_levels": bool(sweep_thinking_levels),
        "include_thinking_variants": include_thinking_variants,
        "requested_models": original_models,
        "attempts": attempts,
        "patch_fallbacks_used": patch_fallbacks_used,
        "status_counts": dict(status_counts),
        "model_status_counts": model_status_counts,
        "task_status": task_status,
        "attempt_manifest": attempt_manifest,
        "metrics": compute_metrics(attempts, models, tasks, samples),
        "metrics_by_thinking_level": compute_metrics_by_thinking_level(
            attempts, models, tasks, samples, thinking_level
        ),
        "timing": {
            "total_duration_seconds": total_duration,
            "total_api_latency_seconds": total_api_latency,
        },
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost, 6),
        },
        "pricing": {model: model_metadata.get(model) for model in models if model_metadata.get(model)},
    }

    summary_path = run_dir / "summary.json"
    store_text(summary_path, json.dumps(summary, indent=2))

    store_text(run_dir / "attempts.json", json.dumps(attempts, indent=2))
    store_text(run_dir / "manifest.json", json.dumps(attempt_manifest, indent=2))

    latest_summary_path = RUN_ARTIFACTS / "latest_summary.json"
    store_text(latest_summary_path, json.dumps(summary, indent=2))

    if any(_is_lmstudio_model(model) for model in original_models):
        unload_lmstudio_models()

    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    allow_incomplete_diffs = (
        DEFAULT_ALLOW_INCOMPLETE_DIFFS if args.allow_incomplete_diffs is None else args.allow_incomplete_diffs
    )
    allow_diff_rewrite_fallback = (
        DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK
        if args.allow_diff_rewrite_fallback is None
        else args.allow_diff_rewrite_fallback
    )

    # Handle resume/retry mode
    if args.resume_from:
        run_dir = Path(args.resume_from)
        if not run_dir.exists():
            raise HarnessError(f"Run directory not found: {run_dir}")

        def progress_callback(model: str, task_id: str, sample_index: int, summary: dict) -> None:
            _cli_echo(f"[{model}] {task_id} sample {sample_index}: {summary['status']}")

        if args.resume_incomplete:
            # Resume incomplete attempts (started but didn't finish)
            summary = resume_incomplete_run(
                run_dir=run_dir,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                preferred_provider=args.provider,
                include_tests=args.include_tests,
                install_deps=args.install_deps,
                allow_incomplete_diffs=allow_incomplete_diffs,
                allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
                progress_callback=progress_callback,
            )
        else:
            # Default: retry api_error attempts
            summary = retry_api_error_attempts(
                original_run_dir=run_dir,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                preferred_provider=args.provider,
                include_tests=args.include_tests,
                install_deps=args.install_deps,
                output_dir=args.output_dir,
                allow_incomplete_diffs=allow_incomplete_diffs,
                allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
                progress_callback=progress_callback,
            )
        return 0

    # Normal mode - require tasks
    tasks = resolve_task_list(args)
    models = args.models
    samples = max(1, args.samples)

    if args.response_file and (len(tasks) != 1 or len(models) != 1 or samples != 1):
        raise HarnessError("--response-file is only supported for single-task, single-model, single-sample runs.")

    if args.dry_run:
        for task_id in tasks:
            metadata = load_metadata(task_id)
            prompt = build_prompt(task_id, metadata, include_tests=args.include_tests)
            _cli_echo(f"===== Prompt for {task_id} =====")
            _cli_echo(prompt)
        return 0

    def progress_callback(model: str, task_id: str, sample_index: int, summary: dict) -> None:
        _cli_echo(f"[{model}] {task_id} sample {sample_index}: {summary['status']}")

    summary = run_tasks(
        tasks=tasks,
        models=models,
        samples=samples,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        preferred_provider=args.provider,
        thinking_level=args.thinking_level,
        sweep_thinking_levels=args.sweep_thinking_levels,
        include_thinking_variants=args.include_thinking_variants,
        include_tests=args.include_tests,
        install_deps=args.install_deps,
        output_dir=args.output_dir,
        response_file=args.response_file,
        allow_incomplete_diffs=allow_incomplete_diffs,
        allow_diff_rewrite_fallback=allow_diff_rewrite_fallback,
        progress_callback=progress_callback,
    )
    _cli_echo(f"Run artifacts stored in {summary['run_dir']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    try:
        raise SystemExit(main())
    except HarnessError as exc:
        _cli_echo(f"Harness error: {exc}", error=True)
        raise SystemExit(1)
