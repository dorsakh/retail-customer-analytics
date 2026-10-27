"""Shared, testable logic for the Behind the Basket explorer."""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from .data import FEATURE_COLUMNS


# These are descriptive cohort percentiles, not personality diagnoses.
# A high regularity score means low visit-interval volatility.
DNA_AXES = {
    "activity": ("baskets_90d", True),
    "regularity": ("visit_interval_volatility_90d", False),
    "spending": ("sales_90d", True),
    "momentum": ("sales_growth_30d", True),
    "discount_reliance": ("discount_share_90d", True),
}


def cohort_dna(frame: pd.DataFrame) -> pd.DataFrame:
    """Return 0–100 cohort percentiles, preserving missing observations."""
    result = pd.DataFrame(index=frame.index)

    for axis, (feature, increasing) in DNA_AXES.items():
        values = pd.to_numeric(frame[feature], errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        # A smaller visit-interval volatility means more regular shopping.
        percentile = values.rank(
            pct=True,
            ascending=increasing,
            method="average",
        )
        result[axis] = (100 * percentile).round(1)

    return result


def safe_number(value: object) -> float | None:
    """Convert SQL/pandas numeric values into strict JSON-compatible numbers."""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def features_as_dict(row: Mapping) -> dict[str, float | None]:
    return {name: safe_number(row[name]) for name in FEATURE_COLUMNS}


def brier_loss(probability: float, observed: bool | int) -> float:
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Probability must be finite and within [0, 1].")
    return (float(probability) - int(observed)) ** 2


def find_paradox_pairs(
    profiles: pd.DataFrame,
    *,
    limit: int = 12,
    maximum_frequency_gap: int = 2,
    minimum_probability_gap: float = 0.12,
) -> list[dict]:
    """Find distinct households matched on recency and approximate frequency.

    Uses *predictions*, not future outcome labels, to select examples. Results
    illustrate disagreement with simple R/F comparisons, not causal effects.
    """
    if limit < 1:
        return []

    required = {
        "household_key", "recency_days", "baskets_90d",
        "predicted_probability",
    }
    if not required.issubset(profiles.columns):
        raise ValueError(f"Missing paradox columns: {required - set(profiles.columns)}")

    candidates: list[dict] = []
    for recency, group in profiles.groupby("recency_days", sort=False):
        ordered = group.sort_values("baskets_90d")
        rows = ordered.to_dict("records")
        for i, left in enumerate(rows):
            for right in rows[i + 1:]:
                if (
                    right["baskets_90d"] - left["baskets_90d"]
                    > maximum_frequency_gap
                ):
                    break
                probability_gap = abs(
                    float(left["predicted_probability"])
                    - float(right["predicted_probability"])
                )
                if probability_gap >= minimum_probability_gap:
                    high, low = sorted(
                        (left, right),
                        key=lambda row: float(row["predicted_probability"]),
                        reverse=True,
                    )
                    candidates.append({
                        "high_household": str(high["household_key"]),
                        "low_household": str(low["household_key"]),
                        "high_probability": float(high["predicted_probability"]),
                        "low_probability": float(low["predicted_probability"]),
                        "probability_gap": probability_gap,
                        "recency_days": int(recency),
                        "high_baskets_90d": int(high["baskets_90d"]),
                        "low_baskets_90d": int(low["baskets_90d"]),
                    })

    candidates.sort(key=lambda row: row["probability_gap"], reverse=True)
    selected: list[dict] = []
    used: set[str] = set()
    for candidate in candidates:
        first = candidate["high_household"]
        second = candidate["low_household"]
        if first in used or second in used:
            continue
        selected.append(candidate)
        used.update((first, second))
        if len(selected) >= limit:
            break
    return selected
