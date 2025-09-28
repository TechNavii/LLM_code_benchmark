from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "runs" / "history.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                model_id TEXT NOT NULL,
                tasks TEXT NOT NULL,
                samples INTEGER NOT NULL,
                accuracy REAL,
                total_cost REAL,
                total_duration REAL,
                summary_path TEXT NOT NULL,
                summary_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                duration REAL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost REAL,
                error TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
            """
        )
    conn.close()


def save_run(summary: Dict) -> str:
    run_dir = Path(summary["run_dir"]).resolve()
    run_id = run_dir.name
    conn = get_connection()
    attempts = summary.get("attempts", [])
    accuracy = summary.get("metrics", {}).get("overall", {}).get("macro_model_accuracy")
    total_cost = summary.get("token_usage", {}).get("total_cost_usd")
    total_duration = summary.get("timing", {}).get("total_duration_seconds")
    with conn:
        conn.execute("DELETE FROM attempts WHERE run_id = ?", (run_id,))
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                id, timestamp_utc, model_id, tasks, samples, accuracy,
                total_cost, total_duration, summary_path, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                summary.get("timestamp_utc"),
                ",".join(summary.get("models", [])),
                json.dumps(summary.get("tasks", [])),
                summary.get("samples", 1),
                accuracy,
                total_cost,
                total_duration,
                str(run_dir / "summary.json"),
                json.dumps(summary),
            ),
        )
        for attempt in attempts:
            usage = attempt.get("usage") or {}
            conn.execute(
                """
                INSERT INTO attempts (
                    run_id, task_id, status, duration, prompt_tokens,
                    completion_tokens, cost, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    attempt.get("task_id"),
                    attempt.get("status"),
                    attempt.get("duration_seconds"),
                    usage.get("prompt_tokens") or usage.get("input_tokens"),
                    usage.get("completion_tokens") or usage.get("output_tokens"),
                    attempt.get("cost_usd"),
                    attempt.get("error"),
                ),
            )
    conn.close()
    return run_id


def list_runs(limit: int = 50) -> Iterable[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, timestamp_utc, model_id, accuracy, total_cost, total_duration FROM runs ORDER BY timestamp_utc DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def get_run(run_id: str) -> Dict | None:
    conn = get_connection()
    row = conn.execute("SELECT summary_json FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row[0])


def leaderboard() -> Iterable[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
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
    ).fetchall()
    conn.close()
    return rows
