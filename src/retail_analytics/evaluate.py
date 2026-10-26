import pandas as pd
from .models import make_lightgbm_model

from .data import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    load_data,
    split_by_time,
)

from .metrics import evaluate


def main() -> None:
    splits = split_by_time(load_data())

    development = pd.concat(
        [splits["train"], splits["validation"]],
        ignore_index=True,
    )

    test = splits["test"]

    model = make_lightgbm_model()

    model.fit(
        development[FEATURE_COLUMNS],
        development[TARGET_COLUMN],
    )

    probabilities = model.predict_proba(
        test[FEATURE_COLUMNS]
    )[:, 1]

    results = [
        evaluate(
            "Recency + frequency",
            test,
            use_frequency=True,
        ),
        evaluate(
            "LightGBM",
            test,
            probabilities=probabilities,
        ),
    ]

    print("\nHoldout test results")
    print(f"Training observations: {len(development):,}")
    print(f"Test observations: {len(test):,}")
    print(f"Test repurchase rate: {test[TARGET_COLUMN].mean():.2%}")

    print(
        pd.DataFrame(results)
        .round(3)
        .to_string(index=False)
    )

    print("\nPerformance by test day")

    for day in sorted(test["as_of_day"].unique()):
        mask = test["as_of_day"].eq(day).to_numpy()
        day_data = test.loc[mask]

        day_results = [
            evaluate(
                "Recency + frequency",
                day_data,
                use_frequency=True,
            ),
            evaluate(
                "LightGBM",
                day_data,
                probabilities=probabilities[mask],
            ),
        ]

        print(f"\nDay {int(day)}")
        print(
            pd.DataFrame(day_results)
            .round(3)
            .to_string(index=False)
        )

    importance = pd.DataFrame({
        "feature": FEATURE_COLUMNS,
        "gain": model.booster_.feature_importance(
            importance_type="gain"
        ),
        "split_count": model.booster_.feature_importance(
            importance_type="split"
        ),
    })

    importance["gain_share_pct"] = (
        100 * importance["gain"] / importance["gain"].sum()
    )

    importance = importance.sort_values(
        "gain",
        ascending=False,
    )

    print("\nFeature importance")
    print(
        importance[
            ["feature", "gain_share_pct", "split_count"]
        ]
        .round(2)
        .to_string(index=False)
    )

    scored = test.copy()
    scored["predicted_probability"] = probabilities

    scored["score_decile"] = (
        scored.groupby("as_of_day")["predicted_probability"]
        .transform(
            lambda scores: pd.qcut(
                scores.rank(method="first"),
                q=10,
                labels=False,
            ) + 1
        )
    )

    decile_summary = (
        scored.groupby("score_decile")
        .agg(
            observations=("household_key", "size"),
            avg_predicted_probability=(
                "predicted_probability", "mean"
            ),
            actual_repurchase_rate=(TARGET_COLUMN, "mean"),
            median_baskets_90d=("baskets_90d", "median"),
            median_recency_days=("recency_days", "median"),
        )
        .reset_index()
        .sort_values("score_decile", ascending=False)
    )

    print("\nCustomer propensity segments")
    print(
        decile_summary
        .round(3)
        .to_string(index=False)
    )

if __name__ == "__main__":
    main()