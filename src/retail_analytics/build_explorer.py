"""Populate small PostgreSQL tables for the Behind the Basket application.

Run *after* sql/schema/explorer.sql and ordinary day-711 scoring. The
historical game model fits train+validation only, so holdout outcomes have
not been used to fit that model. The saved v1 model serves current profiles.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL, FEATURE_COLUMNS, TARGET_COLUMN, load_data, split_by_time
from .explorer import cohort_dna, features_as_dict, safe_number
from .models import make_lightgbm_model
from .score import load_saved_model


PROFILE_UPSERT = text("""
    INSERT INTO analytics.explorer_profiles (
        household_key, as_of_day, model_version, predicted_probability,
        propensity_rank, score_decile, features, dna, purchase_history
    ) VALUES (
        :household_key, :as_of_day, :model_version, :predicted_probability,
        :propensity_rank, :score_decile, CAST(:features AS jsonb),
        CAST(:dna AS jsonb), CAST(:purchase_history AS jsonb)
    ) ON CONFLICT (household_key, as_of_day, model_version) DO UPDATE SET
        predicted_probability = EXCLUDED.predicted_probability,
        propensity_rank = EXCLUDED.propensity_rank,
        score_decile = EXCLUDED.score_decile,
        features = EXCLUDED.features,
        dna = EXCLUDED.dna,
        purchase_history = EXCLUDED.purchase_history
""")

GAME_UPSERT = text("""
    INSERT INTO analytics.explorer_game_cases (
        household_key, as_of_day, predicted_probability, repurchased_7d,
        baseline_rank, features, purchase_history
    ) VALUES (
        :household_key, :as_of_day, :predicted_probability, :repurchased_7d,
        :baseline_rank, CAST(:features AS jsonb), CAST(:purchase_history AS jsonb)
    ) ON CONFLICT (household_key, as_of_day) DO UPDATE SET
        predicted_probability = EXCLUDED.predicted_probability,
        repurchased_7d = EXCLUDED.repurchased_7d,
        baseline_rank = EXCLUDED.baseline_rank,
        features = EXCLUDED.features,
        purchase_history = EXCLUDED.purchase_history
""")


def _history_for(
    household_key: str,
    as_of_day: int,
    grouped_events: dict[str, list[tuple[int, float, int]]],
) -> list[dict]:
    """Purchase history strictly through the observation day (never future)."""
    return [
        {
            "days_ago": as_of_day - day,
            "sales": round(sales, 2),
            "baskets": baskets,
        }
        for day, sales, baskets in grouped_events.get(household_key, [])
        if 0 <= as_of_day - day <= 89
    ]


def _events(connection, first_day: int, last_day: int):
    visits = pd.read_sql_query(
        text("""
            SELECT household_key, day,
                   SUM(basket_sales)::double precision AS sales,
                   COUNT(*)::integer AS baskets
            FROM analytics.baskets
            WHERE day BETWEEN :first_day AND :last_day
            GROUP BY household_key, day
            ORDER BY household_key, day
        """),
        connection,
        params={"first_day": first_day, "last_day": last_day},
    )
    grouped: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
    for row in visits.itertuples(index=False):
        grouped[str(row.household_key)].append(
            (int(row.day), float(row.sales), int(row.baskets))
        )
    return grouped


def _upsert_batches(connection, statement, rows, chunk_size=500):
    for start in range(0, len(rows), chunk_size):
        connection.execute(statement, rows[start:start + chunk_size])


def build(as_of_day: int, model_version: str = "v1") -> tuple[int, int]:
    all_data = load_data()
    splits = split_by_time(all_data)

    # Holdout game probabilities are genuinely out of sample. Do not use
    # the all-data v1 artifact to claim historical holdout performance.
    development = pd.concat(
        [splits["train"], splits["validation"]], ignore_index=True
    )
    test = splits["test"].copy()
    historic_model = make_lightgbm_model()
    historic_model.fit(
        development[FEATURE_COLUMNS], development[TARGET_COLUMN]
    )
    test["predicted_probability"] = historic_model.predict_proba(
        test[FEATURE_COLUMNS]
    )[:, 1]

    baseline = test.sort_values(
        ["as_of_day", "recency_days", "baskets_90d", "household_key"],
        ascending=[True, True, False, True],
        kind="mergesort",
    ).copy()
    baseline["baseline_rank"] = (
        baseline.groupby("as_of_day").cumcount() + 1
    )
    test = test.merge(
        baseline[["household_key", "as_of_day", "baseline_rank"]],
        on=["household_key", "as_of_day"],
        validate="one_to_one",
    )

    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            profiles = pd.read_sql_query(
                text("""
                    SELECT f.*, p.model_version, p.predicted_probability,
                           p.propensity_rank, p.score_decile
                    FROM analytics.household_features_at(:as_of_day) f
                    JOIN analytics.customer_predictions p
                      ON p.household_key = f.household_key
                     AND p.as_of_day = f.as_of_day
                     AND p.model_version = :model_version
                    ORDER BY f.household_key
                """),
                connection,
                params={"as_of_day": as_of_day, "model_version": model_version},
            )
            first_day = min(int(test["as_of_day"].min()), as_of_day) - 89
            grouped_events = _events(connection, first_day, as_of_day)

        if profiles.empty:
            raise ValueError("No saved profiles for the requested scoring day.")

        for name in FEATURE_COLUMNS:
            profiles[name] = pd.to_numeric(profiles[name], errors="raise")

        native_model, metadata = load_saved_model()
        if metadata["model_version"] != model_version:
            raise ValueError("Saved model version does not match the requested day.")
        recomputed = np.asarray(
            native_model.predict(profiles[FEATURE_COLUMNS], validate_features=True)
        )
        if not np.allclose(
            recomputed, profiles["predicted_probability"].to_numpy(), atol=1e-7
        ):
            raise ValueError("Saved scoring results differ from current v1 model.")

        dna = cohort_dna(profiles)
        profile_records = []
        for position, row in enumerate(profiles.to_dict("records")):
            profile_records.append({
                "household_key": str(row["household_key"]),
                "as_of_day": int(row["as_of_day"]),
                "model_version": model_version,
                "predicted_probability": float(row["predicted_probability"]),
                "propensity_rank": int(row["propensity_rank"]),
                "score_decile": int(row["score_decile"]),
                "features": json.dumps(features_as_dict(row), allow_nan=False),
                "dna": json.dumps({
                    name: safe_number(dna.iloc[position][name])
                    for name in dna.columns
                }, allow_nan=False),
                "purchase_history": json.dumps(
                    _history_for(str(row["household_key"]), as_of_day, grouped_events)
                ),
            })

        game_records = []
        for row in test.to_dict("records"):
            day = int(row["as_of_day"])
            key = str(row["household_key"])
            game_records.append({
                "household_key": key,
                "as_of_day": day,
                "predicted_probability": float(row["predicted_probability"]),
                "repurchased_7d": bool(row[TARGET_COLUMN]),
                "baseline_rank": int(row["baseline_rank"]),
                "features": json.dumps(features_as_dict(row), allow_nan=False),
                "purchase_history": json.dumps(
                    _history_for(key, day, grouped_events)
                ),
            })

        # Fail atomically if schema is missing or any individual insert fails.
        with engine.begin() as connection:
            _upsert_batches(connection, PROFILE_UPSERT, profile_records)
            _upsert_batches(connection, GAME_UPSERT, game_records)

        return len(profile_records), len(game_records)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Behind the Basket data")
    parser.add_argument("--as-of-day", type=int, default=711)
    parser.add_argument("--model-version", default="v1")
    args = parser.parse_args()

    profiles, cases = build(args.as_of_day, args.model_version)
    print(f"Explorer profiles: {profiles:,}")
    print(f"Leakage-safe historical game cases: {cases:,}")
    print("Ready: Beat the Model, Shopping DNA, Behavioral Paradox")


if __name__ == "__main__":
    main()
