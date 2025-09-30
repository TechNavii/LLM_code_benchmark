"""Application router containing benchmark API endpoints."""

import asyncio
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from harness.config import get_settings as get_harness_settings
from harness.run_harness import run_tasks
from server import database
from server.config import get_settings
from server.monitoring import timed
from server.progress import progress_manager
from server.validators import ValidatedRunRequest


router = APIRouter()
settings = get_settings()
logger = structlog.get_logger(__name__)
HARNESS_SETTINGS = get_harness_settings()
DEFAULT_ALLOW_INCOMPLETE_DIFFS = HARNESS_SETTINGS.allow_incomplete_diffs
DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK = HARNESS_SETTINGS.allow_diff_rewrite_fallback
DEFAULT_MAX_TOKENS = HARNESS_SETTINGS.default_max_tokens
DEFAULT_TEMPERATURE = HARNESS_SETTINGS.default_temperature


class RunLaunchResponse(BaseModel):
    run_id: str


class RunDetailResponse(BaseModel):
    summary: Dict[str, Any]


class RunSummary(BaseModel):
    run_id: str
    timestamp_utc: Optional[str]
    model_id: Optional[str]
    accuracy: Optional[float]
    total_cost_usd: Optional[float]
    total_duration_seconds: Optional[float]


class RunListResponse(BaseModel):
    runs: List[RunSummary]


class RunRequestPayload(BaseModel):
    models: List[str]
    tasks: Optional[List[str]] = None
    samples: int = 1
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    include_tests: bool = False
    install_deps: bool = False
    allow_incomplete_diffs: bool = DEFAULT_ALLOW_INCOMPLETE_DIFFS
    allow_diff_rewrite_fallback: bool = DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK
    response_text: Optional[str] = None


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/ui/index.html")


@router.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/runs", response_model=RunListResponse, tags=["runs"])
def list_runs(limit: int = 50) -> RunListResponse:
    rows = database.list_runs(limit)
    summaries = [
        RunSummary(
            run_id=row["id"],
            timestamp_utc=row["timestamp_utc"],
            model_id=row["model_id"],
            accuracy=row["accuracy"],
            total_cost_usd=row["total_cost"],
            total_duration_seconds=row["total_duration"],
        )
        for row in rows
    ]
    return RunListResponse(runs=summaries)


@router.get("/runs/{run_id}", response_model=RunDetailResponse, tags=["runs"])
def get_run(run_id: str) -> RunDetailResponse:
    summary = database.get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunDetailResponse(summary=summary)


@router.get("/leaderboard", tags=["leaderboard"])
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


@router.post("/runs", response_model=RunLaunchResponse, tags=["runs"])
@timed
async def create_run(request: RunRequestPayload) -> RunLaunchResponse:
    allowlist = settings.model_allowlist or None
    try:
        validated = ValidatedRunRequest(**request.model_dump(), model_allowlist=allowlist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tasks = validated.tasks or harness_tasks_all()
    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks available to execute.")

    run_id = progress_manager.generate_run_id()
    await progress_manager.start_run(
        run_id,
        {
            "models": validated.models,
            "tasks": tasks,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "samples": validated.samples,
            "temperature": validated.temperature,
            "max_tokens": validated.max_tokens,
            "include_tests": validated.include_tests,
            "install_deps": validated.install_deps,
            "allow_incomplete_diffs": validated.allow_incomplete_diffs,
            "allow_diff_rewrite_fallback": validated.allow_diff_rewrite_fallback,
        },
    )

    output_dir = Path(settings.runs_root)

    def progress_proxy(model: str, task_id: str, sample_index: int, summary: Dict[str, Any]) -> None:
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
            "diff_rewrite_fallback_used": summary.get("diff_rewrite_fallback_used"),
        }
        progress_manager.publish_attempt(run_id, payload)

    async def runner() -> None:
        try:
            summary = await asyncio.to_thread(
                run_tasks,
                tasks=tasks,
                models=validated.models,
                samples=validated.samples,
                temperature=validated.temperature,
                max_tokens=validated.max_tokens,
                include_tests=validated.include_tests,
                install_deps=validated.install_deps,
                allow_incomplete_diffs=validated.allow_incomplete_diffs,
                allow_diff_rewrite_fallback=validated.allow_diff_rewrite_fallback,
                output_dir=output_dir,
                response_text=validated.response_text,
                progress_callback=progress_proxy,
                run_id=run_id,
            )
        except Exception as exc:  # pragma: no cover - background task
            logger.exception("run.failed", run_id=run_id, error=str(exc))
            progress_manager.fail(run_id, str(exc))
        else:
            database.save_run(summary)
            progress_manager.complete(run_id, summary)

    asyncio.create_task(runner())
    return RunLaunchResponse(run_id=run_id)


@router.websocket("/runs/{run_id}/stream")
async def run_stream(websocket: WebSocket, run_id: str) -> None:
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


def harness_tasks_all() -> List[str]:
    from harness.run_harness import discover_tasks

    return discover_tasks()


__all__ = [
    "router",
    "RunLaunchResponse",
    "RunDetailResponse",
    "RunListResponse",
    "RunRequestPayload",
]


RunRequestPayload.model_rebuild()
RunLaunchResponse.model_rebuild()
RunDetailResponse.model_rebuild()
RunSummary.model_rebuild()
RunListResponse.model_rebuild()
