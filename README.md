# Benchmark Harness

A full-stack evaluation lab for benchmarking AI code-generation models across a curated suite of programming tasks. The repository bundles:

- **FastAPI backend** that exposes run and leaderboard APIs, persists run history, and streams live attempt progress.
- **Futuristic dashboard UI** (vanilla JS + CSS) for launching runs, viewing leaderboards, and drilling into per-task telemetry with neon-themed visuals.
- **Python harness** that orchestrates task execution end-to-end: prompting models, applying patches, running task-specific test suites, and emitting rich artifacts.
- **Language-diverse task catalog** (31 tasks across Python, JavaScript, Go, Rust, C++, and HTML) geared toward expert-level reasoning and tool use.

Use the harness to compare LLM performance, then monitor results in the dashboard or consume raw artifacts for offline analysis.

---
## Table of Contents
1. [Repository Layout](#repository-layout)
2. [Prerequisites](#prerequisites)
3. [Environment Configuration](#environment-configuration)
4. [Launching the Benchmark Dashboard](#launching-the-benchmark-dashboard)
5. [Running the Harness from the CLI](#running-the-harness-from-the-cli)
6. [Inspecting Runs & Artifacts](#inspecting-runs--artifacts)
7. [Task Catalog Overview](#task-catalog-overview)
8. [Per-Language Testing Notes](#per-language-testing-notes)
9. [Frontend Development Tips](#frontend-development-tips)
10. [Troubleshooting](#troubleshooting)

---
## Repository Layout

```
benchmark/
├── gui/                     # Neon dashboard front-end (index.html, run.html, style.css, main.js, run.js)
├── server/                  # FastAPI application and SQLite persistence layer
├── harness/                 # Python orchestrator for launching benchmark runs
├── tasks/                   # Task catalog (metadata, instructions, test harnesses, workspaces)
├── docs/                    # Supplementary documentation (GUI, tool-calling strategy, Go setup)
├── runs/                    # Run history, SQLite DB, per-attempt artifacts (generated)
└── README.md                # You're here 🌌
```

Key backend files:
- `server/api.py` – FastAPI app, WebSocket streaming, `/ui` and `/artifacts` mounts.
- `server/database.py` – SQLite helpers, leaderboard query tied to best-accuracy attempts.
- `harness/run_harness.py` – core orchestration logic (progress callbacks, metrics aggregation).

---
## Prerequisites

Install runtimes that match the languages in the task catalog:

| Runtime | Minimum Version | Purpose |
|---------|-----------------|---------|
| Python  | 3.11+           | FastAPI backend & harness
| Node.js | 18+             | JavaScript/HTML tasks & GUI tooling
| Go      | 1.21+           | Go tasks (`go test`)
| Rust    | 1.74+           | Rust tasks (`cargo test`)
| C++     | C++20 toolchain | C++ tasks (`g++` + `pthread`)
| SQLite  | bundled         | Run history storage

Python dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r harness/requirements.txt -r server/requirements.txt
```

Node dependencies are task-scoped: most JavaScript/HTML tasks are CLI-only and run with plain Node.js.

---
## Environment Configuration

Sensitive values live in a `.env` file (loaded automatically by both the server and harness). Populate the template:

```bash
cp .env.example .env
# then edit .env
OPENROUTER_API_KEY=sk-or-...
DEFAULT_MODEL=openrouter/google/gemini-pro
DEFAULT_TEMPERATURE=0.0
```

Environment variables present in the shell always take precedence over `.env` values.

### Optional: LM Studio (local models)

To run local models via [LM Studio](https://lmstudio.ai/), start the LM Studio server (OpenAI-compatible API) and set:

```bash
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
```

Model IDs use the `lmstudio/` prefix (example: `lmstudio/liquid/lfm2.5-1.2b`). In the dashboard, selecting a different LM Studio model will unload all currently loaded models and load the newly selected one (requires the LM Studio CLI `lms` on `PATH`). After runs complete, the harness will also attempt to unload LM Studio models to free memory.

---
## Launching the Benchmark Dashboard

1. **Start the FastAPI server**
   ```bash
   uvicorn server.api:app --reload
   ```
   The app mounts static assets at `/ui` and exposes run history at `/runs`.

2. **Open the UI**
   Visit `http://127.0.0.1:8000/ui/index.html` in your browser. The neon dashboard provides:
   - **Launch Run**: configure models, tasks, sample count, and behavioral flags.
   - **Latest Run Results**: live-updating status table with PASS/FAIL chips.
   - **Leaderboard**: best-accuracy runs per model with aligned cost/duration.
   - **Recent Runs**: history of previous runs (links to detailed views).

3. **Run Detail View**
   Clicking a Run ID opens `run.html`, a two-column experience showing all attempts on the left and a detailed metrics/log explorer on the right. Logs are streamed from the `/artifacts/<run_id>/<attempt_dir>/...` endpoint.

---
## Running the Harness from the CLI

The harness lets you execute tasks against one or more models directly from the terminal.

```bash
# Dry run (no model call, just prompt generation)
python3 harness/run_harness.py --task python_expert_workflow_scheduler --dry-run

# Evaluate a single task against an OpenRouter model
python3 harness/run_harness.py \
  --task python_expert_workflow_scheduler \
  --models openrouter/google/gemini-pro \
  --include-tests \
  --install-deps

# Run multiple models across the entire catalog with two samples each
python3 harness/run_harness.py \
  --tasks all \
  --models openrouter/google/gemini-pro openrouter/anthropic/claude-3 \
  --samples 2 \
  --temperature 0.2
```

Notable CLI flags:
- `--response-file` / `--response-text`: replay stored responses offline.
- `--output-dir`: change artifact location (default `runs/`).
- `--install-deps`: install `requirements.txt` inside each sandbox (requires network access).

Harness progress is streamed to the dashboard automatically via WebSocket once you start a run.

---
## Inspecting Runs & Artifacts

Each run writes a directory under `runs/`:

```
runs/
├── history.db                  # SQLite DB backing the leaderboard & recent runs
├── latest_summary.json         # Shortcut to the most recent run
├── rust_feature_chunk_iter_latest.json
├── run_YYYYMMDDThhmmssZ_xxxxx/ # Per-run artifact bundle
│   ├── summary.json            # Aggregate metrics, attempts, token counts
│   ├── <task>__<model>__sample00/
│   │   ├── prompt.txt
│   │   ├── response.txt
│   │   ├── patch.diff
│   │   ├── stdout.log
│   │   └── stderr.log
```

Artifacts are also available over HTTP at `/artifacts/<run>/<attempt_file>`—the run-detail UI consumes the same endpoint for inline log viewers.

---
## Task Catalog Overview

The catalog now contains **31** tasks spanning six languages:

| Language    | Count | Examples |
|-------------|-------|----------|
| Python (9)  | python_expert_workflow_scheduler, python_expert_time_series_interpolator, python_tool_weather_cli |
| JavaScript (6) | javascript_expert_promise_pool, javascript_expert_markdown_toc, javascript_feature_cli_todo |
| Go (6)      | go_expert_token_bucket, go_expert_lru_cache, go_feature_wordcount |
| Rust (6)    | rust_expert_lru_cache, rust_expert_time_bucketer, rust_expert_async_rate_limiter |
| C++ (2)     | cpp_expert_thread_pool, cpp_expert_sparse_matrix |
| HTML (2)    | html_expert_form_validator, html_expert_heatmap_renderer |

Each task resides in `tasks/<task_id>/` and provides:
- `metadata.json` – evaluation command, tags, difficulty, runtime limits.
- `instructions.md` – scenario description and success criteria.
- `workspace/` – starter code (often intentionally incomplete or buggy).
- `tests/` – reference tests or harnesses used to judge success.

New expert tasks ship with scaffolding that intentionally raises `NotImplementedError`/`panic`/`throw new Error`. Implementations are left to benchmark participants.

---
## Per-Language Testing Notes

Spot-check tasks by invoking their local test harnesses:

```bash
# Python
cd tasks/python_expert_workflow_scheduler && pytest -q

# Go (cache build artifacts locally for sandboxed environments)
cd tasks/go_expert_token_bucket/workspace && GOCACHE=$(pwd)/.gocache go test ./...

# JavaScript / HTML
cd tasks/javascript_expert_promise_pool && node tests/run-tests.js
cd tasks/html_expert_heatmap_renderer && node tests/run-tests.js

# Rust
cd tasks/rust_expert_lru_cache/workspace && cargo test

# C++
cd tasks/cpp_expert_sparse_matrix && tests/run-tests.sh
```

Most tasks fail today because the reference solution is intentionally missing. The goal is to benchmark how well models can complete or repair them.

---
## Frontend Development Tips

- Static assets are served from `/ui`. Update `gui/style.css`, `gui/main.js`, and `gui/run.js` to tweak visuals or behavior.
- The neon theme uses CSS variables defined at the top of `style.css`. Animations (`@keyframes nebulaShift` & `fadeSlide`) give the dashboard a futuristic look.
- Run detail cards fetch run summaries from `/runs/<run_id>` and attempt logs from `/artifacts/...`—handy for building custom visualizations.
- The leaderboard fetch now aligns cost/duration with the best-accuracy attempt via the database CTE in `database.py`.

---
## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| **Dashboard shows blank or outdated styles** | Force refresh (`Ctrl/Cmd+Shift+R`). Assets are cached aggressively by browsers. |
| **API key missing errors** | Ensure `.env` exists with `OPENROUTER_API_KEY`. The server and harness both load it automatically on startup. |
| **Go builds fail under sandbox** | Set a writable Go build cache: `GOCACHE=$(pwd)/.gocache go test ./...`. |
| **Harness run crashes on dependency install** | Use `--install-deps` only when sandboxing allows network access, or pre-install dependencies manually. |
| **Task tests import errors** | Most test suites expect their `workspace/` folder on `sys.path`/`NODE_PATH`. The provided tests already inject paths; mimic that pattern when adding new tasks. |

---
Happy benchmarking! Feel free to extend the catalog, customize the dashboard, or integrate the harness into larger evaluation pipelines.
