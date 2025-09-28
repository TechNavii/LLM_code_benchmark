# Repository Guidelines

## Project Structure & Module Organization
- `gui/` – neon-themed dashboard (`index.html`, `run.html`, `style.css`, JS controllers).
- `server/` – FastAPI app (`api.py`, `database.py`, `progress.py`) and SQLite mounting.
- `harness/` – Python runner orchestrating prompts, patches, metrics, and artifacts.
- `tasks/` – catalog of 31 language-specific challenges; each task ships `metadata.json`, `instructions.md`, `workspace/`, and tests.
- `runs/` – generated artifacts (summaries, attempt logs, SQLite DB); ignored by git.
- `docs/` – extra references (GUI notes, tool-calling strategy, Go setup).

## Build, Test, and Development Commands
```bash
uvicorn server.api:app --reload   # serve backend + UI
python3 harness/run_harness.py ... # launch benchmark runs from CLI
cd tasks/<task>/ && pytest -q      # Python task tests
cd tasks/<task>/workspace && GOCACHE=$(pwd)/.gocache go test ./...
cd tasks/<task>/workspace && cargo test
cd tasks/<task>/ && node tests/run-tests.js
```
Use task-specific commands to validate scaffolding; most solutions are intentionally incomplete and will fail until implemented.

## Coding Style & Naming Conventions
- **Python**: PEP 8; prefer type hints; run `ruff`/`black` if available.
- **Go**: idiomatic `gofmt`; maintain `module` per workspace (`go mod tidy`).
- **Rust**: `rustfmt`; use snake_case module and variable names.
- **JS/HTML/CSS**: semi-colon-less modules allowed; keep neon styling within existing CSS variables; use kebab-case class names.
- File names mirror task IDs (`<language>_<category>_<descriptor>`).

## Testing Guidelines
- Each task’s `metadata.json` declares the canonical test command (pytest, node runner, cargo, go test, custom shell script).
- Tests reside under `tasks/<task>/tests/`; name new tests `test_*.py`, `*_test.go`, `*_test.rs`, or `*-tests.js` accordingly.
- Dashboard smoke checks rely on manual `uvicorn` run + browser refresh; no automated UI tests yet.

## Commit & Pull Request Guidelines
- Write concise, imperative commits (e.g., `Add neon run-detail layout`, `Fix leaderboard query`). Group related changes per commit.
- Pull requests should summarize scope, note affected tasks/modules, list test commands executed, and include UI screenshots when styling changes.
- Link issues or runs when applicable; highlight remaining TODOs and follow-up actions.

## Security & Configuration Tips
- Never commit secrets; `.env` is ignored. Update `.env.example` when adding new required variables.
- For local model testing, confirm `OPENROUTER_API_KEY` is set before invoking the harness.
