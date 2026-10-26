from pathlib import Path

import pandas as pd


DATA_PATH = Path("data/raw/complete_journey/transaction_data.csv")
LOOKBACK_DAYS = 90
PREDICTION_HORIZONS = (7, 14, 30)
CUTOFF_DAYS = (180, 360, 540)


def main():
    transactions = pd.read_csv(
        DATA_PATH,
        usecols=["household_key", "BASKET_ID", "DAY"],
    )

    baskets = transactions.drop_duplicates(
        subset=["household_key", "BASKET_ID"]
    ).dropna()

    print(f"Transaction rows: {len(transactions):,}")
    print(f"Unique baskets: {len(baskets):,}")
    print(f"Unique households: {baskets['household_key'].nunique():,}")
    print(
        f"Day range: {baskets['DAY'].min()} "
        f"to {baskets['DAY'].max()}"
    )

    purchases_per_household = baskets.groupby(
        "household_key"
    )["BASKET_ID"].nunique()

    print(
        "Households with at least two baskets:",
        f"{purchases_per_household.ge(2).sum():,}",
    )

    for cutoff in CUTOFF_DAYS:
        if cutoff + max(PREDICTION_HORIZONS) > baskets["DAY"].max():
            continue

        historical = baskets[
            (baskets["DAY"] > cutoff - LOOKBACK_DAYS)
            & (baskets["DAY"] <= cutoff)
        ]

        eligible_households = set(historical["household_key"])

        print(f"\nPrediction cutoff: Day {cutoff}")
        print(f"Eligible households: {len(eligible_households):,}")

        if not eligible_households:
            continue

        for horizon in PREDICTION_HORIZONS:
            future = baskets[
                (baskets["DAY"] > cutoff)
                & (baskets["DAY"] <= cutoff + horizon)
            ]

            returning_households = set(future["household_key"])
            positive_count = len(
                eligible_households & returning_households
            )

            positive_rate = positive_count / len(eligible_households)

            print(
                f"Repurchase within {horizon:2d} days: "
                f"{positive_count:,} households "
                f"({positive_rate:.1%})"
            )


if __name__ == "__main__":
    main()