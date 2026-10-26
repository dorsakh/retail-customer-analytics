import pandas as pd
from sklearn.base import clone
from sklearn.calibration import calibration_curve

from .data import FEATURE_COLUMNS, TARGET_COLUMN, load_data, split_by_time
from .metrics import evaluate
from .models import make_logistic_model, make_lightgbm_model


TOP_FRACTION = 0.20
RANDOM_STATE = 42


def main() -> None:
    data = load_data()
    splits = split_by_time(data)

    train = splits["train"]
    validation = splits["validation"]

    X_train = train[FEATURE_COLUMNS]
    y_train = train[TARGET_COLUMN]

    X_validation = validation[FEATURE_COLUMNS]

    results = []

    results.append(
        evaluate(
            "Recency only",
            validation,
        )
    )

    results.append(
        evaluate(
            "Recency + frequency",
            validation,
            use_frequency=True,
        )
    )

    logistic_model = make_logistic_model()

    logistic_model.fit(X_train, y_train)

    logistic_probabilities = (
        logistic_model.predict_proba(X_validation)[:, 1]
    )

    results.append(
        evaluate(
            "Logistic regression",
            validation,
            probabilities=logistic_probabilities,
        )
    )

    lightgbm_model = make_lightgbm_model()

    lightgbm_model.fit(X_train, y_train)

    lightgbm_probabilities = (
        lightgbm_model.predict_proba(X_validation)[:, 1]
    )

    results.append(
        evaluate(
            "LightGBM",
            validation,
            probabilities=lightgbm_probabilities,
        )
    )

    report = pd.DataFrame(results)

    print("\nValidation results")
    print(report.round(3).to_string(index=False))

    # Evaluate each validation cutoff separately.

    print("\nPerformance by validation day")

    for day in sorted(validation["as_of_day"].unique()):

        mask = validation["as_of_day"].eq(day).to_numpy()
        day_data = validation.loc[mask]

        day_results = [
            evaluate(
                "Recency + frequency",
                day_data,
                use_frequency=True,
            ),
            evaluate(
                "Logistic regression",
                day_data,
                probabilities=logistic_probabilities[mask],
            ),
            evaluate(
                "LightGBM",
                day_data,
                probabilities=lightgbm_probabilities[mask],
            ),
        ]

        print(f"\nDay {int(day)}")
        print(
            pd.DataFrame(day_results)
            .round(3)
            .to_string(index=False)
        )

    # Compare predicted probabilities with observed event rates.

    print("\nProbability calibration")

    for model_name, probabilities in [
        ("Logistic regression", logistic_probabilities),
        ("LightGBM", lightgbm_probabilities),
    ]:

        observed_rate, predicted_probability = calibration_curve(
            validation[TARGET_COLUMN],
            probabilities,
            n_bins=10,
            strategy="quantile",
        )

        calibration_table = pd.DataFrame({
            "predicted_probability": predicted_probability,
            "observed_rate": observed_rate,
        })

        print(f"\n{model_name}")
        print(
            calibration_table
            .round(3)
            .to_string(index=False)
        )

    print("\nRolling-origin validation")

    rolling_folds = [
        (300, [330, 360]),
        (360, [390, 420]),
        (420, [450, 480]),
        (480, [510, 540]),
    ]

    backtest_results = []

    for train_end_day, validation_days in rolling_folds:

        fold_train = train.loc[
            train["as_of_day"] <= train_end_day
        ]

        fold_validation = train.loc[
            train["as_of_day"].isin(validation_days)
        ]

        baseline_result = evaluate(
            "Recency + frequency",
            fold_validation,
            use_frequency=True,
        )

        baseline_result["train_end_day"] = train_end_day
        baseline_result["validation_days"] = str(validation_days)

        backtest_results.append(baseline_result)

        for model_name, fitted_model in [
            ("Logistic regression", logistic_model),
            ("LightGBM", lightgbm_model),
        ]:

            # Clone creates a fresh, unfitted estimator.
            fold_model = clone(fitted_model)

            fold_model.fit(
                fold_train[FEATURE_COLUMNS],
                fold_train[TARGET_COLUMN],
            )

            probabilities = fold_model.predict_proba(
                fold_validation[FEATURE_COLUMNS]
            )[:, 1]

            fold_result = evaluate(
                model_name,
                fold_validation,
                probabilities=probabilities,
            )

            fold_result["train_end_day"] = train_end_day
            fold_result["validation_days"] = str(validation_days)

            backtest_results.append(fold_result)

    backtest_report = pd.DataFrame(backtest_results)

    columns = [
        "train_end_day",
        "validation_days",
        "model",
        "roc_auc",
        "avg_precision",
        "brier",
        "precision_at_20",
        "lift_at_20",
    ]

    print(
        backtest_report[columns]
        .round(3)
        .to_string(index=False)
    )
    print("\nTest set remains reserved for final evaluation.")


if __name__ == "__main__":
    main()