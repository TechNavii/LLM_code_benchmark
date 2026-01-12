# Benchmark Dashboard & API

The project now ships with an HTTP API and lightweight web UI for launching evaluations, inspecting per-task outcomes, and tracking model leaderboards.

## Requirements
Install the API dependencies (existing harness requirements still apply):

```
pip install -r server/requirements.txt
```

## Running the server

```
uvicorn server.api:app --reload
```

By default the API listens on `http://127.0.0.1:8000`. The web UI is served at `http://127.0.0.1:8000/ui/`.

## Launching runs from the UI
1. Open the dashboard at `/ui/`.
2. Choose a model source:
   - **OpenRouter**: enter one or more model IDs.
   - **LM Studio**: select a model from the dropdown (switching models will unload the previous model and load the new one).
3. Optionally enter task IDs.
4. Submit the form – the backend executes the harness and returns the summary once complete.
5. Review per-task status, token usage, and cost in the results table.

## REST Endpoints
- `POST /runs`: launch a run (synchronous for now) with JSON body `{ models: [...], tasks?: [...], samples?: int, ... }`.
- `GET /runs`: list recent runs with aggregate stats.
- `GET /runs/{run_id}`: fetch the full summary JSON for an individual run.
- `GET /leaderboard`: highest accuracy and cost metrics per model.
- `GET /health`: health check.

## Persistence
Run summaries and attempt-level metrics are stored in `runs/history.db`. The schema:

```
runs(run_id, timestamp_utc, model_id, tasks_json, accuracy, total_cost, total_duration, summary_json)
attempts(run_id, task_id, status, duration, prompt_tokens, completion_tokens, cost, error)
```

The leaderboard and history views query this database to rank models and display previous results.

## Notes
- The harness refactoring introduced `run_tasks(...)` which returns the same summary dictionary used by the CLI. The API wraps this function and persists the summary before responding.
- Progress streaming is not yet implemented; the endpoint responds once the run completes. This keeps the initial UI simple and avoids concurrent worker management.
- Static assets live under `gui/` and are served directly by FastAPI’s `StaticFiles`.

## Live progress
- After launching a run, the dashboard opens a WebSocket (`/runs/{run_id}/stream`) and updates each task card as soon as the harness records an attempt.
- The final summary is pushed when the run completes or fails, so you no longer have to refresh manually.
