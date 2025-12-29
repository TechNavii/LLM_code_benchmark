"""Persist expert question benchmark runs in a dedicated SQLite database."""

from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column, relationship, sessionmaker

from server.config import get_settings

ROOT = Path(__file__).resolve().parents[1]

Base = declarative_base()


class QARunRecord(Base):
    __tablename__ = "qa_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    questions: Mapped[str] = mapped_column(Text, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[Optional[float]] = mapped_column(Float)
    total_cost: Mapped[Optional[float]] = mapped_column(Float)
    total_duration: Mapped[Optional[float]] = mapped_column(Float)
    summary_path: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)

    attempts: Mapped[List["QAAttemptRecord"]] = relationship(
        "QAAttemptRecord",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class QAAttemptRecord(Base):
    __tablename__ = "qa_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost: Mapped[Optional[float]] = mapped_column(Float)
    model_answer: Mapped[Optional[str]] = mapped_column(Text)
    expected_answer: Mapped[Optional[str]] = mapped_column(Text)
    normalized_answer: Mapped[Optional[str]] = mapped_column(Text)
    normalized_expected: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped[QARunRecord] = relationship("QARunRecord", back_populates="attempts")


settings = get_settings()
DB_PATH = ROOT / "runs" / "qa_history.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=settings.database.echo,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_run(summary: Dict[str, Any]) -> str:
    run_dir = Path(summary["run_dir"]).resolve()
    run_id = summary.get("run_id") or run_dir.name

    models = summary.get("models", [])
    attempts = summary.get("attempts", [])
    metrics = summary.get("metrics", {})
    overall = metrics.get("overall", {})

    accuracy = overall.get("accuracy")
    total_cost = summary.get("token_usage", {}).get("total_cost_usd")
    total_duration = summary.get("timing", {}).get("total_duration_seconds")
    timestamp_raw = summary.get("timestamp_utc")
    try:
        timestamp = dt.datetime.fromisoformat(timestamp_raw) if timestamp_raw else dt.datetime.utcnow()
    except ValueError:
        timestamp = dt.datetime.utcnow()

    with get_session() as session:
        record = session.get(QARunRecord, run_id)
        if record is None:
            record = QARunRecord(id=run_id)
        record.timestamp_utc = timestamp
        record.model_id = ",".join(models)
        record.questions = json.dumps(summary.get("questions", []))
        record.samples = summary.get("samples", 1)
        record.accuracy = accuracy
        record.total_cost = total_cost
        record.total_duration = total_duration
        record.summary_path = str(run_dir / "summary.json")
        record.summary_json = json.dumps(summary)
        record.attempts.clear()
        for attempt in attempts:
            usage = attempt.get("usage") or {}
            record.attempts.append(
                QAAttemptRecord(
                    model=attempt.get("model"),
                    sample_index=attempt.get("sample_index", 0),
                    question_number=attempt.get("question_number"),
                    status=attempt.get("status"),
                    duration=attempt.get("duration_seconds"),
                    prompt_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                    completion_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                    cost=attempt.get("cost_usd"),
                    model_answer=attempt.get("model_answer"),
                    expected_answer=attempt.get("expected_answer"),
                    normalized_answer=attempt.get("normalized_answer"),
                    normalized_expected=attempt.get("normalized_expected"),
                    error=attempt.get("error"),
                )
            )
        session.add(record)
    return run_id


def list_runs(limit: int = 50) -> List[Dict[str, Optional[float]]]:
    stmt = (
        select(
            QARunRecord.id,
            QARunRecord.timestamp_utc,
            QARunRecord.model_id,
            QARunRecord.accuracy,
            QARunRecord.total_cost,
            QARunRecord.total_duration,
            QARunRecord.summary_json,
        )
        .order_by(QARunRecord.timestamp_utc.desc())
        .limit(limit)
    )
    with get_session() as session:
        rows = session.execute(stmt).all()
    
    results = []
    for row in rows:
        # Count errors from summary
        error_count = 0
        try:
            summary = json.loads(row.summary_json) if row.summary_json else {}
            attempts = summary.get("attempts", [])
            failed_statuses = {"error", "fail", "failed", "api_error", "exception"}
            error_count = sum(1 for a in attempts if a.get("status", "").lower() in failed_statuses)
        except (json.JSONDecodeError, TypeError):
            pass
        
        results.append({
            "id": row.id,
            "timestamp_utc": row.timestamp_utc.isoformat() if row.timestamp_utc else None,
            "model_id": row.model_id,
            "accuracy": row.accuracy,
            "total_cost": row.total_cost,
            "total_duration": row.total_duration,
            "error_count": error_count,
        })
    return results


def get_run(run_id: str) -> Dict[str, Any] | None:
    with get_session() as session:
        record = session.get(QARunRecord, run_id)
        if record is None:
            return None
        return json.loads(record.summary_json)


def leaderboard(limit_runs: int = 200) -> List[Dict[str, Any]]:
    with get_session() as session:
        records: List[QARunRecord] = (
            session.execute(
                select(QARunRecord).order_by(QARunRecord.timestamp_utc.desc()).limit(limit_runs)
            )
            .scalars()
            .all()
        )

    # Determine thinking level similar to code harness grouping
    def _determine_level(attempts: List[Dict[str, Any]], default_level: Optional[str]) -> str:
        for a in attempts:
            level = a.get("thinking_level_applied")
            if level:
                return str(level)
        for a in attempts:
            if a.get("thinking_level_supported") is False and a.get("thinking_level_requested"):
                req = a.get("thinking_level_requested")
                if req:
                    return f"unsupported ({req})"
        if default_level:
            return default_level
        return "base"

    groups: Dict[tuple[str, str], Dict[str, Any]] = {}
    counts: Dict[tuple[str, str], int] = {}

    for record in records:
        try:
            summary = json.loads(record.summary_json)
        except json.JSONDecodeError:
            continue
        attempts = summary.get("attempts") or []
        default_level = summary.get("thinking_level")
        # Group attempts by (model, determined level)
        per_key: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        for a in attempts:
            model = a.get("model")
            if not model:
                continue
            level = _determine_level([a], default_level)
            per_key.setdefault((model, level), []).append(a)

        # Build candidates per group
        for key, group_attempts in per_key.items():
            model_id, level = key
            successes = sum(1 for a in group_attempts if (a.get("status") or "").lower() == "passed")
            total = len(group_attempts)
            accuracy = successes / total if total else None
            cost_values = [a.get("cost_usd") for a in group_attempts if a.get("cost_usd") is not None]
            duration_values = [a.get("duration_seconds") for a in group_attempts if a.get("duration_seconds") is not None]

            candidate = {
                "model_id": model_id,
                "thinking_level": level,
                "accuracy": accuracy,
                "cost_usd": sum(cost_values) if cost_values else None,
                "duration_seconds": sum(duration_values) if duration_values else None,
                "runs": 1,
            }
            counts[key] = counts.get(key, 0) + 1
            incumbent = groups.get(key)
            # Prefer higher accuracy; tie-break on lower cost, then lower duration
            def _better(a, b):
                if b is None:
                    return True
                ax, bx = a.get("accuracy"), b.get("accuracy")
                if ax is not None and bx is not None:
                    if ax != bx:
                        return ax > bx
                elif ax is not None or bx is not None:
                    return ax is not None
                ac, bc = a.get("cost_usd"), b.get("cost_usd")
                if ac is not None and bc is not None:
                    if ac != bc:
                        return ac < bc
                elif ac is not None or bc is not None:
                    return ac is not None
                ad, bd = a.get("duration_seconds"), b.get("duration_seconds")
                if ad is not None and bd is not None:
                    if ad != bd:
                        return ad < bd
                elif ad is not None or bd is not None:
                    return ad is not None
                return True

            if _better(candidate, incumbent):
                groups[key] = candidate

    # Compile leaderboard rows
    rows: List[Dict[str, Any]] = []
    for key, best in groups.items():
        model_id, level = key
        rows.append(
            {
                "model_id": model_id,
                "thinking_level": level,
                "accuracy": best.get("accuracy"),
                "cost_usd": best.get("cost_usd"),
                "duration_seconds": best.get("duration_seconds"),
                "runs": counts.get(key, 1),
            }
        )

    rows.sort(
        key=lambda r: (
            0 if r.get("accuracy") is None else -r["accuracy"],
            r.get("cost_usd") if r.get("cost_usd") is not None else float("inf"),
            r.get("duration_seconds") if r.get("duration_seconds") is not None else float("inf"),
            r.get("model_id") or "",
            r.get("thinking_level") or "",
        )
    )
    return rows


def delete_runs_for_model(model_id: str) -> int:
    with get_session() as session:
        runs = session.scalars(select(QARunRecord).where(QARunRecord.model_id == model_id)).all()
        count = len(runs)
        for run in runs:
            session.delete(run)
        return count


__all__ = [
    "init_db",
    "save_run",
    "list_runs",
    "get_run",
    "leaderboard",
    "delete_runs_for_model",
]
