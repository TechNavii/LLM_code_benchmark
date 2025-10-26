#!/usr/bin/env python3
"""Benchmark harness for evaluating multiple tasks/models via OpenRouter."""

from __future__ import annotations

import argparse
import difflib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - optional for offline dry runs
    requests = None


ROOT = Path(__file__).resolve().parents[1]

from harness.config import get_settings
from harness.exceptions import HarnessError
from harness.secure_execution import secure_run


SETTINGS = get_settings()

TASKS_ROOT = SETTINGS.tasks_root
RUN_ARTIFACTS = SETTINGS.runs_root
DEFAULT_MODEL = SETTINGS.default_model
DEFAULT_MAX_TOKENS = SETTINGS.default_max_tokens
SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
}
MAX_LOG_CHARS = SETTINGS.max_log_chars
DEFAULT_ALLOW_INCOMPLETE_DIFFS = SETTINGS.allow_incomplete_diffs
DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK = SETTINGS.allow_diff_rewrite_fallback

TASK_HINTS: Dict[str, str] = {
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
    header_lines = sum(1 for line in lines if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "))

    if header_lines >= 2 and (add_lines or remove_lines or hunk_lines):
        return True
    if hunk_lines and (add_lines or remove_lines):
        return True
    if add_lines + remove_lines >= 2:
        return True
    return False


def _normalize_patch_format(patch: str) -> tuple[str, bool]:
    lines = patch.splitlines()
    normalized: List[str] = []
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
                if candidate_stripped.startswith("@@") or candidate_stripped.startswith("diff --git") or candidate_stripped.startswith("--- ") or candidate_stripped.startswith("+++ "):
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
            parsed_old_len_val: Optional[int] = None
            parsed_new_len_val: Optional[int] = None
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
                suffix = stripped[match.end():].strip()
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

        if in_hunk and not line.startswith(('+', '-', ' ', '\\')):
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


def _store_model_metadata(
    registry: Dict[str, Dict[str, Any]],
    model_id: str,
    metadata: Dict[str, Any],
) -> None:
    existing = registry.get(model_id, {})
    if existing:
        merged = {**existing, **metadata}
    else:
        merged = metadata
    registry[model_id] = merged


def fetch_model_metadata(models: List[str]) -> Dict[str, Dict[str, Any]]:
    if requests is None:
        return {}

    requested = {_normalize_model_id(model) for model in models}
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={
                "Authorization": f"Bearer {SETTINGS.openrouter_api_key}",
                "HTTP-Referer": "benchmark-harness",
            },
            timeout=60,
        )
        response.raise_for_status()
    except Exception:
        return {}

    data = response.json()
    registry: Dict[str, Dict[str, Any]] = {}
    for entry in data.get('data', []):
        model_id = entry.get('id')
        if not model_id:
            continue
        is_thinking_variant = model_id.endswith(":thinking")
        base_id = model_id.rsplit(":thinking", 1)[0] if is_thinking_variant else None
        should_include = model_id in requested
        if base_id and base_id in requested:
            should_include = True
        if not should_include:
            continue

        model_pricing = entry.get('pricing') or {}
        try:
            prompt_rate = float(model_pricing.get('prompt', 0))
            completion_rate = float(model_pricing.get('completion', 0))
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
    models: List[str],
    metadata: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Return a model list expanded with thinking variants where available."""
    expanded: List[str] = []
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


def _compose_reasoning_payload(level: str) -> Dict[str, Any]:
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


def discover_tasks() -> List[str]:
    if not TASKS_ROOT.exists():
        return []
    return sorted(
        task_dir.name
        for task_dir in TASKS_ROOT.iterdir()
        if task_dir.is_dir() and (task_dir / "metadata.json").exists()
    )


def load_metadata(task_id: str) -> Dict:
    metadata_path = TASKS_ROOT / task_id / "metadata.json"
    if not metadata_path.exists():
        raise HarnessError(f"metadata.json not found for task {task_id}")
    with metadata_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def should_include_in_prompt(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def build_prompt(task_id: str, metadata: Dict, include_tests: bool = False) -> str:
    task_dir = TASKS_ROOT / task_id
    instructions_path = task_dir / metadata["instructions_file"]
    if not instructions_path.exists():
        raise HarnessError(f"Instructions file missing: {instructions_path}")
    instructions = instructions_path.read_text(encoding="utf-8").strip()

    workspace_dir = task_dir / metadata.get("workspace_dir", "workspace")
    contextual_snippets: List[str] = []

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
MAX_COMPLETION_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


def call_openrouter(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    preferred_provider: Optional[str] = None,
    *,
    thinking_level: Optional[str] = None,
    model_info: Optional[Dict[str, Any]] = None,
) -> tuple[str, Dict, float]:
    if requests is None:
        raise HarnessError("The 'requests' library is required to call OpenRouter.")

    api_key = SETTINGS.openrouter_api_key

    url = "https://openrouter.ai/api/v1/chat/completions"
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
            param.lower()
            for param in model_info.get("supported_parameters", [])
            if isinstance(param, str)
        }
    if thinking_level and "reasoning" in supported_params:
        reasoning_payload = _compose_reasoning_payload(thinking_level)
        if reasoning_payload:
            payload["reasoning"] = reasoning_payload
            if "include_reasoning" in supported_params:
                payload["include_reasoning"] = True

    last_error: Optional[HarnessError] = None
    backoff = RETRY_BACKOFF_SECONDS

    for attempt in range(MAX_COMPLETION_RETRIES):
        try:
            start_time = time.perf_counter()
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            duration = time.perf_counter() - start_time
        except requests.exceptions.RequestException as exc:  # pragma: no cover - network failures
            last_error = HarnessError(f"OpenRouter request failed: {exc}")
            should_retry = True
        else:
            status = response.status_code
            if status >= 500:
                error_message = response.text.strip()
                last_error = HarnessError(f"OpenRouter request failed ({status}): {error_message}")
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
                raise HarnessError(
                    f"OpenRouter request failed ({status}): {error_message}"
                )
            else:
                try:
                    data = response.json()
                except (requests.exceptions.JSONDecodeError, ValueError) as exc:
                    content_type = response.headers.get("content-type", "unknown")
                    body_preview = response.text.strip()
                    if len(body_preview) > 512:
                        body_preview = f"{body_preview[:512]}..."
                    last_error = HarnessError(
                        "OpenRouter returned a non-JSON response payload. "
                        f"status={status} content-type={content_type} preview={body_preview!r}"
                    )
                    should_retry = True
                else:
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError) as exc:  # pragma: no cover - API schema issues
                        last_error = HarnessError(f"Unexpected OpenRouter response payload: {data}")
                        should_retry = True
                    else:
                        return content, data, duration

        if attempt < MAX_COMPLETION_RETRIES - 1 and should_retry:
            time.sleep(backoff)
            backoff *= 2
            continue
        break

    assert last_error is not None  # for type checkers
    raise last_error


def extract_patch(raw_response: str, allow_incomplete_diffs: bool = False) -> str:
    fence = "```diff"
    if fence not in raw_response:
        raise HarnessError("Model response does not contain a ```diff fenced block.")
    start = raw_response.index(fence) + len(fence)
    try:
        end = raw_response.index("```", start)
    except ValueError as exc:
        if not allow_incomplete_diffs:
            raise HarnessError("Model response does not contain closing ``` fence.") from exc
        fallback_patch = _extract_incomplete_patch(raw_response[start:])
        if not fallback_patch or not _is_probably_valid_patch(fallback_patch):
            raise HarnessError(
                "Model response diff block is incomplete or untrustworthy (missing closing ``` fence)."
            ) from exc
        return fallback_patch
    patch = raw_response[start:end]
    return patch.strip() + "\n"


def clean_patch_text(patch_text: str) -> tuple[str, bool, bool]:
    ansi_escape = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
    cleaned = ansi_escape.sub('', patch_text)
    if '\x1b' in cleaned:
        raise HarnessError('Patch contains unsupported control characters.')
    cleaned, synthetic_headers = _normalize_patch_format(cleaned)
    git_style = cleaned.startswith('--- a/') or cleaned.startswith('diff --git')
    return cleaned, git_style, synthetic_headers


def prepare_run_directory(task_id: str, metadata: Dict) -> Path:
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
            "Failed to install requirements:\n"
            f"STDOUT:\n{process.stdout.decode()}\n"
            f"STDERR:\n{process.stderr.decode()}"
        )


def _run_patch_command(args: List[str], patch_bytes: bytes, workspace_path: Path, timeout: int = 60):
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
    except subprocess.TimeoutExpired:
        raise HarnessError("Failed to apply patch: patch command timed out")


def _normalize_patch_path(path: str) -> Optional[str]:
    path = path.strip()
    if not path or path in {"/dev/null", "dev/null"}:
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    path = path.lstrip("./")
    if path.startswith("workspace/"):
        path = path[len("workspace/"):]
    return path.lstrip("./")


def _extract_full_file_rewrites(cleaned_patch: str) -> Optional[Dict[str, str]]:
    lines = cleaned_patch.splitlines()
    rewrites: Dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('diff --git'):
            i += 1
            continue
        if not line.startswith('--- '):
            i += 1
            continue
        old_path = line[4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith('+++ '):
            return None
        new_path = lines[i][4:].strip()
        i += 1
        content_lines: List[str] = []
        has_minus = False
        while i < len(lines):
            current = lines[i]
            if current.startswith('diff --git') or current.startswith('--- '):
                break
            if current.startswith('@@'):
                i += 1
                continue
            if current.startswith('-') and not current.startswith('---'):
                has_minus = True
                i += 1
                continue
            if current.startswith('+') and not current.startswith('+++'):
                content_lines.append(current[1:])
                i += 1
                continue
            if current.startswith(' '):
                content_lines.append(current[1:])
                i += 1
                continue
            if current.startswith('\\'):
                i += 1
                continue
            i += 1
        if has_minus:
            return None
        target_path = _normalize_patch_path(new_path)
        if target_path is None:
            return None
        content = '\n'.join(content_lines)
        if content_lines:
            content += '\n'
        rewrites[target_path] = content
    return rewrites or None


HUNK_HEADER_RE = re.compile(r'^@@ -(?P<old_start>\d+)(?:,(?P<old_len>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_len>\d+))? @@')


def _parse_unified_diff(cleaned_patch: str):
    lines = cleaned_patch.splitlines()
    files = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('diff --git'):
            i += 1
            continue
        if not line.startswith('--- '):
            i += 1
            continue
        old_path = line[4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith('+++ '):
            return None
        new_path = lines[i][4:].strip()
        i += 1
        hunks = []
        while i < len(lines):
            current = lines[i]
            if current.startswith('diff --git') or current.startswith('--- '):
                break
            if current.startswith('@@'):
                match = HUNK_HEADER_RE.match(current)
                if not match:
                    return None
                start_old = int(match.group('old_start'))
                len_old = int(match.group('old_len') or '1')
                start_new = int(match.group('new_start'))
                len_new = int(match.group('new_len') or '1')
                i += 1
                hunk_lines: List[str] = []
                while i < len(lines):
                    candidate = lines[i]
                    if candidate.startswith('diff --git') or candidate.startswith('--- ') or candidate.startswith('@@'):
                        break
                    hunk_lines.append(candidate)
                    i += 1
                hunks.append((start_old, len_old, start_new, len_new, hunk_lines))
            else:
                i += 1
        files.append((old_path, new_path, hunks))
    return files or None


def _apply_parsed_unified_diff(file_diffs, workspace_path: Path) -> Optional[List[str]]:
    rewritten: List[str] = []
    for old_path, new_path, hunks in file_diffs:
        target_rel = _normalize_patch_path(new_path)
        if target_rel is None:
            return None
        source_rel = _normalize_patch_path(old_path)
        if source_rel is None:
            original_lines: List[str] = []
        else:
            source_file = workspace_path / source_rel
            if source_file.exists():
                original_lines = source_file.read_text(encoding="utf-8").splitlines()
            else:
                original_lines = []
        result_lines: List[str] = []
        orig_index = 0
        for start_old, len_old, start_new, len_new, hunk_lines in hunks:
            zero_based = max(start_old - 1, 0)
            zero_based = min(zero_based, len(original_lines))
            if zero_based > orig_index:
                result_lines.extend(original_lines[orig_index:zero_based])
                orig_index = zero_based
            for line in hunk_lines:
                if not line:
                    result_lines.append('')
                    continue
                tag = line[0]
                text = line[1:] if len(line) > 1 else ''
                if tag == ' ':
                    result_lines.append(text)
                    if orig_index < len(original_lines):
                        orig_index += 1
                elif tag == '-':
                    if orig_index < len(original_lines):
                        orig_index += 1
                elif tag == '+':
                    result_lines.append(text)
                elif tag == '\\':
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
        if line.startswith('diff --git'):
            i += 1
            continue
        if not line.startswith('--- '):
            i += 1
            continue
        old_path = line[4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith('+++ '):
            return None
        new_path = lines[i][4:].strip()
        i += 1
        hunks = []
        while i < len(lines):
            current = lines[i]
            if current.startswith('diff --git') or current.startswith('--- '):
                break
            if current.startswith('@@'):
                header = current
                i += 1
                hunk_ops: List[Tuple[str, str]] = []
                while i < len(lines):
                    candidate = lines[i]
                    if candidate.startswith('diff --git') or candidate.startswith('--- ') or candidate.startswith('@@'):
                        break
                    if candidate.startswith('\\'):
                        i += 1
                        continue
                    if not candidate:
                        hunk_ops.append((' ', ''))
                        i += 1
                        continue
                    prefix = candidate[0]
                    if prefix in {'+', '-', ' '}:
                        hunk_ops.append((prefix, candidate[1:]))
                    else:
                        hunk_ops.append((' ', candidate))
                    i += 1
                if hunk_ops:
                    hunks.append((header, hunk_ops))
                continue
            i += 1
        files.append((old_path, new_path, hunks))
    return files or None


def _find_subsequence(haystack: List[str], needle: List[str], start: int) -> Optional[int]:
    if not needle:
        return start
    end_limit = len(haystack) - len(needle)
    if end_limit < 0:
        return None
    start = max(start, 0)
    for idx in range(start, end_limit + 1):
        if haystack[idx:idx + len(needle)] == needle:
            return idx
    return None


_COMPARE_STRATEGIES: Tuple[Callable[[str], str], ...] = (
    lambda s: s,
    lambda s: s.expandtabs(4),
    lambda s: re.sub(r'\s+', ' ', s.strip()),
)


def _lines_equivalent(left: str, right: str) -> bool:
    if left == right:
        return True
    for transform in _COMPARE_STRATEGIES:
        if transform(left) == transform(right):
            return True
    return False


def _locate_hunk(updated_lines: List[str], pattern: List[str], search_start: int) -> Optional[int]:
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
            segment = "\n".join(updated_lines[idx: idx + window])
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


def _apply_loose_unified_diff(file_diffs, workspace_path: Path) -> Optional[List[str]]:
    planned_writes: List[Tuple[str, str]] = []
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
            if not any(tag in ('+', '-') for tag, _ in hunk_ops):
                continue
            pattern = [text for tag, text in hunk_ops if tag in (' ', '-')]
            start_index = _locate_hunk(updated_lines, pattern, search_start)
            if start_index is None:
                if all(tag == '-' for tag, _ in hunk_ops if tag in (' ', '-')):
                    start_index = search_start
                else:
                    return None
            new_segment: List[str] = []
            cursor = start_index
            for tag, text in hunk_ops:
                if tag == ' ':
                    if text == '':
                        while cursor < len(updated_lines) and updated_lines[cursor].strip() == '':
                            new_segment.append(updated_lines[cursor])
                            cursor += 1
                        continue
                    search_cursor = cursor
                    temp_buffer: List[str] = []
                    found = False
                    while search_cursor < len(updated_lines):
                        existing_line = updated_lines[search_cursor]
                        if _lines_equivalent(text, existing_line):
                            new_segment.extend(temp_buffer)
                            new_segment.append(existing_line)
                            cursor = search_cursor + 1
                            found = True
                            break
                        if existing_line.strip() == '':
                            temp_buffer.append(existing_line)
                            search_cursor += 1
                            continue
                        break
                    if not found:
                        return None
                elif tag == '-':
                    temp_segment: List[str] = []
                    temp_cursor = cursor
                    removed = False
                    while temp_cursor < len(updated_lines):
                        existing_line = updated_lines[temp_cursor]
                        if _lines_equivalent(text, existing_line):
                            cursor = temp_cursor + 1
                            new_segment.extend(temp_segment)
                            removed = True
                            break
                        if existing_line.strip() == '':
                            temp_segment.append(existing_line)
                            temp_cursor += 1
                            continue
                        break
                    if not removed:
                        # minus line not present; leave original text untouched
                        continue
                elif tag == '+':
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
    rewritten: List[str] = []
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
) -> Optional[List[str]]:
    rewrites = _extract_full_file_rewrites(cleaned_patch)
    if rewrites:
        rewritten_files: List[str] = []
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
            "hunk failed",
            "out of 1 hunks failed",
            "can't seem to find a patch",
            "cannot find a patch",
        )
    )


def apply_patch(
    patch_text: str,
    workspace_path: Path,
    *,
    allow_diff_rewrite_fallback: bool,
    attempt_summary: Dict,
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
                attempt_summary['diff_rewrite_fallback_used'] = True
                attempt_summary['diff_rewrite_files'] = sorted(rewritten_files)
                store_text(
                    attempt_dir / "diff_rewrite_fallback.log",
                    "Applied diff rewrite fallback to:\n" + "\n".join(sorted(rewritten_files)),
                )
                return
        raise HarnessError(
            "Patch failed dry-run validation:\n"
            f"STDOUT:\n{stdout_text}\n"
            f"STDERR:\n{stderr_text}"
        )

    apply_process = _run_patch_command(patch_args, patch_bytes, workspace_path)
    if apply_process.returncode != 0:
        raise HarnessError(
            "Failed to apply patch:\n"
            f"STDOUT:\n{apply_process.stdout.decode()}\n"
            f"STDERR:\n{apply_process.stderr.decode()}"
        )


def run_evaluation(
    command: List[str],
    workspace_path: Path,
    timeout: int,
    env_updates: Optional[Dict[str, str]] = None,
    working_dir: Optional[str] = None,
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
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = output_root / f"{timestamp}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def store_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def evaluate_attempt(
    task_id: str,
    metadata: Dict,
    model: str,
    sample_index: int,
    temperature: float,
    max_tokens: int,
    preferred_provider: Optional[str],
    thinking_level: Optional[str],
    model_metadata: Dict[str, Dict[str, Any]],
    include_tests: bool,
    install_deps_flag: bool,
    response_override: Optional[str],
    allow_incomplete_diffs: bool,
    allow_diff_rewrite_fallback: bool,
    run_dir: Path,
) -> Dict:
    prompt = build_prompt(task_id, metadata, include_tests=include_tests)
    attempt_id = f"{task_id}__{model.replace('/', '_')}__sample{sample_index:02d}"
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
    }

    model_info = model_metadata.get(model) or {}
    supported_params = {
        param.lower()
        for param in model_info.get("supported_parameters", [])
        if isinstance(param, str)
    }
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
            raw_response, response_meta, api_latency = call_openrouter(
                prompt,
                model,
                temperature,
                max_tokens,
                preferred_provider,
                thinking_level=thinking_level if "reasoning" in supported_params else None,
                model_info=model_info,
            )
    except HarnessError as exc:
        attempt_summary.update({"error": str(exc)})
        store_text(attempt_dir / "error.log", str(exc))
        return attempt_summary

    store_text(attempt_dir / "response.txt", raw_response)
    if response_meta is not None:
        store_text(attempt_dir / "response.json", json.dumps(response_meta, indent=2))
        usage = response_meta.get('usage')

    workspace_path: Optional[Path] = None
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

        store_text(attempt_dir / "stdout.log", truncate_log(process.stdout.decode("utf-8")))
        store_text(attempt_dir / "stderr.log", truncate_log(process.stderr.decode("utf-8")))

        attempt_summary.update(
            {
                "status": "passed" if process.returncode == 0 else "failed",
                "return_code": process.returncode,
            }
        )

    except HarnessError as exc:
        attempt_summary.update({"status": "error", "error": str(exc)})
        store_text(attempt_dir / "error.log", str(exc))
    finally:
        if workspace_path is not None:
            shutil.rmtree(workspace_path.parent, ignore_errors=True)

    attempt_summary['usage'] = usage
    attempt_summary['api_latency_seconds'] = api_latency
    attempt_summary['duration_seconds'] = time.perf_counter() - attempt_timer
    return attempt_summary

def compute_metrics(attempts: Iterable[Dict], models: List[str], tasks: List[str], samples: int) -> Dict:
    metrics: Dict[str, Dict[str, Optional[float]]] = {
        "model_accuracy": {},
        "model_attempt_success": {},
    }
    pass_at_1: Dict[str, Optional[float]] = {}
    pass_at_k: Dict[str, Optional[float]] = {}

    for model in models:
        model_attempts = [a for a in attempts if a["model"] == model]
        if not model_attempts:
            metrics["model_accuracy"][model] = None
            metrics["model_attempt_success"][model] = None
            pass_at_1[model] = None
            pass_at_k[model] = None
            continue

        # Attempt-level success rate
        successes = sum(1 for a in model_attempts if a["status"] == "passed")
        metrics["model_attempt_success"][model] = successes / len(model_attempts)

        task_success_rates: List[int] = []
        task_pass_at_1: List[int] = []
        task_pass_at_k: List[int] = []

        for task in tasks:
            task_attempts = [a for a in model_attempts if a["task_id"] == task]
            if not task_attempts:
                continue
            task_success = any(a["status"] == "passed" for a in task_attempts)
            task_success_rates.append(1 if task_success else 0)

            first_attempt = min(task_attempts, key=lambda x: x["sample_index"])
            task_pass_at_1.append(1 if first_attempt["status"] == "passed" else 0)

            if samples > 1:
                task_pass_at_k.append(1 if task_success else 0)

        metrics["model_accuracy"][model] = (
            sum(task_success_rates) / len(task_success_rates) if task_success_rates else None
        )
        pass_at_1[model] = sum(task_pass_at_1) / len(task_pass_at_1) if task_pass_at_1 else None
        if samples > 1:
            pass_at_k[model] = sum(task_pass_at_k) / len(task_pass_at_k) if task_pass_at_k else None
        else:
            pass_at_k[model] = pass_at_1[model]

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
    return metrics


def update_task_latest(task_id: str, attempt_summary: Dict) -> None:
    RUN_ARTIFACTS.mkdir(exist_ok=True)
    output_path = RUN_ARTIFACTS / f"{task_id}_latest.json"

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


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
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
    parser.add_argument("--install-deps", action="store_true", help="Install requirements.txt inside each attempt workspace")
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
    parser.set_defaults(allow_incomplete_diffs=None, allow_diff_rewrite_fallback=None)
    return parser.parse_args(argv)


def resolve_task_list(args: argparse.Namespace) -> List[str]:
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
    tasks: List[str],
    models: List[str],
    samples: int = 1,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    preferred_provider: Optional[str] = None,
    thinking_level: Optional[str] = None,
    sweep_thinking_levels: bool = False,
    include_thinking_variants: bool = False,
    include_tests: bool = False,
    install_deps: bool = False,
    output_dir: Path = RUN_ARTIFACTS,
    response_file: Optional[Path] = None,
    response_text: Optional[str] = None,
    allow_incomplete_diffs: Optional[bool] = None,
    allow_diff_rewrite_fallback: Optional[bool] = None,
    progress_callback: Optional[Callable[[str, str, int, Dict], None]] = None,
    run_id: Optional[str] = None,
) -> Dict:
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

    attempts: List[Dict] = []

    def _suggest_levels_for_model(model_id: str) -> List[str]:
        info = model_metadata.get(model_id) or {}
        params = {p.lower() for p in (info.get("supported_parameters") or []) if isinstance(p, str)}
        if "reasoning" not in params:
            return []
        # Default suggestion set; providers typically accept these effort levels
        return ["low", "medium", "high"]

    for model in models:
        # Determine which thinking levels to evaluate for this model
        levels: List[Optional[str]]
        if sweep_thinking_levels:
            suggested = _suggest_levels_for_model(model)
            levels = [None] + (suggested or ["low", "medium", "high"])  # fallback if unknown
        else:
            levels = [thinking_level] if thinking_level else [None]

        for level in levels:
            for task_id in tasks:
                metadata = load_metadata(task_id)
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
                        progress_callback(model=model, task_id=task_id, sample_index=sample_idx, summary=attempt_summary)

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
        duration = attempt.get('duration_seconds')
        if duration is not None:
            total_duration += duration
        api_latency = attempt.get('api_latency_seconds')
        if api_latency is not None:
            total_api_latency += api_latency
        usage = attempt.get('usage') or {}
        prompt_tokens = usage.get('prompt_tokens')
        if prompt_tokens is None:
            prompt_tokens = usage.get('input_tokens')
        completion_tokens = usage.get('completion_tokens')
        if completion_tokens is None:
            completion_tokens = usage.get('output_tokens')

        if prompt_tokens is not None:
            prompt_tokens = int(prompt_tokens)
            total_prompt_tokens += prompt_tokens
        if completion_tokens is not None:
            completion_tokens = int(completion_tokens)
            total_completion_tokens += completion_tokens

        pricing = model_metadata.get(attempt['model'])
        if pricing and (prompt_tokens is not None or completion_tokens is not None):
            attempt_cost = 0.0
            if prompt_tokens is not None:
                attempt_cost += prompt_tokens * pricing['prompt']
            if completion_tokens is not None:
                attempt_cost += completion_tokens * pricing['completion']
            attempt['cost_usd'] = attempt_cost
            total_cost += attempt_cost

    summary = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
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
        "metrics": compute_metrics(attempts, models, tasks, samples),
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

    latest_summary_path = RUN_ARTIFACTS / "latest_summary.json"
    store_text(latest_summary_path, json.dumps(summary, indent=2))

    return summary



def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    tasks = resolve_task_list(args)
    models = args.models
    samples = max(1, args.samples)
    allow_incomplete_diffs = (
        DEFAULT_ALLOW_INCOMPLETE_DIFFS
        if args.allow_incomplete_diffs is None
        else args.allow_incomplete_diffs
    )
    allow_diff_rewrite_fallback = (
        DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK
        if args.allow_diff_rewrite_fallback is None
        else args.allow_diff_rewrite_fallback
    )

    if args.response_file and (len(tasks) != 1 or len(models) != 1 or samples != 1):
        raise HarnessError("--response-file is only supported for single-task, single-model, single-sample runs.")

    if args.dry_run:
        for task_id in tasks:
            metadata = load_metadata(task_id)
            prompt = build_prompt(task_id, metadata, include_tests=args.include_tests)
            print(f"===== Prompt for {task_id} =====")
            print(prompt)
        return 0

    def progress_callback(model: str, task_id: str, sample_index: int, summary: Dict) -> None:
        print(f"[{model}] {task_id} sample {sample_index}: {summary['status']}")

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
    print(f"Run artifacts stored in {summary['run_dir']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    try:
        raise SystemExit(main())
    except HarnessError as exc:
        print(f"Harness error: {exc}", file=sys.stderr)
        raise SystemExit(1)
