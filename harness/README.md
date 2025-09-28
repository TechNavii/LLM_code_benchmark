# Harness Usage

The harness orchestrates benchmark runs against one or more tasks and OpenRouter models. For every task/model/sample combination it:
1. Loads metadata, composes the developer prompt (optionally including test files), and snapshots task instructions.
2. Requests a patch from the selected model (or replays a stored response).
3. Applies the patch inside an isolated copy of the task workspace.
4. Executes the task's evaluation command (unit tests, linters, integration scripts, etc.).
5. Persists prompts, responses, logs, and aggregate metrics under `runs/`.

## Prerequisites
- Python 3.11+ with `requests` installed (`pip install requests`).
- `patch` executable available on the system.
- `OPENROUTER_API_KEY` exported (see `.env.example` for guidance).
- Language runtimes aligned with the tasks you plan to execute:
  - Python tasks rely on `pytest` (installed per-task via `requirements.txt`).
  - JavaScript tasks target Node.js `>=18`.
  - Go tasks require the `go` toolchain (`go test`).
  - Rust tasks require `cargo`.
- Optional: pass `--install-deps` to install a task's `requirements.txt` inside each attempt workspace (requires network access).

## Task Catalog & Tags
Each task's metadata now includes a `tags` array describing language, category (bug fix vs feature), and domain focus. The aggregated catalogue at `tasks/catalog.json` provides a quick view of all tasks, which you can filter or feed into dashboards when constructing balanced evaluation suites.

## Quick Start
```bash
# Dry run (prints prompt only)
python3 harness/run_harness.py --task python_expert_workflow_scheduler --dry-run

# Evaluate a single task using an OpenRouter model
python3 harness/run_harness.py --task python_expert_workflow_scheduler --models openrouter/google/gemini-pro

# Replay a stored model response (offline validation)
python3 harness/run_harness.py --task python_expert_workflow_scheduler \
  --response-file path/to/offline_patch.txt

# Batch across all tasks and multiple models with two samples each
python3 harness/run_harness.py --tasks all \
  --models openrouter/google/gemini-pro openrouter/anthropic/claude-3 \
  --samples 2 --temperature 0.2
```

Key options:
- `--tasks all` discovers every task subdirectory containing `metadata.json`.
- `--include-tests` adds test files to the model prompt context.
- `--install-deps` installs `requirements.txt` within each isolated workspace.
- `--output-dir` changes where run artifacts are stored (defaults to `runs/`).

## Output Artifacts
Each run produces a timestamped directory under `runs/` containing:
- `summary.json`: run configuration, per-attempt outcomes, and aggregate metrics (model accuracy, pass@k, etc.).
- One subdirectory per attempt with `prompt.txt`, `response.txt`, `patch.diff`, `stdout.log`, and `stderr.log` (trimmed for size).
- `latest_summary.json`: shortcut to the most recent run summary.
- `{task_id}_latest.json`: best recent attempt status for each task (updated with pass > fail > error precedence).

These artifacts feed CI dashboards, leaderboards, or offline analytics. Adjust the harness as new task languages or evaluation workflows are added.

## Tool-Calling Tasks
Some tasks are tagged with `tool_call`. They bundle mock CLIs under `workspace/tools/` that emit random tokens so the tests can verify the model actually invoked the tool. Ensure the execution environment allows running those scripts (they are self-contained and offline).
