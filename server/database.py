from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column, relationship, sessionmaker

from server.config import get_settings
from server.database_utils import count_errors_from_summary, extract_usage_tokens, parse_timestamp


ROOT = Path(__file__).resolve().parents[1]
Base = declarative_base()


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    tasks: Mapped[str] = mapped_column(Text, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[Optional[float]] = mapped_column(Float)
    total_cost: Mapped[Optional[float]] = mapped_column(Float)
    total_duration: Mapped[Optional[float]] = mapped_column(Float)
    summary_path: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)

    attempts: Mapped[List["AttemptRecord"]] = relationship(
        "AttemptRecord",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class AttemptRecord(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost: Mapped[Optional[float]] = mapped_column(Float)
    error: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped[RunRecord] = relationship("RunRecord", back_populates="attempts")


settings = get_settings()

engine = create_engine(
    settings.database.url,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    echo=settings.database.echo,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    ROOT.joinpath("runs").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Iterator[Session]:
    with SessionLocal.begin() as session:
        yield session


def save_run(summary: Dict) -> str:
    run_dir = Path(summary["run_dir"]).resolve()
    run_id = run_dir.name
    attempts = summary.get("attempts", [])
    accuracy = summary.get("metrics", {}).get("overall", {}).get("macro_model_accuracy")
    total_cost = summary.get("token_usage", {}).get("total_cost_usd")
    total_duration = summary.get("timing", {}).get("total_duration_seconds")
    timestamp = parse_timestamp(summary.get("timestamp_utc"))

    with get_session() as session:
        record = session.get(RunRecord, run_id)
        if record is None:
            record = RunRecord(id=run_id)
        record.timestamp_utc = timestamp
        record.model_id = ",".join(summary.get("models", []))
        record.tasks = json.dumps(summary.get("tasks", []))
        record.samples = summary.get("samples", 1)
        record.accuracy = accuracy
        record.total_cost = total_cost
        record.total_duration = total_duration
        record.summary_path = str(run_dir / "summary.json")
        record.summary_json = json.dumps(summary)
        record.attempts.clear()
        for attempt in attempts:
            prompt_tokens, completion_tokens = extract_usage_tokens(attempt.get("usage"))
            record.attempts.append(
                AttemptRecord(
                    task_id=attempt.get("task_id"),
                    status=attempt.get("status"),
                    duration=attempt.get("duration_seconds"),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost=attempt.get("cost_usd"),
                    error=attempt.get("error"),
                )
            )
        session.add(record)
    return run_id


def list_runs(limit: int = 50) -> List[Dict[str, Optional[float]]]:
    stmt = (
        select(
            RunRecord.id,
            RunRecord.timestamp_utc,
            RunRecord.model_id,
            RunRecord.accuracy,
            RunRecord.total_cost,
            RunRecord.total_duration,
            RunRecord.summary_json,
        )
        .order_by(RunRecord.timestamp_utc.desc())
        .limit(limit)
    )
    with get_session() as session:
        rows = session.execute(stmt).all()

    results = []
    for row in rows:
        results.append(
            {
                "id": row.id,
                "timestamp_utc": row.timestamp_utc.isoformat() if row.timestamp_utc else None,
                "model_id": row.model_id,
                "accuracy": row.accuracy,
                "total_cost": row.total_cost,
                "total_duration": row.total_duration,
                "error_count": count_errors_from_summary(row.summary_json),
            }
        )
    return results


def get_run(run_id: str) -> Dict | None:
    with get_session() as session:
        record = session.get(RunRecord, run_id)
        if record is None:
            return None
        return json.loads(record.summary_json)


def _determine_model_level(attempts: List[Dict[str, Any]], default_level: Optional[str]) -> str:
    for attempt in attempts:
        applied = attempt.get("thinking_level_applied")
        if applied:
            return applied
    for attempt in attempts:
        if attempt.get("thinking_level_supported") is False and attempt.get("thinking_level_requested"):
            requested = attempt.get("thinking_level_requested")
            if requested:
                return f"unsupported ({requested})"
    if default_level:
        return default_level
    return "base"


def leaderboard() -> List[Dict[str, Optional[float]]]:
    stmt = select(
        RunRecord.id,
        RunRecord.summary_json,
        RunRecord.timestamp_utc,
    )
    with get_session() as session:
        rows = session.execute(stmt).all()

    def _is_better(candidate: Dict[str, Any], incumbent: Optional[Dict[str, Any]]) -> bool:
        if incumbent is None:
            return True
        cand_acc = candidate.get("accuracy")
        inc_acc = incumbent.get("accuracy")
        if cand_acc is None and inc_acc is not None:
            return False
        if cand_acc is not None and inc_acc is None:
            return True
        if cand_acc is not None and inc_acc is not None:
            if cand_acc > inc_acc:
                return True
            if cand_acc < inc_acc:
                return False
        cand_cost = candidate.get("cost")
        inc_cost = incumbent.get("cost")
        if cand_cost is None and inc_cost is not None:
            return False
        if cand_cost is not None and inc_cost is None:
            return True
        if cand_cost is not None and inc_cost is not None:
            if cand_cost < inc_cost:
                return True
            if cand_cost > inc_cost:
                return False
        cand_duration = candidate.get("duration")
        inc_duration = incumbent.get("duration")
        if cand_duration is None and inc_duration is not None:
            return False
        if cand_duration is not None and inc_duration is None:
            return True
        if cand_duration is not None and inc_duration is not None:
            if cand_duration < inc_duration:
                return True
            if cand_duration > inc_duration:
                return False
        return (candidate.get("timestamp") or dt.datetime.min) > (incumbent.get("timestamp") or dt.datetime.min)

    groups: Dict[tuple[str, str], Dict[str, Any]] = {}

    for row in rows:
        try:
            summary = json.loads(row.summary_json)
        except json.JSONDecodeError:
            continue

        attempts = summary.get("attempts") or []
        if not attempts:
            continue
        default_level = summary.get("thinking_level")
        # Group attempts per (model, thinking level)
        per_model_level: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        for attempt in attempts:
            model_id = attempt.get("model")
            if not model_id:
                continue
            level = _determine_model_level([attempt], default_level)
            per_model_level.setdefault((model_id, level), []).append(attempt)

        for (model_id, level), model_attempts in per_model_level.items():
            cost_values = [a.get("cost_usd") for a in model_attempts if a.get("cost_usd") is not None]
            duration_values = [
                a.get("duration_seconds") for a in model_attempts if a.get("duration_seconds") is not None
            ]
            # Compute accuracy for this (model, level) subset
            successes = sum(1 for a in model_attempts if (a.get("status") or "").lower() == "passed")
            accuracy = successes / len(model_attempts) if model_attempts else None
            candidate = {
                "model_id": model_id,
                "thinking_level": level,
                "accuracy": accuracy,
                "cost": sum(cost_values) if cost_values else None,
                "duration": sum(duration_values) if duration_values else None,
                "runs": 1,
                "timestamp": row.timestamp_utc,
            }
            key = (model_id, level)
            group = groups.setdefault(key, {"runs": 0, "best": None})
            group["runs"] += 1
            if _is_better(candidate, group["best"]):
                group["best"] = candidate

    leaderboard_rows = []
    for (model_id, level), info in groups.items():
        best = info.get("best") or {}
        leaderboard_rows.append(
            {
                "model_id": model_id,
                "thinking_level": level,
                "best_accuracy": best.get("accuracy"),
                "cost_at_best": best.get("cost"),
                "duration_at_best": best.get("duration"),
                "runs": info.get("runs", 0),
            }
        )

    leaderboard_rows.sort(
        key=lambda row: (
            0 if row.get("best_accuracy") is None else -row["best_accuracy"],
            row.get("cost_at_best") if row.get("cost_at_best") is not None else float("inf"),
            row.get("duration_at_best") if row.get("duration_at_best") is not None else float("inf"),
            row["model_id"],
            row.get("thinking_level") or "",
        )
    )
    return leaderboard_rows


def delete_runs_for_model(model_id: str, thinking_level: Optional[str] = None) -> int:
    like_pattern = f"%{model_id}%"
    with get_session() as session:
        candidates = session.scalars(select(RunRecord).where(RunRecord.model_id.like(like_pattern))).all()
        removed = 0
        for record in candidates:
            models = [m.strip() for m in (record.model_id or "").split(",") if m.strip()]
            if model_id not in models:
                continue
            if thinking_level:
                try:
                    summary = json.loads(record.summary_json)
                except json.JSONDecodeError:
                    continue
                attempts = summary.get("attempts") or []
                default_level = summary.get("thinking_level")
                per_model_attempts = [a for a in attempts if a.get("model") == model_id]
                if not per_model_attempts:
                    continue
                level = _determine_model_level(per_model_attempts, default_level)
                if level != thinking_level:
                    continue
            session.delete(record)
            removed += 1
        return removed
