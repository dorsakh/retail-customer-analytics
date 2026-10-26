import os

import pandas as pd
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv(
    "RETAIL_DATABASE_URL",
    "postgresql+psycopg:///retail_analytics",
)

FEATURE_COLUMNS = [
    "recency_days",
    "baskets_90d",
    "baskets_30d",
    "baskets_previous_30d",
    "sales_90d",
    "sales_30d",
    "sales_previous_30d",
    "sales_growth_30d",
    "avg_basket_value_90d",
    "basket_value_volatility_90d",
    "avg_product_diversity_90d",
    "distinct_stores_90d",
    "discount_share_90d",
    "avg_days_between_visits_90d",
    "visit_interval_volatility_90d",
]

TARGET_COLUMN = "repurchased_7d"


def load_data() -> pd.DataFrame:
    query = text("""
        SELECT
            s.*,
            r.repurchased_7d
        FROM analytics.household_snapshots AS s
        LEFT JOIN analytics.repurchase_7d AS r
            ON s.household_key = r.household_key
            AND s.as_of_day = r.as_of_day
        ORDER BY
            s.as_of_day,
            s.household_key
    """)

    engine = create_engine(DATABASE_URL)

    try:
        with engine.connect() as connection:
            data = pd.read_sql_query(query, connection)
    finally:
        engine.dispose()

    if data.empty:
        raise ValueError("No household snapshots were returned.")

    keys = ["household_key", "as_of_day"]

    if data[keys].isna().any().any():
        raise ValueError("Missing household or observation-day keys.")

    if data.duplicated(keys).any():
        raise ValueError("Duplicate household snapshots detected.")

    if data[TARGET_COLUMN].isna().any():
        raise ValueError("Some snapshots have no repurchase label.")

    for column in FEATURE_COLUMNS:
        data[column] = pd.to_numeric(
            data[column],
            errors="raise",
        )

    data[TARGET_COLUMN] = data[TARGET_COLUMN].astype("int8")

    return data


def split_by_time(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    splits = {
        "train": data.loc[
            data["as_of_day"].between(180, 540)
        ].copy(),

        "validation": data.loc[
            data["as_of_day"].isin([570, 600])
        ].copy(),

        "test": data.loc[
            data["as_of_day"].isin([630, 660, 690])
        ].copy(),
    }

    for name, subset in splits.items():
        if subset.empty:
            raise ValueError(f"{name} split is empty.")

    total = sum(len(subset) for subset in splits.values())

    if total != len(data):
        raise ValueError("Some observations were not assigned to a split.")

    return splits


def main() -> None:
    data = load_data()
    splits = split_by_time(data)

    print(f"Total observations: {len(data):,}")
    print(f"Unique households: {data['household_key'].nunique():,}")
    print(f"Number of features: {len(FEATURE_COLUMNS)}")

    for name, subset in splits.items():
        print(f"\n{name.upper()}")
        print(f"Observations: {len(subset):,}")
        print(f"Unique households: {subset['household_key'].nunique():,}")
        print(f"Observation days: {sorted(subset['as_of_day'].unique())}")

        if name != "test":
            positive_rate = 100 * subset[TARGET_COLUMN].mean()
            print(f"Repurchase rate: {positive_rate:.2f}%")

    print("\nMissing feature values in training data:")

    missing = (
        splits["train"][FEATURE_COLUMNS]
        .isna()
        .sum()
    )

    print(missing[missing > 0].sort_values(ascending=False))

    if not (missing > 0).any():
        print("None")


if __name__ == "__main__":
    main()