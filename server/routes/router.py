"""Application router containing benchmark API endpoints."""

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from harness.config import get_settings as get_harness_settings
from harness.exceptions import HarnessError
from harness.run_harness import (
    run_tasks,
    fetch_model_metadata,
    retry_api_error_attempts,
    load_api_error_attempts,
    load_failed_attempts,
    retry_failed_attempts,
    load_incomplete_attempts,
    resume_incomplete_run,
)
from server import database
from server.config import get_settings
from server.monitoring import timed
from server.progress import progress_manager
from server.routes.auth import require_api_token
from server.routes.background import run_in_thread_with_callbacks
from server.validators import ValidatedRunRequest


router = APIRouter()
settings = get_settings()
logger = structlog.get_logger(__name__)
HARNESS_SETTINGS = get_harness_settings()
_background_tasks: set = set()
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
    provider: Optional[str] = None
    include_tests: bool = False
    install_deps: bool = False
    allow_incomplete_diffs: bool = DEFAULT_ALLOW_INCOMPLETE_DIFFS
    allow_diff_rewrite_fallback: bool = DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK
    response_text: Optional[str] = None
    thinking_level: Optional[str] = None
    include_thinking_variants: bool = False
    sweep_thinking_levels: bool = False


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
                "thinking_level": row.get("thinking_level"),
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
async def create_run(request: RunRequestPayload, _: None = Depends(require_api_token)) -> RunLaunchResponse:
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
            "provider": validated.provider,
            "include_tests": validated.include_tests,
            "install_deps": validated.install_deps,
            "allow_incomplete_diffs": validated.allow_incomplete_diffs,
            "allow_diff_rewrite_fallback": validated.allow_diff_rewrite_fallback,
            "thinking_level": validated.thinking_level,
            "include_thinking_variants": validated.include_thinking_variants,
            "sweep_thinking_levels": validated.sweep_thinking_levels,
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
            "provider": validated.provider,
            "thinking_level_applied": summary.get("thinking_level_applied"),
            "thinking_level_requested": summary.get("thinking_level_requested"),
        }
        progress_manager.publish_attempt(run_id, payload)

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("run.failed", run_id=run_id, error=str(exc))
            progress_manager.fail(run_id, str(exc))

        def on_success(summary: Dict[str, Any]) -> None:
            database.save_run(summary)
            progress_manager.complete(run_id, summary)

        await run_in_thread_with_callbacks(
            run_tasks,
            tasks=tasks,
            models=validated.models,
            samples=validated.samples,
            temperature=validated.temperature,
            max_tokens=validated.max_tokens,
            preferred_provider=validated.provider,
            thinking_level=validated.thinking_level,
            sweep_thinking_levels=validated.sweep_thinking_levels,
            include_thinking_variants=validated.include_thinking_variants,
            include_tests=validated.include_tests,
            install_deps=validated.install_deps,
            allow_incomplete_diffs=validated.allow_incomplete_diffs,
            allow_diff_rewrite_fallback=validated.allow_diff_rewrite_fallback,
            output_dir=output_dir,
            response_text=validated.response_text,
            progress_callback=progress_proxy,
            run_id=run_id,
            on_success=on_success,
            on_error=on_error,
        )

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return RunLaunchResponse(run_id=run_id)


@router.delete("/leaderboard/{model_id:path}", tags=["leaderboard"])
def delete_leaderboard_entry(
    model_id: str,
    thinking_level: Optional[str] = None,
    _: None = Depends(require_api_token),
) -> Dict[str, Any]:
    removed = database.delete_runs_for_model(model_id, thinking_level)
    status = "removed" if removed else "already_missing"
    return {
        "model_id": model_id,
        "thinking_level": thinking_level,
        "removed_runs": removed,
        "status": status,
    }


@router.get("/models/capabilities", tags=["models"])
def get_model_capabilities(model_id: str) -> Dict[str, Any]:
    model_id = model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id must be provided")
    metadata = fetch_model_metadata([model_id])
    info = metadata.get(model_id) or metadata.get(f"openrouter/{model_id}")
    if not info:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")
    supported_parameters = [param for param in info.get("supported_parameters", []) if isinstance(param, str)]
    supported_lower = {param.lower() for param in supported_parameters}
    supports_reasoning = "reasoning" in supported_lower
    suggested_levels: List[str] = []
    if supports_reasoning:
        suggested_levels = ["low", "medium", "high"]
    supports_budget_tokens = False
    supports_budget_seconds = False
    if supports_reasoning:
        # Many providers accept numerical budgets even if not documented.
        supports_budget_tokens = True
        supports_budget_seconds = True
    return {
        "model_id": model_id,
        "supports_thinking": supports_reasoning,
        "thinking_variant": info.get("thinking_variant"),
        "supported_parameters": supported_parameters,
        "suggested_levels": suggested_levels,
        "supports_budget_tokens": supports_budget_tokens,
        "supports_budget_seconds": supports_budget_seconds,
    }


def _extract_lmstudio_context_length(entry: Dict[str, Any]) -> Optional[int]:
    candidates = (
        "max_context_length",
        "context_length",
        "context_window",
        "context_size",
        "n_ctx",
    )
    for key in candidates:
        value = entry.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _lmstudio_native_base_url(base_url: str) -> str:
    trimmed = (base_url or "").rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed


@router.get("/models/lmstudio", tags=["models"])
def list_lmstudio_models() -> Dict[str, Any]:
    base_url = (settings.lmstudio_base_url or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=500, detail="LM Studio base URL is not configured")

    openai_models_url = f"{base_url}/models"
    native_base = _lmstudio_native_base_url(base_url)
    native_models_url = f"{native_base}/api/v0/models"

    payload: Dict[str, Any] | None = None
    last_error: Optional[str] = None

    # Prefer LM Studio's native endpoint when available (includes max_context_length).
    for url in (native_models_url, openai_models_url):
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                raw = response.read().decode("utf-8")
        except (URLError, HTTPError) as exc:
            last_error = f"Unable to reach LM Studio server at {url}: {exc}"
            continue

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            last_error = f"LM Studio server returned a non-JSON response from {url}"
            continue

        if isinstance(parsed, dict):
            payload = parsed
            break

    if payload is None:
        raise HTTPException(status_code=503, detail=last_error or "Unable to load LM Studio models")

    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raw_models = []

    models: List[Dict[str, Any]] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id or not isinstance(model_id, str):
            continue
        models.append(
            {
                "id": model_id,
                "context_length": _extract_lmstudio_context_length(entry),
            }
        )

    return {
        "base_url": base_url,
        "models": models,
    }


class RetryApiErrorsResponse(BaseModel):
    retry_run_id: str
    original_run_id: str
    api_errors_found: int
    message: str


class ApiErrorsInfoResponse(BaseModel):
    run_id: str
    api_error_count: int
    api_errors: List[Dict[str, Any]]


class RetrySingleAttemptRequest(BaseModel):
    task_id: str
    model: Optional[str] = None
    sample_index: Optional[int] = None


@router.get("/runs/{run_id}/api-errors", response_model=ApiErrorsInfoResponse, tags=["runs"])
def get_api_errors(run_id: str) -> ApiErrorsInfoResponse:
    """Get information about api_error attempts in a run."""
    summary = database.get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = Path(settings.runs_root) / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run directory not found")

    try:
        api_errors = load_api_error_attempts(run_dir)
    except (OSError, json.JSONDecodeError, HarnessError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load api errors: {exc}")

    return ApiErrorsInfoResponse(
        run_id=run_id,
        api_error_count=len(api_errors),
        api_errors=[
            {
                "task_id": e.get("task_id"),
                "model": e.get("model"),
                "sample_index": e.get("sample_index"),
                "thinking_level": e.get("thinking_level_requested"),
                "error": e.get("error", "")[:200],  # Truncate error message
            }
            for e in api_errors
        ],
    )


@router.post("/runs/{run_id}/retry-api-errors", response_model=RetryApiErrorsResponse, tags=["runs"])
async def retry_api_errors(run_id: str, _: None = Depends(require_api_token)) -> RetryApiErrorsResponse:
    """Retry only the api_error attempts from a previous run."""
    summary = database.get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = Path(settings.runs_root) / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run directory not found")

    try:
        api_errors = load_api_error_attempts(run_dir)
    except (OSError, json.JSONDecodeError, HarnessError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load api errors: {exc}")

    if not api_errors:
        return RetryApiErrorsResponse(
            retry_run_id="",
            original_run_id=run_id,
            api_errors_found=0,
            message="No api_error attempts found to retry",
        )

    # Generate new run ID for retry
    retry_run_id = progress_manager.generate_run_id()
    await progress_manager.start_run(
        retry_run_id,
        {
            "original_run_id": run_id,
            "retry_mode": True,
            "api_errors_to_retry": len(api_errors),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
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
            "error": summary.get("error"),
        }
        progress_manager.publish_attempt(retry_run_id, payload)

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("retry.failed", run_id=retry_run_id, error=str(exc))
            progress_manager.fail(retry_run_id, str(exc))

        def on_success(result: Dict[str, Any]) -> None:
            database.save_run(result)
            progress_manager.complete(retry_run_id, result)

        await run_in_thread_with_callbacks(
            retry_api_error_attempts,
            original_run_dir=run_dir,
            output_dir=output_dir,
            progress_callback=progress_proxy,
            run_id=retry_run_id,
            on_success=on_success,
            on_error=on_error,
        )

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return RetryApiErrorsResponse(
        retry_run_id=retry_run_id,
        original_run_id=run_id,
        api_errors_found=len(api_errors),
        message=f"Retrying {len(api_errors)} api_error attempts",
    )


@router.post("/runs/{run_id}/retry-single", response_model=RetryApiErrorsResponse, tags=["runs"])
async def retry_single_attempt(
    run_id: str,
    request: RetrySingleAttemptRequest,
    _: None = Depends(require_api_token),
) -> RetryApiErrorsResponse:
    """Retry a single failed attempt from a previous run."""
    summary = database.get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = Path(settings.runs_root) / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run directory not found")

    try:
        all_failed = load_failed_attempts(run_dir)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load failed attempts: {exc}")

    # Filter to find the specific attempt
    filtered = [
        e
        for e in all_failed
        if e.get("task_id") == request.task_id
        and (request.model is None or e.get("model") == request.model)
        and (request.sample_index is None or e.get("sample_index") == request.sample_index)
    ]

    if not filtered:
        raise HTTPException(status_code=404, detail="Specified attempt not found or not a failed attempt")

    retry_run_id = progress_manager.generate_run_id()
    await progress_manager.start_run(
        retry_run_id,
        {
            "original_run_id": run_id,
            "retry_mode": True,
            "single_retry": True,
            "task_id": request.task_id,
            "api_errors_to_retry": len(filtered),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
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
            "error": summary.get("error"),
        }
        progress_manager.publish_attempt(retry_run_id, payload)

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("retry.single.failed", run_id=retry_run_id, error=str(exc))
            progress_manager.fail(retry_run_id, str(exc))

        def on_success(result: Dict[str, Any]) -> None:
            database.save_run(result)
            progress_manager.complete(retry_run_id, result)

        await run_in_thread_with_callbacks(
            retry_failed_attempts,
            original_run_dir=run_dir,
            output_dir=output_dir,
            progress_callback=progress_proxy,
            filter_task_id=request.task_id,
            filter_model=request.model,
            filter_sample_index=request.sample_index,
            run_id=retry_run_id,
            on_success=on_success,
            on_error=on_error,
        )

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return RetryApiErrorsResponse(
        retry_run_id=retry_run_id,
        original_run_id=run_id,
        api_errors_found=len(filtered),
        message=f"Retrying {len(filtered)} failed attempt(s) for task {request.task_id}",
    )


class IncompleteAttemptsResponse(BaseModel):
    run_id: str
    incomplete_count: int
    incomplete_attempts: List[Dict[str, Any]]


class ResumeIncompleteResponse(BaseModel):
    run_id: str
    incomplete_count: int
    message: str


@router.get("/runs/{run_id}/incomplete", response_model=IncompleteAttemptsResponse)
async def get_incomplete_attempts(run_id: str) -> IncompleteAttemptsResponse:
    """Get incomplete attempts for a run (started but didn't finish)."""
    run_dir = Path(settings.runs_root) / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run directory not found")

    try:
        incomplete = load_incomplete_attempts(run_dir)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load incomplete attempts: {exc}")

    return IncompleteAttemptsResponse(
        run_id=run_id,
        incomplete_count=len(incomplete),
        incomplete_attempts=incomplete,
    )


@router.post("/runs/{run_id}/resume", response_model=ResumeIncompleteResponse)
async def resume_run(run_id: str, _: None = Depends(require_api_token)) -> ResumeIncompleteResponse:
    """Resume incomplete attempts for a run."""
    run_dir = Path(settings.runs_root) / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run directory not found")

    try:
        incomplete = load_incomplete_attempts(run_dir)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load incomplete attempts: {exc}")

    if not incomplete:
        raise HTTPException(status_code=400, detail="No incomplete attempts to resume")

    # Start resume in progress manager
    await progress_manager.start_run(
        run_id,
        {
            "resume_mode": True,
            "incomplete_to_resume": len(incomplete),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    )

    def progress_proxy(model: str, task_id: str, sample_index: int, summary: Dict[str, Any]) -> None:
        progress_manager.publish_attempt(
            run_id,
            {
                "task_id": task_id,
                "model": model,
                "sample_index": sample_index,
                "status": summary.get("status"),
                "duration_seconds": summary.get("duration_seconds"),
                "error": summary.get("error"),
            },
        )

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("resume.failed", run_id=run_id, error=str(exc))
            progress_manager.fail(run_id, str(exc))

        def on_success(result: Dict[str, Any]) -> None:
            database.save_run(result)
            progress_manager.complete(run_id, result)

        await run_in_thread_with_callbacks(
            resume_incomplete_run,
            run_dir=run_dir,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            include_tests=HARNESS_SETTINGS.include_tests_by_default,
            install_deps=HARNESS_SETTINGS.install_deps_by_default,
            allow_incomplete_diffs=DEFAULT_ALLOW_INCOMPLETE_DIFFS,
            allow_diff_rewrite_fallback=DEFAULT_ALLOW_DIFF_REWRITE_FALLBACK,
            progress_callback=progress_proxy,
            on_success=on_success,
            on_error=on_error,
        )

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return ResumeIncompleteResponse(
        run_id=run_id,
        incomplete_count=len(incomplete),
        message=f"Resuming {len(incomplete)} incomplete attempt(s)",
    )


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
IncompleteAttemptsResponse.model_rebuild()
ResumeIncompleteResponse.model_rebuild()
