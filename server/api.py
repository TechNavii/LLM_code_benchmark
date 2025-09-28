from __future__ import annotations

import asyncio
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from harness.run_harness import run_tasks
from server import database
from server.progress import progress_manager

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    """Populate os.environ from a dotenv-style file if variables are missing."""
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
app = FastAPI(title="Benchmark Harness API")
app.mount("/ui", StaticFiles(directory=str(ROOT / "gui"), html=True), name="ui")
app.mount("/artifacts", StaticFiles(directory=str(ROOT / "runs"), check_dir=False), name="artifacts")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

database.init_db()


class RunRequest(BaseModel):
    models: List[str] = Field(..., description="List of model identifiers")
    tasks: Optional[List[str]] = Field(None, description="Subset of task IDs; defaults to all")
    samples: int = 1
    temperature: float = 0.0
    max_tokens: int = 800
    include_tests: bool = False
    install_deps: bool = False
    response_text: Optional[str] = None


class RunLaunchResponse(BaseModel):
    run_id: str


class RunDetailResponse(BaseModel):
    summary: Dict[str, Any]




@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/ui/index.html")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runs")
def list_runs(limit: int = 50) -> Dict[str, Any]:
    rows = database.list_runs(limit)
    return {
        "runs": [
            {
                "run_id": row["id"],
                "timestamp_utc": row["timestamp_utc"],
                "model_id": row["model_id"],
                "accuracy": row["accuracy"],
                "total_cost_usd": row["total_cost"],
                "total_duration_seconds": row["total_duration"],
            }
            for row in rows
        ]
    }


@app.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: str) -> RunDetailResponse:
    summary = database.get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunDetailResponse(summary=summary)


@app.get("/leaderboard")
def get_leaderboard() -> Dict[str, Any]:
    rows = database.leaderboard()
    return {
        "models": [
            {
                "model_id": row["model_id"],
                "best_accuracy": row["best_accuracy"],
                "cost_at_best": row["cost_at_best"],
                "duration_at_best": row["duration_at_best"],
                "runs": row["runs"],
            }
            for row in rows
        ]
    }


@app.post("/runs", response_model=RunLaunchResponse)
async def create_run(request: RunRequest) -> RunLaunchResponse:
    if not request.models:
        raise HTTPException(status_code=400, detail="At least one model must be provided")

    tasks = request.tasks or harness_tasks_all()
    run_id = progress_manager.generate_run_id()
    await progress_manager.start_run(run_id, {
        "models": request.models,
        "tasks": tasks,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    })

    config = {
        "tasks": tasks,
        "models": request.models,
        "samples": request.samples,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "include_tests": request.include_tests,
        "install_deps": request.install_deps,
        "output_dir": Path("runs"),
        "response_text": request.response_text,
        "run_id": run_id,
    }

    async def runner() -> None:
        def progress_callback(model: str, task_id: str, sample_index: int, summary: Dict[str, Any]) -> None:
            payload = {
                "model": model,
                "task_id": task_id,
                "sample_index": sample_index,
                "status": summary.get("status"),
                "duration_seconds": summary.get("duration_seconds"),
                "prompt_tokens": (summary.get("usage") or {}).get("prompt_tokens"),
                "completion_tokens": (summary.get("usage") or {}).get("completion_tokens"),
                "cost_usd": summary.get("cost_usd"),
                "error": summary.get("error"),
            }
            progress_manager.publish_attempt(run_id, payload)

        try:
            summary = await asyncio.to_thread(
                run_tasks,
                progress_callback=progress_callback,
                **config,
            )
            database.save_run(summary)
            progress_manager.complete(run_id, summary)
        except Exception as exc:
            progress_manager.fail(run_id, str(exc))
            raise

    asyncio.create_task(runner())
    return RunLaunchResponse(run_id=run_id)


def harness_tasks_all() -> List[str]:
    from harness.run_harness import discover_tasks

    return discover_tasks()


@app.websocket("/runs/{run_id}/stream")
async def run_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()
    try:
        queue = await progress_manager.subscribe(run_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") in {"complete", "error"}:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await progress_manager.unsubscribe(run_id, queue)
