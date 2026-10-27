import os
import argparse
import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL, FEATURE_COLUMNS


# --------------------------------------------------
# Paths
# --------------------------------------------------

PROJECT_ROOT = Path(
    os.getenv(
        "RETAIL_PROJECT_ROOT",
        Path(__file__).resolve().parents[2],
    )
).resolve()

MODEL_DIR = PROJECT_ROOT / "artifacts" / "models" / "v1"
MODEL_PATH = MODEL_DIR / "repurchase_model.txt"
METADATA_PATH = MODEL_DIR / "metadata.json"

REPORT_DIR = PROJECT_ROOT / "reports" / "tables"


# --------------------------------------------------
# Load and validate saved model
# --------------------------------------------------

def load_saved_model():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"Model file not found: {MODEL_PATH}"
        )

    if not METADATA_PATH.is_file():
        raise FileNotFoundError(
            f"Model metadata not found: {METADATA_PATH}"
        )

    metadata = json.loads(
        METADATA_PATH.read_text(encoding="utf-8")
    )

    if metadata["model_file"] != MODEL_PATH.name:
        raise ValueError(
            "Unexpected model filename in metadata."
        )

    if metadata["feature_columns"] != FEATURE_COLUMNS:
        raise ValueError(
            "Model feature contract does not match the code."
        )

    checksum = hashlib.sha256(
        MODEL_PATH.read_bytes()
    ).hexdigest()

    if checksum != metadata["model_sha256"]:
        raise ValueError(
            "Model file checksum mismatch."
        )

    model = lgb.Booster(
        model_file=str(MODEL_PATH)
    )

    if model.feature_name() != FEATURE_COLUMNS:
        raise ValueError(
            "Saved model feature names do not match."
        )

    return model, metadata


# --------------------------------------------------
# Load features for a requested observation day
# --------------------------------------------------

def load_scoring_features(as_of_day: int) -> pd.DataFrame:
    engine = create_engine(DATABASE_URL)

    try:
        with engine.connect() as connection:

            max_day = connection.execute(
                text("""
                    SELECT MAX(day)
                    FROM analytics.baskets
                """)
            ).scalar_one()

            if max_day is None:
                raise ValueError(
                    "No basket data is available."
                )

            if not 180 <= as_of_day <= max_day:
                raise ValueError(
                    f"as_of_day must be between 180 and {max_day}."
                )

            query = text("""
                SELECT *
                FROM analytics.household_features_at(:as_of_day)
                ORDER BY household_key
            """)

            data = pd.read_sql_query(
                query,
                connection,
                params={
                    "as_of_day": as_of_day
                },
            )

    finally:
        engine.dispose()

    if data.empty:
        raise ValueError(
            "No households available for scoring."
        )

    if data["household_key"].isna().any():
        raise ValueError(
            "Missing household identifiers."
        )

    if data["household_key"].duplicated().any():
        raise ValueError(
            "Duplicate households in scoring data."
        )

    if not data["as_of_day"].eq(as_of_day).all():
        raise ValueError(
            "Incorrect observation day returned."
        )

    missing_features = [
        column
        for column in FEATURE_COLUMNS
        if column not in data.columns
    ]

    if missing_features:
        raise ValueError(
            f"Missing scoring features: {missing_features}"
        )

    return data


# --------------------------------------------------
# Save predictions to PostgreSQL
# --------------------------------------------------

def save_predictions(scored: pd.DataFrame) -> None:
    if scored.empty:
        raise ValueError(
            "Cannot save an empty prediction dataset."
        )

    query = text("""
        INSERT INTO analytics.customer_predictions AS existing (
            household_key,
            as_of_day,
            model_version,
            predicted_probability,
            score_decile,
            propensity_rank
        )
        VALUES (
            :household_key,
            :as_of_day,
            :model_version,
            :predicted_probability,
            :score_decile,
            :propensity_rank
        )

        ON CONFLICT (
            household_key,
            as_of_day,
            model_version
        )

        DO UPDATE SET
            predicted_probability = EXCLUDED.predicted_probability,
            score_decile = EXCLUDED.score_decile,
            propensity_rank = EXCLUDED.propensity_rank,
            scored_at = CURRENT_TIMESTAMP

        WHERE (
            existing.predicted_probability,
            existing.score_decile,
            existing.propensity_rank
        ) IS DISTINCT FROM (
            EXCLUDED.predicted_probability,
            EXCLUDED.score_decile,
            EXCLUDED.propensity_rank
        )
    """)

    records = [
        {
            "household_key": row["household_key"],
            "as_of_day": int(row["as_of_day"]),
            "model_version": str(row["model_version"]),
            "predicted_probability": float(
                row["predicted_probability"]
            ),
            "score_decile": int(row["score_decile"]),
            "propensity_rank": int(row["rank"]),
        }
        for row in scored.to_dict(orient="records")
    ]

    as_of_day = int(scored["as_of_day"].iloc[0])
    model_version = str(scored["model_version"].iloc[0])

    engine = create_engine(DATABASE_URL)

    try:
        with engine.begin() as connection:

            connection.execute(
                query,
                records,
            )

            stored_count = connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM analytics.customer_predictions
                    WHERE as_of_day = :as_of_day
                      AND model_version = :model_version
                """),
                {
                    "as_of_day": as_of_day,
                    "model_version": model_version,
                },
            ).scalar_one()

            if stored_count != len(records):
                raise ValueError(
                    "Stored prediction count does not "
                    "match scoring output."
                )

    finally:
        engine.dispose()

    print(
        f"Predictions stored in PostgreSQL: {len(records):,}"
    )


# --------------------------------------------------
# Run scoring pipeline
# --------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score retail households for repurchase."
    )

    parser.add_argument(
        "--as-of-day",
        type=int,
        required=True,
        help="Observation day used to generate features.",
    )

    args = parser.parse_args()

    # 1. Load model

    model, metadata = load_saved_model()

    # 2. Load historical features

    data = load_scoring_features(
        args.as_of_day
    )

    features = data[FEATURE_COLUMNS].copy()

    for column in FEATURE_COLUMNS:
        features[column] = pd.to_numeric(
            features[column],
            errors="raise",
        )

    if np.isinf(
        features.to_numpy(dtype=float)
    ).any():
        raise ValueError(
            "Infinite feature values detected."
        )

    # 3. Generate predictions

    probabilities = np.asarray(
        model.predict(
            features,
            validate_features=True,
        ),
        dtype=float,
    )

    if not np.isfinite(probabilities).all():
        raise ValueError(
            "Non-finite predictions detected."
        )

    if not np.all(
        (probabilities >= 0)
        & (probabilities <= 1)
    ):
        raise ValueError(
            "Predictions must be between 0 and 1."
        )

    # 4. Create scoring dataset

    scored = data[
        ["household_key", "as_of_day"]
    ].copy()

    scored["predicted_probability"] = probabilities

    # 5. Assign propensity deciles

    ranks = scored["predicted_probability"].rank(
        method="first"
    )

    if len(scored) >= 10:
        scored["score_decile"] = (
            pd.qcut(
                ranks,
                q=10,
                labels=False,
            ) + 1
        )
    else:
        scored["score_decile"] = np.ceil(
            10 * ranks / len(scored)
        ).astype(int)

    # 6. Rank customers by probability

    scored = scored.sort_values(
        ["predicted_probability", "household_key"],
        ascending=[False, True],
    ).reset_index(drop=True)

    scored.insert(
        0,
        "rank",
        range(1, len(scored) + 1),
    )

    # 7. Add model version BEFORE saving

    scored["model_version"] = metadata["model_version"]

    # 8. Save predictions to PostgreSQL

    save_predictions(scored)

    # 9. Export predictions to CSV

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        REPORT_DIR
        / f"scored_day_{args.as_of_day}_"
          f"{metadata['model_version']}.csv"
    )

    scored.to_csv(
        output_path,
        index=False,
    )

    # 10. Print summary

    print(f"\nModel version: {metadata['model_version']}")
    print(f"Observation day: {args.as_of_day}")
    print(f"Households scored: {len(scored):,}")
    print(f"Output: {output_path}")

    print("\nTop 10 customers:")

    print(
        scored.head(10).to_string(index=False)
    )


if __name__ == "__main__":
    main()