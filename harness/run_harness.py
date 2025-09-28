#!/usr/bin/env python3
"""Benchmark harness for evaluating multiple tasks/models via OpenRouter."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Callable

try:
    import requests
except ImportError:  # pragma: no cover - optional for offline dry runs
    requests = None


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    """Populate os.environ with keys from a dotenv file if missing."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


load_env(ROOT / ".env")

TASKS_ROOT = ROOT / "tasks"
RUN_ARTIFACTS = ROOT / "runs"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openrouter/google/gemini-pro")
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
MAX_LOG_CHARS = 20000


class HarnessError(RuntimeError):
    """Custom harness error for clearer exception handling."""


def fetch_model_pricing(models: List[str]) -> Dict[str, Dict[str, float]]:
    if requests is None:
        return {}

    try:
        response = requests.get("https://openrouter.ai/api/v1/models", headers={
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
            "HTTP-Referer": "benchmark-harness",
        }, timeout=60)
        response.raise_for_status()
    except Exception:
        return {}

    data = response.json()
    pricing: Dict[str, Dict[str, float]] = {}
    for entry in data.get('data', []):
        model_id = entry.get('id')
        if model_id not in models and f"openrouter/{model_id}" not in models:
            continue
        model_pricing = entry.get('pricing') or {}
        try:
            prompt_rate = float(model_pricing.get('prompt', 0))
            completion_rate = float(model_pricing.get('completion', 0))
        except (TypeError, ValueError):
            continue
        pricing[model_id] = {"prompt": prompt_rate, "completion": completion_rate}
        pricing[f"openrouter/{model_id}"] = {"prompt": prompt_rate, "completion": completion_rate}
    return pricing


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

    prompt = textwrap.dedent(
        f"""
        You are an autonomous software developer. Apply a minimal fix to satisfy the task instructions and existing tests.

        Task instructions:
        {instructions}

        Return a unified diff patch enclosed in a single ```diff fenced code block and nothing else.

        Project context:
        {os.linesep.join(contextual_snippets)}
        """
    ).strip()

    return prompt


def call_openrouter(prompt: str, model: str, temperature: float, max_tokens: int) -> str:
    if requests is None:
        raise HarnessError("The 'requests' library is required to call OpenRouter.")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HarnessError("OPENROUTER_API_KEY environment variable is not set.")

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

    start_time = time.perf_counter()
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    duration = time.perf_counter() - start_time
    response.raise_for_status()
    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:  # pragma: no cover - API schema issues
        raise HarnessError(f"Unexpected OpenRouter response payload: {data}") from exc

    return content, data, duration


def extract_patch(raw_response: str) -> str:
    fence = "```diff"
    if fence not in raw_response:
        raise HarnessError("Model response does not contain a ```diff fenced block.")
    start = raw_response.index(fence) + len(fence)
    try:
        end = raw_response.index("```", start)
    except ValueError as exc:
        raise HarnessError("Model response does not contain closing ``` fence.") from exc
    patch = raw_response[start:end]
    return patch.strip() + "\n"


def clean_patch_text(patch_text: str) -> tuple[str, bool]:
    ansi_escape = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
    cleaned = ansi_escape.sub('', patch_text)
    if '\x1b' in cleaned:
        raise HarnessError('Patch contains unsupported control characters.')
    git_style = cleaned.startswith('--- a/') or cleaned.startswith('diff --git')
    return cleaned, git_style


def prepare_run_directory(task_id: str, metadata: Dict) -> Path:
    task_dir = TASKS_ROOT / task_id
    workspace_dir = task_dir / metadata.get("workspace_dir", "workspace")
    tests_dir = task_dir / metadata.get("tests_dir", "tests")

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"{task_id}_"))
    run_workspace = tmp_dir / "workspace"
    shutil.copytree(workspace_dir, run_workspace)
    if tests_dir.exists():
        shutil.copytree(tests_dir, run_workspace / "tests")

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


def apply_patch(patch_text: str, workspace_path: Path) -> None:
    cleaned_patch, git_style = clean_patch_text(patch_text)
    patch_args = ["patch", "--force"]
    patch_args.append("-p0" if not git_style else "-p1")
    try:
        process = subprocess.run(
            patch_args,
            input=cleaned_patch.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace_path),
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise HarnessError("Failed to apply patch: patch command timed out")

    if process.returncode != 0:
        raise HarnessError(
            "Failed to apply patch:\n"
            f"STDOUT:\n{process.stdout.decode()}\n"
            f"STDERR:\n{process.stderr.decode()}"
        )


def run_evaluation(command: List[str], workspace_path: Path, timeout: int, env_updates: Optional[Dict[str, str]] = None, working_dir: Optional[str] = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    if env_updates:
        env.update(env_updates)
    workdir = workspace_path if working_dir is None else workspace_path / working_dir
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workdir),
        timeout=timeout,
        check=False,
        env=env,
    )
    return process


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
    include_tests: bool,
    install_deps_flag: bool,
    response_override: Optional[str],
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
        "sample_index": sample_index,
        "status": "error",
        "return_code": None,
        "error": None,
        "attempt_dir": str(attempt_dir.relative_to(run_dir)),
    }

    try:
        if response_override is not None:
            raw_response = response_override
            response_meta = None
            api_latency = None
        else:
            raw_response, response_meta, api_latency = call_openrouter(prompt, model, temperature, max_tokens)
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
        patch_text = extract_patch(raw_response)
        store_text(attempt_dir / "patch.diff", patch_text)

        workspace_path = prepare_run_directory(task_id, metadata)
        if install_deps_flag:
            install_requirements(workspace_path)
        apply_patch(patch_text, workspace_path)

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
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--response-file", type=Path, help="Replay a stored model response (single-task runs only)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts only, skip model calls and evaluation")
    parser.add_argument("--include-tests", action="store_true", help="Include test files in the model prompt context")
    parser.add_argument("--install-deps", action="store_true", help="Install requirements.txt inside each attempt workspace")
    parser.add_argument("--output-dir", type=Path, default=RUN_ARTIFACTS, help="Directory to write run artifacts")
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
    max_tokens: int = 800,
    include_tests: bool = False,
    install_deps: bool = False,
    output_dir: Path = RUN_ARTIFACTS,
    response_file: Optional[Path] = None,
    response_text: Optional[str] = None,
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

    pricing_table = fetch_model_pricing(models)

    response_override = None
    if response_file:
        response_override = Path(response_file).read_text(encoding="utf-8")
    elif response_text is not None:
        response_override = response_text

    attempts: List[Dict] = []

    for model in models:
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
                    include_tests=include_tests,
                    install_deps_flag=install_deps,
                    response_override=response_override,
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

        pricing = pricing_table.get(attempt['model'])
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
        "samples": samples,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "include_tests": include_tests,
        "install_deps": install_deps,
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
        "pricing": {model: pricing_table.get(model) for model in models if pricing_table.get(model)},
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
        include_tests=args.include_tests,
        install_deps=args.install_deps,
        output_dir=args.output_dir,
        response_file=args.response_file,
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
