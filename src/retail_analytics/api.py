import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .data import DATABASE_URL


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