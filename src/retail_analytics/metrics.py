import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

from .data import TARGET_COLUMN


TOP_FRACTION = 0.20

def top_fraction_metrics(
    data: pd.DataFrame,
    scores=None,
    use_frequency: bool = False,
) -> tuple[float, float]:

    ranked = data[
        [
            "as_of_day",
            "household_key",
            "recency_days",
            "baskets_90d",
            TARGET_COLUMN,
        ]
    ].copy()

    if scores is not None:
        ranked["model_score"] = np.asarray(scores)

        ranked = ranked.sort_values(
            ["as_of_day", "model_score", "household_key"],
            ascending=[True, False, True],
            kind="mergesort",
        )

    elif use_frequency:
        ranked = ranked.sort_values(
            [
                "as_of_day",
                "recency_days",
                "baskets_90d",
                "household_key",
            ],
            ascending=[True, True, False, True],
            kind="mergesort",
        )

    else:
        ranked = ranked.sort_values(
            ["as_of_day", "recency_days", "household_key"],
            ascending=[True, True, True],
            kind="mergesort",
        )

    group_sizes = ranked.groupby("as_of_day")[
        "household_key"
    ].transform("size")

    selection_limits = np.ceil(
        group_sizes * TOP_FRACTION
    )

    positions = (
        ranked.groupby("as_of_day").cumcount() + 1
    )

    selected = ranked.loc[
        positions <= selection_limits
    ]

    precision = selected[TARGET_COLUMN].mean()
    baseline_rate = data[TARGET_COLUMN].mean()

    if baseline_rate > 0:
        lift = precision / baseline_rate
    else:
        lift = np.nan

    return float(precision), float(lift)

def evaluate(
    name: str,
    data: pd.DataFrame,
    probabilities=None,
    use_frequency: bool = False,
) -> dict:

    precision, lift = top_fraction_metrics(
        data,
        scores=probabilities,
        use_frequency=use_frequency,
    )

    result = {
        "model": name,
        "roc_auc": np.nan,
        "avg_precision": np.nan,
        "brier": np.nan,
        "precision_at_20": precision,
        "lift_at_20": lift,
    }

    if probabilities is not None:
        y_true = data[TARGET_COLUMN]

        result["roc_auc"] = roc_auc_score(
            y_true,
            probabilities,
        )

        result["avg_precision"] = average_precision_score(
            y_true,
            probabilities,
        )

        result["brier"] = brier_score_loss(
            y_true,
            probabilities,
        )

    return result