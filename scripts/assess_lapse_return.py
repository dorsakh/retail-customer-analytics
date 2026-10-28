"""Audit how often eligible 14-day lapsers purchase again after the lapse.

The follow-up window begins when the 14-day lapse becomes observable, not at
the prediction cutoff. All included observations must have the full 60-day
post-lapse follow-up available; a missing next basket is then a genuine
non-return within the observation window, not right censoring.

Run from the repository root with the existing PostgreSQL database and
prepared retention snapshots:

    python scripts/assess_lapse_return.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


LAST_DAY = 711
LAPSE_DAYS = 14
FOLLOW_UP_DAYS = 60
REPORT_PATH = Path(__file__).resolve().parents[1] / "reports/tables/retention_lapse_return.csv"


def select_lapsers(
    snapshots: pd.DataFrame,
    *,
    last_day: int = LAST_DAY,
    lapse_days: int = LAPSE_DAYS,
    follow_up_days: int = FOLLOW_UP_DAYS,
) -> pd.DataFrame:
    """Keep eligible, observed lapses with complete post-lapse follow-up."""
    if lapse_days <= 0 or follow_up_days <= 0:
        raise ValueError("Lapse and follow-up windows must be positive")
    required = {"household_key", "as_of_day", "segment", f"lapsed_{lapse_days}d"}
    if required - set(snapshots.columns):
        raise ValueError(f"Missing snapshot columns: {sorted(required - set(snapshots.columns))}")
    eligible = snapshots.loc[
        snapshots["segment"].eq("eligible")
        & snapshots[f"lapsed_{lapse_days}d"].eq(1)
        & snapshots["as_of_day"].le(last_day - lapse_days - follow_up_days),
        ["household_key", "as_of_day"],
    ].copy()
    if eligible.duplicated(["household_key", "as_of_day"]).any():
        raise ValueError("Duplicate household-date lapse observations")
    return eligible


def summarize_returns(
    observations: pd.DataFrame,
    *,
    last_day: int = LAST_DAY,
    lapse_days: int = LAPSE_DAYS,
    follow_up_days: int = FOLLOW_UP_DAYS,
) -> pd.DataFrame:
    """Summarize first next purchases; missing dates mean no observed return."""
    if observations.empty:
        raise ValueError("No fully observed 14-day lapsers to summarize")
    if (observations["as_of_day"] + lapse_days + follow_up_days > last_day).any():
        raise ValueError("Some observations lack complete post-lapse follow-up")
    elapsed = observations["next_day"] - observations["as_of_day"] - lapse_days
    if elapsed.dropna().le(0).any():
        raise ValueError("A 14-day lapser cannot repurchase during the lapse window")
    returned_30 = elapsed.between(1, 30, inclusive="both")
    returned_60 = elapsed.between(1, follow_up_days, inclusive="both")
    observed_return = elapsed.loc[returned_60]
    return pd.DataFrame([{
        "lapse_days": lapse_days,
        "follow_up_days_after_lapse": follow_up_days,
        "last_observed_day": last_day,
        "latest_included_as_of_day": int(observations["as_of_day"].max()),
        "lapse_observations": int(len(observations)),
        "distinct_households": int(observations["household_key"].nunique()),
        "returned_within_30d_after_lapse": float(returned_30.mean()),
        "returned_within_60d_after_lapse": float(returned_60.mean()),
        "not_returned_within_60d_after_lapse": float((~returned_60).mean()),
        "not_returned_by_last_day": float(observations["next_day"].isna().mean()),
        "median_days_after_lapse_to_return_within_60d": (
            float(observed_return.median()) if not observed_return.empty else np.nan
        ),
    }])


def main() -> None:
    from sqlalchemy import create_engine, text

    from retail_analytics.data import DATABASE_URL
    from retail_analytics.retention_data import read_snapshots

    engine = create_engine(DATABASE_URL)
    parts = []
    try:
        with engine.connect() as connection:
            max_day = connection.execute(
                text("SELECT MAX(day) FROM analytics.baskets")
            ).scalar_one()
            if max_day is None:
                raise ValueError("analytics.baskets contains no purchase dates")
            last_day = min(LAST_DAY, int(max_day))
            lapsers = select_lapsers(read_snapshots(), last_day=last_day)
            if lapsers.empty:
                raise ValueError("No eligible lapsers have 60 complete post-lapse days")
            for as_of_day, group in lapsers.groupby("as_of_day", sort=True):
                next_baskets = pd.read_sql_query(
                    text("""
                        SELECT household_key, MIN(day) AS next_day
                        FROM analytics.baskets
                        WHERE day > :lapse_end AND day <= :last_day
                        GROUP BY household_key
                    """),
                    connection,
                    params={
                        "lapse_end": int(as_of_day) + LAPSE_DAYS,
                        "last_day": last_day,
                    },
                )
                parts.append(group.merge(next_baskets, on="household_key", how="left", validate="many_to_one"))
    finally:
        engine.dispose()

    result = summarize_returns(pd.concat(parts, ignore_index=True), last_day=last_day)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(REPORT_PATH, index=False)
    print(result.round(3).to_string(index=False))
    print(f"Saved {REPORT_PATH}")
    print("Rates refer to household-date lapse observations, not causal treatment effects.")


if __name__ == "__main__":
    main()
