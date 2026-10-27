from pathlib import Path

import pandas as pd
from sklearn.calibration import calibration_curve

from .uncertainty import household_bootstrap_precision

from .data import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    load_data,
    split_by_time,
)
from .metrics import evaluate
from .models import make_lightgbm_model


REPORT_DIR = (
    Path(__file__).resolve().parents[2]
    / "reports"
    / "tables"
)


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

    # Overall holdout performance
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

    holdout_results = pd.DataFrame(results)

    print("\nHoldout test results")
    print(f"Training observations: {len(development):,}")
    print(f"Test observations: {len(test):,}")
    print(f"Test repurchase rate: {test[TARGET_COLUMN].mean():.2%}")

    print(
        holdout_results
        .round(3)
        .to_string(index=False)
    )

    # Performance by observation day
    print("\nPerformance by test day")

    day_records = []

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

        for result in day_results:
            day_records.append({
                "as_of_day": int(day),
                **result,
            })

        print(f"\nDay {int(day)}")
        print(
            pd.DataFrame(day_results)
            .round(3)
            .to_string(index=False)
        )

    day_report = pd.DataFrame(day_records)

    # Feature importance
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

    # Customer propensity segments
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

    # Holdout probability calibration
    observed_rate, predicted_probability = calibration_curve(
        test[TARGET_COLUMN],
        probabilities,
        n_bins=10,
        strategy="quantile",
    )

    calibration_table = pd.DataFrame({
        "predicted_probability": predicted_probability,
        "observed_rate": observed_rate,
    })

    print("\nHoldout probability calibration")
    print(
        calibration_table
        .round(3)
        .to_string(index=False)
    )

    # Save aggregate evaluation results
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    holdout_results.to_csv(
        REPORT_DIR / "holdout_metrics.csv",
        index=False,
    )

    day_report.to_csv(
        REPORT_DIR / "holdout_by_day.csv",
        index=False,
    )

    importance.to_csv(
        REPORT_DIR / "holdout_feature_importance.csv",
        index=False,
    )

    decile_summary.to_csv(
        REPORT_DIR / "holdout_propensity_deciles.csv",
        index=False,
    )

    calibration_table.to_csv(
        REPORT_DIR / "holdout_calibration.csv",
        index=False,
    )

    # Export ranked household scores for the latest holdout day
    latest_day = scored["as_of_day"].max()

    latest_scores = (
        scored.loc[
            scored["as_of_day"].eq(latest_day),
            [
                "household_key",
                "as_of_day",
                "predicted_probability",
                "score_decile",
            ],
        ]
        .sort_values(
            "predicted_probability",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    latest_scores.insert(
        0,
        "rank",
        range(1, len(latest_scores) + 1),
    )

    latest_scores.to_csv(
        REPORT_DIR / "holdout_latest_day_scores.csv",
        index=False,
    )

    # Household-cluster bootstrap uncertainty
    uncertainty_report = household_bootstrap_precision(
        test,
        probabilities,
        n_bootstrap=1000,
        random_state=42,
    )

    print("\nHoldout uncertainty: 95% household-cluster bootstrap")
    print(
        uncertainty_report[
            [
                "metric",
                "estimate",
                "ci_lower_95",
                "ci_upper_95",
            ]
        ]
        .round(3)
        .to_string(index=False)
    )

    uncertainty_report.to_csv(
        REPORT_DIR / "holdout_uncertainty.csv",
        index=False,
    )

    print(f"\nHoldout results saved to: {REPORT_DIR}")


if __name__ == "__main__":
    main()