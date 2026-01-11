"""API endpoints for the expert question benchmark."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, PositiveInt, field_validator

from harness.expert_questions import (
    load_questions,
    run_question_benchmark,
    load_qa_api_error_attempts,
    retry_qa_api_error_attempts,
    load_qa_failed_attempts,
    retry_qa_failed_attempts,
)
from server.config import get_settings
from server.qa_database import (
    delete_runs_for_model,
    get_run,
    leaderboard,
    list_runs,
    save_run,
)
from server.qa_progress import qa_progress_manager
from server.routes.background import run_in_thread_with_callbacks
from server.routes.auth import require_api_token

logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/qa", tags=["qa"])
_background_tasks: set = set()


class QARunLaunchResponse(BaseModel):
    run_id: str


class QARunListEntry(BaseModel):
    run_id: str
    timestamp_utc: str | None
    model_id: str | None
    accuracy: float | None
    total_cost_usd: float | None
    total_duration_seconds: float | None


class QARunListResponse(BaseModel):
    runs: list[QARunListEntry]


class QARunDetailResponse(BaseModel):
    summary: dict[str, Any]


class QARunRequest(BaseModel):
    models: list[str]
    samples: PositiveInt = 1
    temperature: float = 0.5
    max_tokens: int = 200000
    provider: str | None = None
    thinking_level: str | None = None
    include_thinking_variants: bool = False
    sweep_thinking_levels: bool = False

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: list[str]) -> list[str]:
        trimmed = [item.strip() for item in value if item.strip()]
        if not trimmed:
            raise ValueError("At least one model identifier is required.")
        return trimmed

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_tokens must be positive")
        return value

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, provider: str | None) -> str | None:
        if provider is None:
            return None
        trimmed = provider.strip()
        if not trimmed:
            return None
        if not re.fullmatch(r"[A-Za-z0-9._\-/]+", trimmed):
            raise ValueError(
                "provider must be alphanumeric with optional hyphen/underscore characters (dots and slashes allowed)"
            )
        return trimmed

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, level: str | None) -> str | None:
        if level is None:
            return None
        trimmed = level.strip()
        return trimmed or None


@router.get("/runs", response_model=QARunListResponse)
async def qa_runs_list(limit: int = 50) -> QARunListResponse:
    rows = list_runs(limit)
    payload = [
        QARunListEntry(
            run_id=row["id"],
            timestamp_utc=row["timestamp_utc"],
            model_id=row["model_id"],
            accuracy=row["accuracy"],
            total_cost_usd=row["total_cost"],
            total_duration_seconds=row["total_duration"],
        )
        for row in rows
    ]
    return QARunListResponse(runs=payload)


@router.get("/runs/{run_id}", response_model=QARunDetailResponse)
async def qa_run_detail(run_id: str) -> QARunDetailResponse:
    summary = get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return QARunDetailResponse(summary=summary)


@router.get("/leaderboard")
async def qa_leaderboard() -> dict[str, Any]:
    rows = leaderboard()
    return {"models": rows}


@router.delete("/leaderboard/{model_id:path}")
async def qa_leaderboard_delete(model_id: str, _: None = Depends(require_api_token)) -> dict[str, Any]:
    removed = delete_runs_for_model(model_id)
    status = "removed" if removed else "already_missing"
    if removed:
        logger.info("qa.leaderboard_cleared", model_id=model_id, removed_runs=removed)
    return {"model_id": model_id, "removed_runs": removed, "status": status}


@router.post("/runs", response_model=QARunLaunchResponse)
async def qa_run_create(request: QARunRequest, _: None = Depends(require_api_token)) -> QARunLaunchResponse:
    models = request.models
    samples = request.samples
    temperature = request.temperature
    max_tokens = request.max_tokens
    provider = request.provider
    thinking_level = request.thinking_level
    include_thinking_variants = request.include_thinking_variants

    questions = load_questions()
    if not questions:
        raise HTTPException(status_code=500, detail="Question set could not be loaded.")

    run_id = qa_progress_manager.generate_run_id()
    await qa_progress_manager.start_run(
        run_id,
        {
            "models": models,
            "samples": samples,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "provider": provider,
            "question_count": len(questions),
            "thinking_level": thinking_level,
            "include_thinking_variants": include_thinking_variants,
            "sweep_thinking_levels": request.sweep_thinking_levels,
        },
    )

    def progress_proxy(model: str, question_number: int, sample_index: int, attempt: dict[str, Any]) -> None:
        usage = attempt.get("usage") or {}
        qa_progress_manager.publish_attempt(
            run_id,
            {
                "model": model,
                "question_number": question_number,
                "sample_index": sample_index,
                "status": attempt.get("status"),
                "model_answer": attempt.get("model_answer"),
                "expected_answer": attempt.get("expected_answer"),
                "normalized_answer": attempt.get("normalized_answer"),
                "normalized_expected": attempt.get("normalized_expected"),
                "duration_seconds": attempt.get("duration_seconds"),
                "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
                "completion_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
                "cost_usd": attempt.get("cost_usd"),
                "judge_decision": attempt.get("judge_decision"),
                "judge_rationale": attempt.get("judge_rationale"),
                "judge_cost_usd": attempt.get("judge_cost_usd"),
                "judge_error": attempt.get("judge_error"),
                "error": attempt.get("error"),
                "provider": provider,
                "thinking_level_applied": attempt.get("thinking_level_applied"),
                "thinking_level_requested": attempt.get("thinking_level_requested"),
            },
        )

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("qa.run_failed", run_id=run_id, error=str(exc))
            qa_progress_manager.fail(run_id, str(exc))

        def on_success(summary: dict[str, Any]) -> None:
            save_run(summary)
            qa_progress_manager.complete(run_id, summary)

        await run_in_thread_with_callbacks(
            run_question_benchmark,
            models=models,
            samples=samples,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider,
            thinking_level=thinking_level,
            include_thinking_variants=include_thinking_variants,
            sweep_thinking_levels=request.sweep_thinking_levels,
            run_id=run_id,
            progress_callback=progress_proxy,
            on_success=on_success,
            on_error=on_error,
        )

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return QARunLaunchResponse(run_id=run_id)


class QARetryApiErrorsResponse(BaseModel):
    retry_run_id: str
    original_run_id: str
    api_errors_found: int
    message: str


class QAApiErrorsInfoResponse(BaseModel):
    run_id: str
    api_error_count: int
    api_errors: list[dict[str, Any]]


class QARetrySingleAttemptRequest(BaseModel):
    question_number: int
    model: str | None = None
    sample_index: int | None = None


@router.get("/runs/{run_id}/api-errors", response_model=QAApiErrorsInfoResponse)
async def qa_get_api_errors(run_id: str) -> QAApiErrorsInfoResponse:
    """Get information about api_error attempts in a QA run."""
    summary = get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="QA Run not found")

    run_dir = Path(settings.runs_root) / "qa_runs" / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="QA Run directory not found")

    try:
        api_errors = load_qa_api_error_attempts(run_dir)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load api errors: {exc}")

    return QAApiErrorsInfoResponse(
        run_id=run_id,
        api_error_count=len(api_errors),
        api_errors=[
            {
                "question_number": e.get("question_number"),
                "model": e.get("model"),
                "sample_index": e.get("sample_index"),
                "thinking_level": e.get("thinking_level_requested"),
                "error": e.get("error", "")[:200],
            }
            for e in api_errors
        ],
    )


@router.post("/runs/{run_id}/retry-api-errors", response_model=QARetryApiErrorsResponse)
async def qa_retry_api_errors(run_id: str, _: None = Depends(require_api_token)) -> QARetryApiErrorsResponse:
    """Retry only the api_error attempts from a previous QA run."""
    summary = get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="QA Run not found")

    run_dir = Path(settings.runs_root) / "qa_runs" / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="QA Run directory not found")

    try:
        api_errors = load_qa_api_error_attempts(run_dir)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load api errors: {exc}")

    if not api_errors:
        return QARetryApiErrorsResponse(
            retry_run_id="",
            original_run_id=run_id,
            api_errors_found=0,
            message="No api_error attempts found to retry",
        )

    retry_run_id = qa_progress_manager.generate_run_id()
    await qa_progress_manager.start_run(
        retry_run_id,
        {
            "original_run_id": run_id,
            "retry_mode": True,
            "api_errors_to_retry": len(api_errors),
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        },
    )

    output_dir = Path(settings.runs_root)

    def progress_proxy(model: str, question_number: int, sample_index: int, attempt: dict[str, Any]) -> None:
        qa_progress_manager.publish_attempt(
            retry_run_id,
            {
                "model": model,
                "question_number": question_number,
                "sample_index": sample_index,
                "status": attempt.get("status"),
                "duration_seconds": attempt.get("duration_seconds"),
                "error": attempt.get("error"),
            },
        )

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("qa.retry.failed", run_id=retry_run_id, error=str(exc))
            qa_progress_manager.fail(retry_run_id, str(exc))

        def on_success(result: dict[str, Any]) -> None:
            save_run(result)
            qa_progress_manager.complete(retry_run_id, result)

        await run_in_thread_with_callbacks(
            retry_qa_api_error_attempts,
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

    return QARetryApiErrorsResponse(
        retry_run_id=retry_run_id,
        original_run_id=run_id,
        api_errors_found=len(api_errors),
        message=f"Retrying {len(api_errors)} api_error attempts",
    )


@router.post("/runs/{run_id}/retry-single", response_model=QARetryApiErrorsResponse)
async def qa_retry_single_attempt(
    run_id: str,
    request: QARetrySingleAttemptRequest,
    _: None = Depends(require_api_token),
) -> QARetryApiErrorsResponse:
    """Retry a single failed attempt from a previous QA run."""
    summary = get_run(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="QA Run not found")

    run_dir = Path(settings.runs_root) / "qa_runs" / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="QA Run directory not found")

    try:
        all_failed = load_qa_failed_attempts(run_dir)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load failed attempts: {exc}")

    # Filter to find the specific attempt
    filtered = [
        e
        for e in all_failed
        if e.get("question_number") == request.question_number
        and (request.model is None or e.get("model") == request.model)
        and (request.sample_index is None or e.get("sample_index") == request.sample_index)
    ]

    if not filtered:
        raise HTTPException(status_code=404, detail="Specified attempt not found or not a failed attempt")

    retry_run_id = qa_progress_manager.generate_run_id()
    await qa_progress_manager.start_run(
        retry_run_id,
        {
            "original_run_id": run_id,
            "retry_mode": True,
            "single_retry": True,
            "question_number": request.question_number,
            "api_errors_to_retry": len(filtered),
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        },
    )

    output_dir = Path(settings.runs_root)

    def progress_proxy(model: str, question_number: int, sample_index: int, attempt: dict[str, Any]) -> None:
        qa_progress_manager.publish_attempt(
            retry_run_id,
            {
                "model": model,
                "question_number": question_number,
                "sample_index": sample_index,
                "status": attempt.get("status"),
                "duration_seconds": attempt.get("duration_seconds"),
                "error": attempt.get("error"),
            },
        )

    async def runner() -> None:
        def on_error(exc: Exception) -> None:
            logger.exception("qa.retry.single.failed", run_id=retry_run_id, error=str(exc))
            qa_progress_manager.fail(retry_run_id, str(exc))

        def on_success(result: dict[str, Any]) -> None:
            save_run(result)
            qa_progress_manager.complete(retry_run_id, result)

        await run_in_thread_with_callbacks(
            retry_qa_failed_attempts,
            original_run_dir=run_dir,
            output_dir=output_dir,
            progress_callback=progress_proxy,
            filter_question_number=request.question_number,
            filter_model=request.model,
            filter_sample_index=request.sample_index,
            on_success=on_success,
            on_error=on_error,
        )

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return QARetryApiErrorsResponse(
        retry_run_id=retry_run_id,
        original_run_id=run_id,
        api_errors_found=len(filtered),
        message=f"Retrying {len(filtered)} failed attempt(s) for question {request.question_number}",
    )


@router.websocket("/runs/{run_id}/stream")
async def qa_run_stream(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    try:
        queue = await qa_progress_manager.subscribe(run_id)
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
        await qa_progress_manager.unsubscribe(run_id, queue)


__all__ = [
    "router",
    "QARunRequest",
    "QARunLaunchResponse",
    "QARunListResponse",
    "QARunDetailResponse",
]


QARunRequest.model_rebuild()
QARunLaunchResponse.model_rebuild()
QARunListEntry.model_rebuild()
QARunListResponse.model_rebuild()
QARunDetailResponse.model_rebuild()
