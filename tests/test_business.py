import numpy as np
import pandas as pd
import pytest

from retail_analytics.business import household_bootstrap_curve, priority_curve
from retail_analytics.metrics import top_fraction_metrics


def example_holdout():
    # The baseline prioritizes recent baskets, but the model identifies the
    # deliberately less-recent future buyers.
    return pd.DataFrame({
        "as_of_day": [630] * 10 + [660] * 6,
        "household_key": [str(i) for i in range(10)]
                         + [str(i) for i in range(6)],
        "recency_days": list(range(10)) + list(range(6)),
        "baskets_90d": [1] * 16,
        "repurchased_7d": [0] * 5 + [1] * 5 + [0] * 3 + [1] * 3,
        "model_score": [i / 10 for i in range(10)]
                       + [i / 6 for i in range(6)],
    })


def test_capacity_rounded_within_each_observation_day():
    overall, per_day = priority_curve(example_holdout(), capacities=(0.20, 1.0))
    model = per_day.loc[
        (per_day["capacity_pct"] == 20) & (per_day["strategy"] == "model")
    ].sort_values("as_of_day")

    assert model["selected"].tolist() == [2, 2]
    assert model["purchasers_identified"].tolist() == [2, 2]
    assert overall.loc[0, "model_precision"] == 1.0
    assert overall.loc[0, "baseline_precision"] == 0.0
    assert overall.loc[0, "extra_purchasers_identified"] == 4

    full = overall.iloc[1]
    assert full["selected"] == 16
    assert full["extra_purchasers_identified"] == 0
    assert full["model_precision"] == full["baseline_precision"]


def test_at_20_matches_existing_holdout_metric_exactly():
    data = example_holdout()
    overall, _ = priority_curve(data, capacities=(0.20,))

    model_precision, model_lift = top_fraction_metrics(
        data, scores=data["model_score"]
    )
    baseline_precision, baseline_lift = top_fraction_metrics(
        data, use_frequency=True
    )

    assert overall.loc[0, "model_precision"] == pytest.approx(model_precision)
    assert overall.loc[0, "model_lift"] == pytest.approx(model_lift)
    assert overall.loc[0, "baseline_precision"] == pytest.approx(baseline_precision)
    assert overall.loc[0, "baseline_lift"] == pytest.approx(baseline_lift)


def test_household_cluster_bootstrap_reproducible():
    data = example_holdout()
    first = household_bootstrap_curve(
        data, capacities=(0.20, 1.0), n_bootstrap=25, random_state=19
    )
    second = household_bootstrap_curve(
        data, capacities=(0.20, 1.0), n_bootstrap=25, random_state=19
    )
    pd.testing.assert_frame_equal(first, second)
    assert (first["precision_gap_pp_ci_low"] <=
            first["precision_gap_pp_ci_high"]).all()
    assert np.allclose(first.loc[1, [
        "precision_gap_pp_ci_low", "precision_gap_pp_ci_high"
    ]].to_numpy(dtype=float), 0)


def test_bad_values_rejected():
    data = example_holdout()
    data.loc[0, "model_score"] = np.inf
    with pytest.raises(ValueError, match="finite"):
        priority_curve(data)

    with pytest.raises(ValueError, match="Capacities"):
        priority_curve(example_holdout(), capacities=(-0.2,))


def test_missing_baseline_history_is_allowed():
    data = example_holdout()
    data.loc[0, ["recency_days", "baskets_90d"]] = np.nan
    overall, _ = priority_curve(data, capacities=(0.20,))
    assert len(overall) == 1
    assert np.isfinite(overall.loc[0, "baseline_precision"])
