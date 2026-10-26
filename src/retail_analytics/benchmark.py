from pathlib import Path
from time import perf_counter

import pandas as pd
from sklearn.base import clone

from .data import FEATURE_COLUMNS, TARGET_COLUMN, load_data, split_by_time
from .metrics import evaluate
from .models import (
    make_logistic_model,
    make_lightgbm_model,
    make_xgboost_model,
    make_hist_gradient_boosting_model,
)


ROLLING_FOLDS = [
    (300, [330, 360]),
    (360, [390, 420]),
    (420, [450, 480]),
    (480, [510, 540]),
]

MODELS = {
    "Logistic regression": make_logistic_model(),
    "LightGBM": make_lightgbm_model(),
    "XGBoost": make_xgboost_model(),
    "HistGradientBoosting": make_hist_gradient_boosting_model(),
}

REPORT_DIR = (
    Path(__file__).resolve().parents[2]
    / "reports"
    / "tables"
)


def compare_models(
    train: pd.DataFrame,
    validation: pd.DataFrame,
) -> pd.DataFrame:

    results = [
        evaluate(
            "Recency + frequency",
            validation,
            use_frequency=True,
        )
    ]

    results[0]["fit_seconds"] = None

    for name, estimator in MODELS.items():
        model = clone(estimator)

        start = perf_counter()

        model.fit(
            train[FEATURE_COLUMNS],
            train[TARGET_COLUMN],
        )

        fit_seconds = perf_counter() - start

        probabilities = model.predict_proba(
            validation[FEATURE_COLUMNS]
        )[:, 1]

        result = evaluate(
            name,
            validation,
            probabilities=probabilities,
        )

        result["fit_seconds"] = fit_seconds
        results.append(result)

    return pd.DataFrame(results)


def main() -> None:
    splits = split_by_time(load_data())

    train = splits["train"]
    validation = splits["validation"]

    # Standard validation benchmark
    validation_results = compare_models(
        train,
        validation,
    )

    print("\nValidation benchmark")
    print(
        validation_results
        .round(3)
        .to_string(index=False)
    )

    # Rolling-origin benchmark
    fold_results = []

    for train_end_day, validation_days in ROLLING_FOLDS:

        fold_train = train.loc[
            train["as_of_day"] <= train_end_day
        ]

        fold_validation = train.loc[
            train["as_of_day"].isin(validation_days)
        ]

        report = compare_models(
            fold_train,
            fold_validation,
        )

        report.insert(
            0,
            "train_end_day",
            train_end_day,
        )

        report.insert(
            1,
            "validation_days",
            str(validation_days),
        )

        fold_results.append(report)

    backtest = pd.concat(
        fold_results,
        ignore_index=True,
    )

    print("\nRolling-origin benchmark")
    print(
        backtest
        .round(3)
        .to_string(index=False)
    )

    # Summary across rolling-origin folds
    summary = (
        backtest.groupby("model")
        .agg(
            mean_roc_auc=("roc_auc", "mean"),
            mean_avg_precision=("avg_precision", "mean"),
            mean_brier=("brier", "mean"),
            mean_precision_at_20=("precision_at_20", "mean"),
            std_precision_at_20=("precision_at_20", "std"),
            mean_fit_seconds=("fit_seconds", "mean"),
        )
        .sort_values(
            "mean_precision_at_20",
            ascending=False,
        )
    )

    print("\nRolling-origin summary")
    print(
        summary
        .round(3)
        .to_string()
    )

    # Save reproducible benchmark outputs
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    validation_results.to_csv(
        REPORT_DIR / "model_comparison_validation.csv",
        index=False,
    )

    backtest.to_csv(
        REPORT_DIR / "rolling_origin_folds.csv",
        index=False,
    )

    summary.reset_index().to_csv(
        REPORT_DIR / "rolling_origin_summary.csv",
        index=False,
    )

    print(f"\nBenchmark results saved to: {REPORT_DIR}")
    print("Test data was not used in this benchmark.")


if __name__ == "__main__":
    main()