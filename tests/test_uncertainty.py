import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from retail_analytics.metrics import top_fraction_metrics
from retail_analytics.uncertainty import (
    household_bootstrap_precision,
)


@pytest.fixture
def sample_data():
    return pd.DataFrame({
        "as_of_day": [630] * 10 + [660] * 10,
        "household_key": [f"h{i}" for i in range(10)] * 2,
        "recency_days": list(range(1, 11)) * 2,
        "baskets_90d": list(range(10, 0, -1)) * 2,
        "repurchased_7d": [1, 1] + [0] * 8
                           + [1, 1] + [0] * 8,
    })


def test_bootstrap_is_reproducible(sample_data):
    probabilities = np.array(
        [0.9, 0.8, 0.7, 0.6, 0.5,
         0.4, 0.3, 0.2, 0.1, 0.05] * 2
    )

    first = household_bootstrap_precision(
        sample_data,
        probabilities,
        n_bootstrap=50,
        random_state=42,
    )

    second = household_bootstrap_precision(
        sample_data,
        probabilities,
        n_bootstrap=50,
        random_state=42,
    )

    pdt.assert_frame_equal(first, second)


def test_bootstrap_point_estimates_match_metrics(sample_data):
    probabilities = np.array(
        [0.9, 0.8, 0.7, 0.6, 0.5,
         0.4, 0.3, 0.2, 0.1, 0.05] * 2
    )

    report = household_bootstrap_precision(
        sample_data,
        probabilities,
        n_bootstrap=50,
        random_state=42,
    )

    baseline, _ = top_fraction_metrics(
        sample_data,
        use_frequency=True,
    )

    model, _ = top_fraction_metrics(
        sample_data,
        scores=probabilities,
    )

    estimates = report.set_index("metric")["estimate"]

    assert estimates["baseline_precision_at_20"] == pytest.approx(
        baseline
    )

    assert estimates["lightgbm_precision_at_20"] == pytest.approx(
        model
    )

    assert estimates["precision_gain_at_20"] == pytest.approx(
        model - baseline
    )