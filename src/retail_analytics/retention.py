"""Research-to-serving CLI for the independent customer-lapse v2 track.

Run from the repository root after creating sql/marts/retention_features.sql
and sql/schema/retention.sql in the EXISTING local PostgreSQL database:

  python -m retail_analytics.retention run --horizon auto --day 711

No uplift or incremental marketing return is estimated by this program.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL
from .models import make_lightgbm_model, make_logistic_model
from .retention_analysis import REPORTS, run_evaluation
from .retention_data import (
    ALL_FAMILIES, ROOT, classify_cohort, features_frame, load_snapshot,
    prepare_snapshots, read_snapshots,
)


VERSION = "lapse_v2"
MODEL_DIR = ROOT / "artifacts" / "models" / VERSION
MODEL_PATH = MODEL_DIR / "model.joblib"
METADATA_PATH = MODEL_DIR / "metadata.json"


def save_model(data: pd.DataFrame, decision: dict) -> dict:
    if MODEL_PATH.exists() or METADATA_PATH.exists():
        raise FileExistsError(
            "lapse_v2 model already exists. Keep this immutable and create a "
            "new version if retraining is needed."
        )
    selected = data.loc[data["segment"].eq("eligible")].copy()
    horizon = int(decision["selected_horizon_days"])
    selected["target"] = selected[f"lapsed_{horizon}d"].astype(int)
    matrix = features_frame(selected, ALL_FAMILIES)
    model_name = decision["selected_model"]
    model = (
        make_lightgbm_model() if model_name == "LightGBM"
        else make_logistic_model()
    )
    model.fit(matrix, selected["target"])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH, compress=3)
    reloaded = joblib.load(MODEL_PATH)
    np.testing.assert_allclose(
        model.predict_proba(matrix.head(100))[:, 1],
        reloaded.predict_proba(matrix.head(100))[:, 1],
        rtol=1e-10, atol=1e-10,
    )
    metadata = {
        "version": VERSION,
        "model_type": model_name,
        "prediction_target": f"no_purchase_next_{horizon}d_for_active_shoppers",
        "horizon_days": horizon,
        "eligible_condition": "baskets_90d >= 3 AND recency_days <= 30",
        "feature_families": list(ALL_FAMILIES),
        "feature_columns": matrix.columns.tolist(),
        "labeled_training_rows": int(len(selected)),
        "labeled_training_households": int(selected["household_key"].nunique()),
        "max_training_as_of_day": int(selected["as_of_day"].max()),
        "final_training_scope": "all mature observed periods INCLUDING holdout",
        "holdout_protocol": "separately refitted on days <= 570; never final artifact",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_file": MODEL_PATH.name,
        "model_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Saved {VERSION}: {len(selected):,} rows, {len(matrix.columns)} encoded features")
    return metadata


def load_model():
    if not MODEL_PATH.is_file() or not METADATA_PATH.is_file():
        raise FileNotFoundError("Run 'retention run' before scoring the v2 model")
    metadata = json.loads(METADATA_PATH.read_text())
    if metadata["version"] != VERSION or metadata["model_file"] != MODEL_PATH.name:
        raise ValueError("Unexpected retention model metadata")
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != metadata["model_sha256"]:
        raise ValueError("Retention model checksum mismatch")
    # joblib files are trusted local artifacts; never load user-uploaded files.
    return joblib.load(MODEL_PATH), metadata


def _safe_number(value):
    if pd.isna(value):
        return None
    return float(value)


def make_scoring_records(snapshot: pd.DataFrame, model, metadata: dict) -> list[dict]:
    cohort = snapshot.copy()
    cohort["segment"] = classify_cohort(cohort)
    cohort["lapse_probability"] = np.nan
    cohort["risk_rank"] = pd.Series([None] * len(cohort), dtype="object")
    eligible_mask = cohort["segment"].eq("eligible")
    if eligible_mask.any():
        x = features_frame(
            cohort.loc[eligible_mask],
            tuple(metadata["feature_families"]),
            columns=metadata["feature_columns"],
        )
        values = np.asarray(model.predict_proba(x)[:, 1], dtype=float)
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise ValueError("Invalid lapse probabilities")
        cohort.loc[eligible_mask, "lapse_probability"] = values
        active = cohort.loc[eligible_mask].sort_values(
            ["lapse_probability", "household_key"],
            ascending=[False, True], kind="mergesort",
        )
        ranks = pd.Series(range(1, len(active) + 1), index=active.index)
        cohort.loc[active.index, "risk_rank"] = ranks
        threshold = int(np.ceil(0.20 * len(active)))
        cohort.loc[active.index[:threshold], "segment"] = "at_risk"
        cohort.loc[active.index[threshold:], "segment"] = "active"
    records = []
    for row in cohort.to_dict("records"):
        records.append({
            "household_key": str(row["household_key"]),
            "as_of_day": int(row["as_of_day"]),
            "model_version": metadata["version"],
            "horizon_days": int(metadata["horizon_days"]),
            "segment": row["segment"],
            "lapse_probability": _safe_number(row["lapse_probability"]),
            "risk_rank": int(row["risk_rank"]) if pd.notna(row["risk_rank"]) else None,
            "recency_days": int(row["recency_days"]),
            "baskets_90d": int(row["baskets_90d"]),
            "typical_visit_gap_90d": _safe_number(row["typical_visit_gap_90d"]),
            "overdue_ratio": _safe_number(row["overdue_ratio"]),
            "sales_90d": _safe_number(row["sales_90d"]),
        })
    return records


def score_day(day: int) -> dict:
    model, metadata = load_model()
    if day <= metadata["max_training_as_of_day"] + metadata["horizon_days"]:
        raise ValueError("Current scoring day must be after last training label maturity")
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            maximum = connection.execute(
                text("SELECT MAX(day) FROM analytics.baskets")
            ).scalar_one()
            if not 180 <= day <= int(maximum):
                raise ValueError(f"Scoring day must be 180..{maximum}")
            snapshot = load_snapshot(connection, day)
        records = make_scoring_records(snapshot, model, metadata)
        query = text("""
            INSERT INTO analytics.retention_scores AS existing (
                household_key, as_of_day, model_version, horizon_days,
                segment, lapse_probability, risk_rank, recency_days, baskets_90d,
                typical_visit_gap_90d, overdue_ratio, sales_90d
            ) VALUES (
                :household_key, :as_of_day, :model_version, :horizon_days,
                :segment, :lapse_probability, :risk_rank, :recency_days,
                :baskets_90d, :typical_visit_gap_90d, :overdue_ratio, :sales_90d
            ) ON CONFLICT (household_key, as_of_day, model_version) DO UPDATE SET
                segment = EXCLUDED.segment,
                lapse_probability = EXCLUDED.lapse_probability,
                risk_rank = EXCLUDED.risk_rank,
                recency_days = EXCLUDED.recency_days,
                baskets_90d = EXCLUDED.baskets_90d,
                typical_visit_gap_90d = EXCLUDED.typical_visit_gap_90d,
                overdue_ratio = EXCLUDED.overdue_ratio,
                sales_90d = EXCLUDED.sales_90d,
                scored_at = CURRENT_TIMESTAMP
        """)
        with engine.begin() as connection:
            for offset in range(0, len(records), 500):
                connection.execute(query, records[offset:offset + 500])
            count = connection.execute(text("""
                SELECT COUNT(*) FROM analytics.retention_scores
                WHERE as_of_day = :day AND model_version = :version
            """), {"day": day, "version": VERSION}).scalar_one()
            if int(count) != len(records):
                raise ValueError("Retention roster count differs from stored row count")
    finally:
        engine.dispose()
    segments = pd.Series([r["segment"] for r in records]).value_counts().to_dict()
    summary = {"as_of_day": day, "model_version": VERSION,
               "horizon_days": metadata["horizon_days"],
               "households_with_prior_purchase": len(records),
               "segments": segments}
    print(json.dumps(summary, indent=2))
    return summary


def replay_daily(start: int = 600, end: int = 683, step: int = 1) -> pd.DataFrame:
    """Recreate historical daily batches with a frozen development-only model.

    This is an offline walk-forward replay; it does not overwrite online scores,
    alter the database, or use the final all-history model for past dates.
    """
    from .retention_analysis import (
        classification_report, population_stability_index,
    )

    if step < 1 or end < start:
        raise ValueError("Replay requires positive step and end >= start")
    decision = json.loads((REPORTS / "retention_decision.json").read_text())
    horizon = int(decision["selected_horizon_days"])
    data = read_snapshots()
    development = data.loc[
        data["segment"].eq("eligible") & data["as_of_day"].le(570)
    ].copy()
    development["target"] = development[f"lapsed_{horizon}d"].astype(int)
    x = features_frame(development, ALL_FAMILIES)
    model = (
        make_lightgbm_model() if decision["selected_model"] == "LightGBM"
        else make_logistic_model()
    )
    model.fit(x, development["target"])
    ref = development.loc[development["as_of_day"].isin([540, 570])]
    reference_prob = model.predict_proba(
        features_frame(ref, ALL_FAMILIES, columns=x.columns.tolist())
    )[:, 1]
    engine = create_engine(DATABASE_URL)
    series = []
    try:
        with engine.connect() as connection:
            maximum = int(connection.execute(
                text("SELECT MAX(day) FROM analytics.baskets")
            ).scalar_one())
            if end > maximum - horizon:
                raise ValueError(
                    f"Replay outcomes need through day {end + horizon}; "
                    f"source ends at {maximum}"
                )
            if start <= 570:
                raise ValueError("Replay must be strictly after training through day 570")
            for day in range(start, end + 1, step):
                batch = load_snapshot(connection, day)
                eligible = batch.loc[batch["segment"].eq("eligible")].copy()
                if eligible.empty:
                    continue
                scores = model.predict_proba(
                    features_frame(eligible, ALL_FAMILIES, columns=x.columns.tolist())
                )[:, 1]
                buyers = pd.read_sql_query(text("""
                    SELECT DISTINCT household_key FROM analytics.baskets
                    WHERE day > :day AND day <= :end_day
                """), connection, params={"day": day, "end_day": day + horizon})
                eligible["target"] = (
                    ~eligible["household_key"].isin(buyers["household_key"])
                ).astype(int)
                row = classification_report("Frozen development model", eligible, scores)
                series.append({
                    "as_of_day": day,
                    "known_households": len(batch),
                    "eligible_households": len(eligible),
                    "observed_lapse_rate": row["lapse_rate"],
                    "mean_predicted_risk": float(np.mean(scores)),
                    "precision_at_capacity": row["precision_at_capacity"],
                    "prediction_psi_vs_validation": population_stability_index(
                        reference_prob, scores
                    ),
                    "model_trained_through_day": 570,
                    "labels_matured_through_day": day + horizon,
                })
                print(f"Replay day {day}: {len(eligible):,} eligible shoppers")
    finally:
        engine.dispose()
    report = pd.DataFrame(series)
    REPORTS.mkdir(parents=True, exist_ok=True)
    report.to_csv(REPORTS / "retention_replay_daily.csv", index=False)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe retail lapse research v2")
    command = parser.add_subparsers(dest="command", required=True)
    command.add_parser("prepare", help="Materialize point-in-time snapshots and labels")
    run = command.add_parser("run", help="Prepare, evaluate, save, and score v2")
    run.add_argument("--horizon", choices=("auto", "7", "14", "28"), default="auto")
    run.add_argument("--day", type=int, default=711)
    run.add_argument("--bootstraps", type=int, default=500)
    run.add_argument("--margin", type=float, default=15.0)
    run.add_argument("--contact-cost", type=float, default=2.0)
    evaluate = command.add_parser("evaluate", help="Re-evaluate prepared research data")
    evaluate.add_argument("--horizon", choices=("auto", "7", "14", "28"), default="auto")
    evaluate.add_argument("--bootstraps", type=int, default=500)
    evaluate.add_argument("--margin", type=float, default=15.0)
    evaluate.add_argument("--contact-cost", type=float, default=2.0)
    score = command.add_parser("score", help="Score the existing v2 model")
    score.add_argument("--day", type=int, default=711)
    replay = command.add_parser("replay", help="Genuine day-by-day frozen-model historical replay")
    replay.add_argument("--start", type=int, default=600)
    replay.add_argument("--end", type=int, default=683)
    replay.add_argument("--step", type=int, default=1)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_snapshots()
    elif args.command == "score":
        score_day(args.day)
    elif args.command == "replay":
        replay_daily(args.start, args.end, args.step)
    else:
        data = prepare_snapshots() if args.command == "run" else read_snapshots()
        horizon = None if args.horizon == "auto" else int(args.horizon)
        decision = run_evaluation(
            data, horizon=horizon, bootstraps=args.bootstraps,
            gross_margin=args.margin, contact_cost=args.contact_cost,
        )
        if args.command == "run":
            save_model(data, decision)
            score_day(args.day)
            print(f"Research reports: {REPORTS}")


if __name__ == "__main__":
    main()
