"""Point-in-time lapse snapshots, target definitions, and cohort coverage.

This is a separate v2 modeling contract. It intentionally does not alter
v1's purchase propensity label or the saved v1 scoring artifact.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL


HORIZONS = (7, 14, 28)
CUTOFFS = tuple(range(180, 661, 30))
TRAIN_LAST_DAY = 510
VALIDATION_DAYS = (540, 570)
HOLDOUT_DAYS = (600, 630, 660)
MIN_BASKETS_90D = 3
MAX_ACTIVE_RECENCY = 30
ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "processed" / "retention_snapshots.csv.gz"

FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "behavioral": (
        "recency_days", "baskets_90d", "baskets_30d", "baskets_prev_30d",
        "sales_90d", "sales_30d", "sales_prev_30d",
        "avg_basket_value_90d", "basket_value_volatility_90d",
        "discount_share_90d", "distinct_stores_90d",
        "avg_product_diversity_90d", "sales_change_ratio",
    ),
    "cadence": (
        "typical_visit_gap_90d", "visit_gap_volatility_90d", "overdue_ratio",
    ),
    "products": (
        "department_diversity_90d", "grocery_sales_share_90d",
        "private_brand_share_90d",
    ),
    "promotions": ("prior_campaigns", "coupon_redemptions_90d"),
    "seasonality": ("week_sin", "week_cos", "year_sin", "year_cos"),
    "demographics": ("age_desc", "income_desc", "household_size_desc"),
}
ALL_FAMILIES = tuple(FEATURE_FAMILIES)
DEMOGRAPHIC_COLUMNS = set(FEATURE_FAMILIES["demographics"])


def classify_cohort(data: pd.DataFrame) -> pd.Series:
    """Expose all known shoppers, but train lapse only on active repeat buyers.

    A shopper with no 90-day visits is *dormant*, not a missing record.
    Not-yet-observed households are not considered acquired and therefore
    are not included in the SQL source population.
    """
    recency = pd.to_numeric(data["recency_days"], errors="raise")
    baskets = pd.to_numeric(data["baskets_90d"], errors="raise")
    return pd.Series(
        np.select(
            [
                recency >= 90,
                recency > MAX_ACTIVE_RECENCY,
                baskets < MIN_BASKETS_90D,
            ],
            ["dormant", "inactive", "limited_history"],
            default="eligible",
        ),
        index=data.index,
        name="segment",
    )


def add_derived_features(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    day = pd.to_numeric(out["as_of_day"], errors="raise").astype(int)
    prev = pd.to_numeric(out["sales_prev_30d"], errors="raise")
    current = pd.to_numeric(out["sales_30d"], errors="raise")
    out["sales_change_ratio"] = (current - prev) / prev.replace(0, np.nan)
    out["week_sin"] = np.sin(2 * np.pi * day / 7)
    out["week_cos"] = np.cos(2 * np.pi * day / 7)
    out["year_sin"] = np.sin(2 * np.pi * day / 365.25)
    out["year_cos"] = np.cos(2 * np.pi * day / 365.25)
    return out


def features_frame(
    data: pd.DataFrame,
    families: tuple[str, ...] = ALL_FAMILIES,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Deterministic numeric model matrix with explicit categorical dummies.

    Column order is persisted in v2 model metadata, and inference reindexes
    to that exact order. Unseen demographic categories cannot shift columns.
    """
    unknown = set(families) - FEATURE_FAMILIES.keys()
    if unknown:
        raise ValueError(f"Unknown feature families: {sorted(unknown)}")
    names = [name for family in families for name in FEATURE_FAMILIES[family]]
    missing = set(names) - set(data.columns)
    if missing:
        raise ValueError(f"Missing retention features: {sorted(missing)}")
    encoded = data[names].copy()
    categorical = [name for name in names if name in DEMOGRAPHIC_COLUMNS]
    numeric = [name for name in names if name not in DEMOGRAPHIC_COLUMNS]
    for name in numeric:
        encoded[name] = pd.to_numeric(encoded[name], errors="raise")
    for name in categorical:
        encoded[name] = (
            encoded[name].fillna("UNKNOWN").astype(str).str.strip().str.upper()
            .replace("", "UNKNOWN")
        )
    if categorical:
        encoded = pd.get_dummies(encoded, columns=categorical, dtype="int8")
    encoded = encoded.replace([np.inf, -np.inf], np.nan)
    if columns is not None:
        encoded = encoded.reindex(columns=columns, fill_value=0)
    if encoded.empty or not len(encoded.columns):
        raise ValueError("Model feature matrix is empty")
    return encoded.astype("float64")


def partition(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    eligible = data.loc[data["segment"].eq("eligible")].copy()
    splits = {
        "train": eligible.loc[eligible["as_of_day"] <= TRAIN_LAST_DAY].copy(),
        "validation": eligible.loc[eligible["as_of_day"].isin(VALIDATION_DAYS)].copy(),
        "holdout": eligible.loc[eligible["as_of_day"].isin(HOLDOUT_DAYS)].copy(),
    }
    if any(frame.empty for frame in splits.values()):
        raise ValueError("A chronological retention split is empty")
    if sum(len(frame) for frame in splits.values()) != len(eligible):
        raise ValueError("Unassigned or overlapping retention rows")
    # All candidate labels are fully matured before the next split begins.
    if TRAIN_LAST_DAY + max(HORIZONS) >= min(VALIDATION_DAYS):
        raise ValueError("Training labels overlap validation time")
    if max(VALIDATION_DAYS) + max(HORIZONS) >= min(HOLDOUT_DAYS):
        raise ValueError("Validation labels overlap holdout time")
    return splits


def load_snapshot(connection, day: int) -> pd.DataFrame:
    snapshot = pd.read_sql_query(
        text("SELECT * FROM analytics.retention_features_at(:day) ORDER BY household_key"),
        connection,
        params={"day": day},
    )
    if snapshot.empty:
        raise ValueError(f"No households with purchase history at day {day}")
    if snapshot["household_key"].duplicated().any():
        raise ValueError("Duplicate retention household keys")
    if snapshot["as_of_day"].ne(day).any():
        raise ValueError("Point-in-time SQL returned an unexpected day")
    snapshot = add_derived_features(snapshot)
    snapshot["segment"] = classify_cohort(snapshot)
    return snapshot


def prepare_snapshots() -> pd.DataFrame:
    engine = create_engine(DATABASE_URL)
    snapshots = []
    try:
        with engine.connect() as connection:
            maximum = connection.execute(
                text("SELECT MAX(day) FROM analytics.baskets")
            ).scalar_one()
            if maximum is None or maximum < max(CUTOFFS) + max(HORIZONS):
                raise ValueError(
                    "Not enough observed future data for the common 28-day holdout"
                )
            for day in CUTOFFS:
                current = load_snapshot(connection, day)
                for horizon in HORIZONS:
                    bought = pd.read_sql_query(
                        text("""
                            SELECT DISTINCT household_key FROM analytics.baskets
                            WHERE day > :day AND day <= :end_day
                        """),
                        connection,
                        params={"day": day, "end_day": day + horizon},
                    )
                    current[f"lapsed_{horizon}d"] = (
                        ~current["household_key"].isin(bought["household_key"])
                    ).astype("int8")
                snapshots.append(current)
                print(
                    f"Day {day}: {len(current):,} known households, "
                    f"{current['segment'].eq('eligible').sum():,} eligible"
                )
    finally:
        engine.dispose()
    data = pd.concat(snapshots, ignore_index=True)
    if data.duplicated(["household_key", "as_of_day"]).any():
        raise ValueError("Repeated household/day pairs")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(CACHE_PATH, index=False, compression="gzip")
    return data


def read_snapshots() -> pd.DataFrame:
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            "First run: python -m retail_analytics.retention prepare"
        )
    data = pd.read_csv(CACHE_PATH, dtype={"household_key": "str"})
    return data


def coverage_summary(data: pd.DataFrame) -> pd.DataFrame:
    return (
        data.groupby(["as_of_day", "segment"], observed=True)
        .agg(households=("household_key", "nunique"))
        .reset_index()
    )
