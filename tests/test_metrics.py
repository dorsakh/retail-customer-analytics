import numpy as np
import pandas as pd
import pytest

from retail_analytics.metrics import evaluate, top_fraction_metrics


@pytest.fixture
def sample_data():
    return pd.DataFrame({
        "as_of_day": [180] * 5 + [210] * 5,
        "household_key": [f"h{i}" for i in range(10)],
        "recency_days": [1, 2, 3, 4, 5] * 2,
        "baskets_90d": [5, 4, 3, 2, 1] * 2,
        "repurchased_7d": [1, 0, 0, 0, 0] * 2,
    })


def test_top_fraction_selection_is_per_day(sample_data):
    scores = np.array([
        0.99, 0.95, 0.90, 0.80, 0.70,
        0.55, 0.50, 0.40, 0.30, 0.20,
    ])

    precision, lift = top_fraction_metrics(
        sample_data,
        scores=scores,
    )

    assert precision == pytest.approx(1.0)
    assert lift == pytest.approx(5.0)


def test_perfect_predictions(sample_data):
    probabilities = np.array([
        1, 0, 0, 0, 0,
        1, 0, 0, 0, 0,
    ])

    result = evaluate(
        "Perfect model",
        sample_data,
        probabilities=probabilities,
    )

    assert result["roc_auc"] == pytest.approx(1.0)
    assert result["avg_precision"] == pytest.approx(1.0)
    assert result["brier"] == pytest.approx(0.0)
    assert result["precision_at_20"] == pytest.approx(1.0)
    assert result["lift_at_20"] == pytest.approx(5.0)


def test_ranking_baseline_has_no_probability_metrics(sample_data):
    result = evaluate(
        "Recency only",
        sample_data,
    )

    assert np.isnan(result["roc_auc"])
    assert np.isnan(result["avg_precision"])
    assert np.isnan(result["brier"])


def test_lift_undefined_when_no_positive_labels(sample_data):
    no_purchase = sample_data.copy()
    no_purchase["repurchased_7d"] = 0

    precision, lift = top_fraction_metrics(
        no_purchase,
        use_frequency=True,
    )

    assert precision == 0.0
    assert np.isnan(lift)