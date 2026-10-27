"""Idempotent batch-scoring orchestration with PostgreSQL run history.

The input is the existing analytics.baskets materialized view. This job does
not ingest new transactions or refresh materialized views automatically.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL, FEATURE_COLUMNS
from .score import load_saved_model, load_scoring_features


logger = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).with_name("sql") / "pipeline_runs.sql"


def validate_batch(frame: pd.DataFrame, as_of_day: int) -> int:
    """Reject invalid inputs before invoking the scorer."""
    if frame.empty:
        raise ValueError("Scoring batch is empty.")
    expected = {"household_key", "as_of_day", *FEATURE_COLUMNS}
    if expected - set(frame.columns):
        raise ValueError(f"Missing fields: {sorted(expected - set(frame.columns))}")
    if frame["household_key"].isna().any() or frame["household_key"].duplicated().any():
        raise ValueError("Household identifiers must be present and unique.")
    if not frame["as_of_day"].eq(as_of_day).all():
        raise ValueError("Mixed observation days in scoring batch.")

    numeric = frame[FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
    if np.isinf(numeric.to_numpy(dtype=float)).any():
        raise ValueError("Infinite feature values in scoring batch.")
    if not numeric["recency_days"].between(0, 89).all():
        raise ValueError("Recency must be within the 90-day feature window.")
    for column in ("baskets_90d", "baskets_30d", "baskets_previous_30d"):
        if numeric[column].isna().any() or (numeric[column] < 0).any():
            raise ValueError(f"Invalid basket count: {column}")
    if (numeric["baskets_90d"] < 1).any():
        raise ValueError("Every scoring household needs purchase history.")
    if (
        numeric["baskets_30d"] + numeric["baskets_previous_30d"]
        > numeric["baskets_90d"]
    ).any():
        raise ValueError("30-day basket counts exceed 90-day counts.")
    return len(frame)


def _initialize_runs(engine) -> None:
    # The single packaged SQL migration is the source of truth for this table.
    with engine.begin() as connection:
        connection.exec_driver_sql(SCHEMA_PATH.read_text(encoding="utf-8"))


def _save_run(engine, *, run_id: str, as_of_day: int, version: str,
              checksum: str, source_max_day: int, status: str,
              input_rows: int | None = None, scored_rows: int | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO analytics.pipeline_runs (
                run_id, as_of_day, model_version, model_sha256, source_max_day,
                status, input_rows, scored_rows, finished_at
            ) VALUES (
                CAST(:run_id AS UUID), :day, :version, :checksum, :max_day,
                :status, :input_rows, :scored_rows,
                CASE WHEN :status = 'skipped' THEN CURRENT_TIMESTAMP ELSE NULL END
            )
        """), {
            "run_id": run_id, "day": as_of_day, "version": version,
            "checksum": checksum, "max_day": source_max_day,
            "status": status, "input_rows": input_rows, "scored_rows": scored_rows,
        })


def _finish_run(engine, run_id: str, *, status: str, input_rows: int | None,
                scored_rows: int | None, error: Exception | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE analytics.pipeline_runs
            SET status = :status, finished_at = CURRENT_TIMESTAMP,
                input_rows = :input_rows, scored_rows = :scored_rows,
                error_type = :error_type, error_message = :error_message
            WHERE run_id = CAST(:run_id AS UUID)
        """), {
            "run_id": run_id, "status": status,
            "input_rows": input_rows, "scored_rows": scored_rows,
            "error_type": type(error).__name__ if error else None,
            "error_message": str(error)[:300] if error else None,
        })


def _already_completed(engine, *, as_of_day: int, version: str,
                       checksum: str) -> int | None:
    """Skip unchanged observation days; --force covers late corrections."""
    with engine.connect() as connection:
        previous = connection.execute(text("""
            SELECT scored_rows
            FROM analytics.pipeline_runs
            WHERE as_of_day = :day AND model_version = :version
              AND model_sha256 = :checksum AND status = 'succeeded'
            ORDER BY finished_at DESC LIMIT 1
        """), {"day": as_of_day, "version": version, "checksum": checksum}
        ).scalar_one_or_none()
        if not previous:
            return None
        stored = connection.execute(text("""
            SELECT COUNT(*) FROM analytics.customer_predictions
            WHERE as_of_day = :day AND model_version = :version
        """), {"day": as_of_day, "version": version}).scalar_one()
        return int(stored) if int(stored) == int(previous) else None


def run_once(*, as_of_day: int | None = None, force: bool = False,
             dry_run: bool = False, refresh_explorer: bool = False) -> dict:
    """Run one batch; return the outcome or raise after recording failure."""
    _, metadata = load_saved_model()  # checks model path, features, and SHA256
    version = str(metadata["model_version"])
    checksum = str(metadata["model_sha256"])
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            maximum = connection.execute(
                text("SELECT MAX(day) FROM analytics.baskets")
            ).scalar_one()
        if maximum is None:
            raise ValueError("analytics.baskets has no rows.")
        day = int(maximum) if as_of_day is None else int(as_of_day)
        if not 180 <= day <= int(maximum):
            raise ValueError(f"Observation day must be between 180 and {maximum}.")

        if dry_run:
            count = validate_batch(load_scoring_features(day), day)
            return {"status": "dry_run", "as_of_day": day,
                    "model_version": version, "input_rows": count}

        _initialize_runs(engine)
        run_id = str(uuid4())
        with engine.connect() as lock_connection:
            locked = lock_connection.execute(
                text("SELECT pg_try_advisory_lock(617431, :day)"),
                {"day": day},
            ).scalar_one()
            lock_connection.commit()
            if not locked:
                raise RuntimeError(f"Another batch is scoring observation day {day}.")
            try:
                previous = None if force or refresh_explorer else _already_completed(
                    engine, as_of_day=day, version=version, checksum=checksum
                )
                if previous is not None:
                    _save_run(
                        engine, run_id=run_id, as_of_day=day, version=version,
                        checksum=checksum, source_max_day=int(maximum),
                        status="skipped", scored_rows=previous,
                    )
                    return {"status": "skipped", "as_of_day": day,
                            "model_version": version, "scored_rows": previous}

                _save_run(
                    engine, run_id=run_id, as_of_day=day, version=version,
                    checksum=checksum, source_max_day=int(maximum), status="running",
                )
                input_rows = None
                scored_rows = None
                try:
                    input_rows = validate_batch(load_scoring_features(day), day)
                    logger.info("Run %s: validated %s household features", run_id, input_rows)
                    subprocess.run([
                        sys.executable, "-m", "retail_analytics.score",
                        "--as-of-day", str(day),
                    ], check=True)
                    with engine.connect() as connection:
                        scored_rows = int(connection.execute(text("""
                            SELECT COUNT(*) FROM analytics.customer_predictions
                            WHERE as_of_day = :day AND model_version = :version
                        """), {"day": day, "version": version}).scalar_one())
                    if scored_rows != input_rows:
                        raise ValueError("Saved prediction count differs from input count.")
                    if refresh_explorer:
                        subprocess.run([
                            sys.executable, "-m", "retail_analytics.build_explorer",
                            "--as-of-day", str(day), "--model-version", version,
                        ], check=True)
                    _finish_run(
                        engine, run_id, status="succeeded",
                        input_rows=input_rows, scored_rows=scored_rows,
                    )
                    return {"status": "succeeded", "as_of_day": day,
                            "model_version": version, "run_id": run_id,
                            "input_rows": input_rows, "scored_rows": scored_rows}
                except Exception as exc:
                    _finish_run(
                        engine, run_id, status="failed",
                        input_rows=input_rows, scored_rows=scored_rows, error=exc,
                    )
                    logger.exception("Run %s failed", run_id)
                    raise
            finally:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(617431, :day)"), {"day": day}
                )
                lock_connection.commit()
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate, score, and record a repeatable household batch."
    )
    parser.add_argument("--as-of-day", type=int,
                        help="Defaults to the latest day in analytics.baskets.")
    parser.add_argument("--force", action="store_true",
                        help="Rescore when source data was corrected without a new day.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate without creating tables or writing predictions.")
    parser.add_argument("--refresh-explorer", action="store_true",
                        help="Also rebuild interactive explorer profiles.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_once(**vars(args))
    print("\nBatch:", ", ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
