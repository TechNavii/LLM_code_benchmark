from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column, relationship, sessionmaker

from server.config import get_settings


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
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_run(summary: Dict) -> str:
    run_dir = Path(summary["run_dir"]).resolve()
    run_id = run_dir.name
    attempts = summary.get("attempts", [])
    accuracy = summary.get("metrics", {}).get("overall", {}).get("macro_model_accuracy")
    total_cost = summary.get("token_usage", {}).get("total_cost_usd")
    total_duration = summary.get("timing", {}).get("total_duration_seconds")
    timestamp_raw = summary.get("timestamp_utc")
    timestamp = dt.datetime.fromisoformat(timestamp_raw) if timestamp_raw else dt.datetime.utcnow()

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
            usage = attempt.get("usage") or {}
            record.attempts.append(
                AttemptRecord(
                    task_id=attempt.get("task_id"),
                    status=attempt.get("status"),
                    duration=attempt.get("duration_seconds"),
                    prompt_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                    completion_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
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
        )
        .order_by(RunRecord.timestamp_utc.desc())
        .limit(limit)
    )
    with get_session() as session:
        rows = session.execute(stmt).all()
    return [
        {
            "id": row.id,
            "timestamp_utc": row.timestamp_utc.isoformat() if row.timestamp_utc else None,
            "model_id": row.model_id,
            "accuracy": row.accuracy,
            "total_cost": row.total_cost,
            "total_duration": row.total_duration,
        }
        for row in rows
    ]


def get_run(run_id: str) -> Dict | None:
    with get_session() as session:
        record = session.get(RunRecord, run_id)
        if record is None:
            return None
        return json.loads(record.summary_json)


def leaderboard() -> List[Dict[str, Optional[float]]]:
    leaderboard_query = text(
        """
        WITH ranked AS (
            SELECT
                id,
                model_id,
                accuracy,
                total_cost,
                total_duration,
                timestamp_utc,
                ROW_NUMBER() OVER (
                    PARTITION BY model_id
                    ORDER BY
                        CASE WHEN accuracy IS NULL THEN 1 ELSE 0 END,
                        accuracy DESC,
                        CASE WHEN total_cost IS NULL THEN 1 ELSE 0 END,
                        total_cost ASC,
                        CASE WHEN total_duration IS NULL THEN 1 ELSE 0 END,
                        total_duration ASC,
                        timestamp_utc DESC
                ) AS row_rank
            FROM runs
        ), counts AS (
            SELECT model_id, COUNT(*) AS run_count
            FROM runs
            GROUP BY model_id
        )
        SELECT
            ranked.model_id,
            ranked.accuracy AS best_accuracy,
            ranked.total_cost AS cost_at_best,
            ranked.total_duration AS duration_at_best,
            counts.run_count AS runs
        FROM ranked
        JOIN counts ON counts.model_id = ranked.model_id
        WHERE ranked.row_rank = 1
        ORDER BY
            CASE WHEN ranked.accuracy IS NULL THEN 1 ELSE 0 END,
            ranked.accuracy DESC,
            CASE WHEN ranked.total_cost IS NULL THEN 1 ELSE 0 END,
            ranked.total_cost ASC
        """
    )
    with get_session() as session:
        rows = session.execute(leaderboard_query).all()
    return [
        {
            "model_id": row.model_id,
            "best_accuracy": row.best_accuracy,
            "cost_at_best": row.cost_at_best,
            "duration_at_best": row.duration_at_best,
            "runs": row.runs,
        }
        for row in rows
    ]
