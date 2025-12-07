"""API endpoints for the expert question benchmark."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, PositiveInt, field_validator

from harness.expert_questions import load_questions, run_question_benchmark
from server.qa_database import (
    delete_runs_for_model,
    get_run,
    init_db as init_qa_db,
    leaderboard,
    list_runs,
    save_run,
)
from server.qa_progress import qa_progress_manager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/qa", tags=["qa"])
_background_tasks: set = set()


class QARunLaunchResponse(BaseModel):
    run_id: str


class QARunListEntry(BaseModel):
    run_id: str
    timestamp_utc: Optional[str]
    model_id: Optional[str]
    accuracy: Optional[float]
    total_cost_usd: Optional[float]
    total_duration_seconds: Optional[float]


class QARunListResponse(BaseModel):
    runs: List[QARunListEntry]


class QARunDetailResponse(BaseModel):
    summary: Dict[str, Any]


class QARunRequest(BaseModel):
    models: List[str]
    samples: PositiveInt = 1
    temperature: float = 0.5
    max_tokens: int = 200000
    provider: Optional[str] = None
    thinking_level: Optional[str] = None
    include_thinking_variants: bool = False
    sweep_thinking_levels: bool = False

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: List[str]) -> List[str]:
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
    def validate_provider(cls, provider: Optional[str]) -> Optional[str]:
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
    def validate_thinking_level(cls, level: Optional[str]) -> Optional[str]:
        if level is None:
            return None
        trimmed = level.strip()
        return trimmed or None


@router.on_event("startup")
async def startup_event() -> None:  # pragma: no cover - called by FastAPI
    init_qa_db()


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
async def qa_leaderboard() -> Dict[str, Any]:
    rows = leaderboard()
    return {"models": rows}


@router.delete("/leaderboard/{model_id:path}")
async def qa_leaderboard_delete(model_id: str) -> Dict[str, Any]:
    removed = delete_runs_for_model(model_id)
    status = "removed" if removed else "already_missing"
    if removed:
        logger.info("qa.leaderboard_cleared", model_id=model_id, removed_runs=removed)
    return {"model_id": model_id, "removed_runs": removed, "status": status}


@router.post("/runs", response_model=QARunLaunchResponse)
async def qa_run_create(request: QARunRequest) -> QARunLaunchResponse:
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

    def progress_proxy(model: str, question_number: int, sample_index: int, attempt: Dict[str, Any]) -> None:
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
        try:
            summary = await asyncio.to_thread(
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
            )
        except Exception as exc:  # pragma: no cover - background failure
            logger.exception("qa.run_failed", run_id=run_id, error=str(exc))
            qa_progress_manager.fail(run_id, str(exc))
        else:
            save_run(summary)
            qa_progress_manager.complete(run_id, summary)

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return QARunLaunchResponse(run_id=run_id)


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
