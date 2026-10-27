import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .data import DATABASE_URL, FEATURE_COLUMNS
from .explorer import brier_loss, find_paradox_pairs
from .score import load_saved_model


logger = logging.getLogger(__name__)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(
    title="Retail Customer Analytics API",
    description="Seven-day customer repurchase predictions",
    version="0.1.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# Response schemas
# --------------------------------------------------

class Prediction(BaseModel):
    household_key: str
    as_of_day: int
    model_version: str
    predicted_probability: float
    score_decile: int
    rank: int


class PredictionList(BaseModel):
    as_of_day: int
    model_version: str
    total: int
    limit: int
    offset: int
    predictions: list[Prediction]


# --------------------------------------------------
# Database helper
# --------------------------------------------------

def fetch_rows(query: str, params: dict | None = None) -> list[dict]:
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text(query),
                params or {},
            )

            return [
                dict(row)
                for row in result.mappings().all()
            ]

    except SQLAlchemyError as exc:
        logger.exception("Database request failed")

        raise HTTPException(
            status_code=503,
            detail="Database unavailable.",
        ) from exc


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/health")
def health():
    fetch_rows("SELECT 1 AS connected")

    return {
        "status": "ok",
        "database": "connected",
    }


# --------------------------------------------------
# Available scoring runs
# --------------------------------------------------

@app.get("/runs")
def list_runs():
    return fetch_rows("""
        SELECT
            as_of_day,
            model_version,
            COUNT(*) AS households_scored
        FROM analytics.customer_predictions
        GROUP BY
            as_of_day,
            model_version
        ORDER BY
            as_of_day DESC,
            model_version
    """)


# --------------------------------------------------
# Operational history for automated scoring
# --------------------------------------------------

@app.get("/pipeline/runs")
def list_pipeline_runs(limit: int = Query(20, ge=1, le=100)):
    # Expose operational status without publishing internal error messages.
    return fetch_rows("""
        SELECT
            run_id::TEXT AS run_id,
            as_of_day,
            model_version,
            status,
            source_max_day,
            input_rows,
            scored_rows,
            started_at,
            finished_at,
            error_type
        FROM analytics.pipeline_runs
        ORDER BY started_at DESC
        LIMIT :limit
    """, {"limit": limit})


# --------------------------------------------------
# Model monitoring (aggregate, no household identifiers)
# --------------------------------------------------

@app.get("/monitoring/latest")
def latest_monitoring_report(model_version: str = Query("v1")):
    rows = fetch_rows("""
        SELECT as_of_day, model_version, source_max_day, household_count,
               reference_count, checked_at, drift_status, feature_drift,
               prediction_drift, alerts, label_status, outcome_metrics
        FROM analytics.monitoring_reports
        WHERE model_version = :version
        ORDER BY as_of_day DESC
        LIMIT 1
    """, {"version": model_version})
    if not rows:
        raise HTTPException(status_code=404, detail="No monitoring report exists yet.")
    return rows[0]


@app.get("/monitoring/history")
def monitoring_history(
    model_version: str = Query("v1"),
    limit: int = Query(20, ge=1, le=100),
):
    return fetch_rows("""
        SELECT as_of_day, model_version, source_max_day, checked_at,
               drift_status, label_status,
               jsonb_array_length(alerts) AS alert_count,
               outcome_metrics
        FROM analytics.monitoring_reports
        WHERE model_version = :version
        ORDER BY as_of_day DESC
        LIMIT :limit
    """, {"version": model_version, "limit": limit})


# --------------------------------------------------
# Ranked customer predictions
# --------------------------------------------------

@app.get(
    "/predictions",
    response_model=PredictionList,
)
def list_predictions(
    as_of_day: int = Query(..., ge=1),
    model_version: str = Query("v1", min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    params = {
        "as_of_day": as_of_day,
        "model_version": model_version,
        "limit": limit,
        "offset": offset,
    }

    count_result = fetch_rows("""
        SELECT COUNT(*) AS total
        FROM analytics.customer_predictions
        WHERE as_of_day = :as_of_day
          AND model_version = :model_version
    """, params)

    predictions = fetch_rows("""
        SELECT
            household_key,
            as_of_day,
            model_version,
            predicted_probability,
            score_decile,
            propensity_rank AS rank

        FROM analytics.customer_predictions

        WHERE as_of_day = :as_of_day
          AND model_version = :model_version

        ORDER BY propensity_rank

        LIMIT :limit
        OFFSET :offset
    """, params)

    return {
        "as_of_day": as_of_day,
        "model_version": model_version,
        "total": count_result[0]["total"],
        "limit": limit,
        "offset": offset,
        "predictions": predictions,
    }


# --------------------------------------------------
# Individual customer prediction
# --------------------------------------------------

@app.get(
    "/predictions/{household_key}",
    response_model=Prediction,
)
def get_customer_prediction(
    household_key: str,
    as_of_day: int = Query(..., ge=1),
    model_version: str = Query("v1", min_length=1),
):
    results = fetch_rows("""
        SELECT
            household_key,
            as_of_day,
            model_version,
            predicted_probability,
            score_decile,
            propensity_rank AS rank

        FROM analytics.customer_predictions

        WHERE household_key = :household_key
          AND as_of_day = :as_of_day
          AND model_version = :model_version
    """, {
        "household_key": household_key,
        "as_of_day": as_of_day,
        "model_version": model_version,
    })

    if not results:
        raise HTTPException(
            status_code=404,
            detail="Prediction not found.",
        )

    return results[0]


# --------------------------------------------------
# Behind the Basket: browser demo and explorer API
# --------------------------------------------------

@app.get("/", include_in_schema=False)
def explorer_home():
    return FileResponse(Path(__file__).with_name("web") / "index.html")


class GameGuess(BaseModel):
    predicted_probability: float = Field(ge=0, le=1)


@lru_cache(maxsize=1)
def get_explorer_model():
    # A single checked native model is shared across incoming requests.
    return load_saved_model()[0]


@app.get("/explorer/game")
def new_game_case():
    # Only past observations are returned here; both the holdout outcome and
    # the model prediction remain hidden until the user submits a guess.
    cases = fetch_rows("""
        SELECT household_key, as_of_day, features, purchase_history
        FROM analytics.explorer_game_cases
        WHERE predicted_probability BETWEEN 0.15 AND 0.85
        ORDER BY random()
        LIMIT 1
    """)
    if not cases:
        raise HTTPException(status_code=404, detail="No game cases available.")
    return cases[0]


@app.post("/explorer/game/{as_of_day}/{household_key}/guess")
def reveal_game_case(as_of_day: int, household_key: str, guess: GameGuess):
    matches = fetch_rows("""
        SELECT predicted_probability, repurchased_7d, baseline_rank
        FROM analytics.explorer_game_cases
        WHERE as_of_day = :as_of_day AND household_key = :household_key
    """, {"as_of_day": as_of_day, "household_key": household_key})
    if not matches:
        raise HTTPException(status_code=404, detail="Game case not found.")
    row = matches[0]
    actual = bool(row["repurchased_7d"])
    model_probability = float(row["predicted_probability"])
    user_loss = brier_loss(guess.predicted_probability, actual)
    model_loss = brier_loss(model_probability, actual)
    return {
        "repurchased_7d": actual,
        "your_probability": guess.predicted_probability,
        "model_probability": model_probability,
        "your_brier": round(user_loss, 5),
        "model_brier": round(model_loss, 5),
        "beat_model": user_loss < model_loss,
        "baseline_rank": int(row["baseline_rank"]),
        "note": "Historical holdout: the prediction predates these outcomes.",
    }


@app.get("/explorer/customers")
def explorer_customers(
    as_of_day: int = Query(711, ge=1),
    model_version: str = Query("v1"),
    limit: int = Query(30, ge=1, le=100),
):
    return fetch_rows("""
        SELECT household_key, predicted_probability, propensity_rank,
               score_decile, dna
        FROM analytics.explorer_profiles
        WHERE as_of_day = :as_of_day AND model_version = :model_version
        ORDER BY propensity_rank
        LIMIT :limit
    """, {
        "as_of_day": as_of_day,
        "model_version": model_version,
        "limit": limit,
    })


@app.get("/explorer/dna/{household_key}")
def explorer_customer_dna(
    household_key: str,
    as_of_day: int = Query(711, ge=1),
    model_version: str = Query("v1"),
):
    rows = fetch_rows("""
        SELECT household_key, as_of_day, model_version,
               propensity_rank, score_decile, features, dna,
               purchase_history, predicted_probability
        FROM analytics.explorer_profiles
        WHERE household_key = :household_key
          AND as_of_day = :as_of_day
          AND model_version = :model_version
    """, {
        "household_key": household_key,
        "as_of_day": as_of_day,
        "model_version": model_version,
    })
    if not rows:
        raise HTTPException(status_code=404, detail="Customer not found.")
    result = dict(rows[0])
    frame = pd.DataFrame([result["features"]], columns=FEATURE_COLUMNS)
    frame = frame.apply(pd.to_numeric, errors="raise")
    probability = float(
        np.asarray(get_explorer_model().predict(frame, validate_features=True))[0]
    )
    result["live_model_probability"] = probability
    return result


@app.get("/explorer/paradoxes")
def explorer_paradoxes(
    as_of_day: int = Query(711, ge=1),
    model_version: str = Query("v1"),
    limit: int = Query(8, ge=1, le=20),
):
    rows = fetch_rows("""
        SELECT household_key, predicted_probability, features
        FROM analytics.explorer_profiles
        WHERE as_of_day = :as_of_day AND model_version = :model_version
    """, {"as_of_day": as_of_day, "model_version": model_version})
    if not rows:
        return []
    frame = pd.DataFrame([
        {
            "household_key": row["household_key"],
            "predicted_probability": row["predicted_probability"],
            "recency_days": row["features"]["recency_days"],
            "baskets_90d": row["features"]["baskets_90d"],
        }
        for row in rows
    ])
    pairs = find_paradox_pairs(frame, limit=limit)
    by_household = {str(row["household_key"]): row["features"] for row in rows}
    model = get_explorer_model()

    for pair in pairs:
        left = by_household[pair["high_household"]]
        right = by_household[pair["low_household"]]
        features = pd.DataFrame([left, right], columns=FEATURE_COLUMNS)
        features = features.apply(pd.to_numeric, errors="raise")
        # Native LightGBM feature contributions are in raw-score/log-odds
        # units, not probability percentage points or causal effects.
        contributions = np.asarray(model.predict(features, pred_contrib=True))
        delta = contributions[0, :-1] - contributions[1, :-1]
        strongest = np.argsort(np.abs(delta))[::-1][:4]
        pair["top_differences"] = [
            {
                "feature": FEATURE_COLUMNS[int(i)],
                "raw_score_difference": round(float(delta[i]), 4),
                "higher_customer_value": left[FEATURE_COLUMNS[int(i)]],
                "lower_customer_value": right[FEATURE_COLUMNS[int(i)]],
            }
            for i in strongest
        ]
    return pairs
