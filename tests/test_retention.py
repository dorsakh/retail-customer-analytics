"""Contract and leakage tests for the independent lapse-v2 extension."""

import numpy as np
import pandas as pd
import pytest

from retail_analytics.retention import make_scoring_records
from retail_analytics.retention_analysis import (
    bootstrap_model_differences,
    choose_horizon,
    run_evaluation,
    scenario_table,
    top_capacity_stats,
)
from retail_analytics.retention_data import (
    ALL_FAMILIES, FEATURE_FAMILIES, HORIZONS,
    add_derived_features, classify_cohort, features_frame, partition,
)


def rows():
    data = pd.DataFrame({
        "as_of_day": [711] * 5,
        "household_key": ["1", "2", "3", "4", "5"],
        "recency_days": [3, 15, 31, 90, 120],
        "baskets_90d": [6, 2, 7, 0, 0],
        "sales_prev_30d": [10.0, 0.0, 0.0, 0.0, 0.0],
        "sales_30d": [15.0, 0.0, 10.0, 0.0, 0.0],
    })
    for family in FEATURE_FAMILIES.values():
        for name in family:
            if name not in data and name not in {
                "week_sin", "week_cos", "year_sin", "year_cos", "sales_change_ratio"
            }:
                data[name] = "45-54" if name in {"age_desc", "income_desc", "household_size_desc"} else 2.0
    return add_derived_features(data)


def test_all_known_households_get_a_lifecycle_class():
    classified = classify_cohort(rows())
    assert classified.tolist() == [
        "eligible", "limited_history", "inactive", "dormant", "dormant"
    ]


def test_feature_columns_retain_training_contract_at_inference():
    source = rows()
    training = features_frame(source, ALL_FAMILIES)
    new = source.copy()
    new.loc[0, "income_desc"] = "new category"
    scored = features_frame(new, ALL_FAMILIES, columns=training.columns.tolist())
    assert scored.columns.tolist() == training.columns.tolist()
    assert not np.isinf(scored.to_numpy()).any()
    assert np.isnan(scored["sales_change_ratio"].iloc[1])


def test_temporal_partitions_keep_28_day_targets_matured():
    source = pd.concat([
        rows().assign(as_of_day=day)
        for day in range(180, 661, 30)
    ], ignore_index=True)
    source["segment"] = classify_cohort(source)
    splits = partition(source)
    assert max(splits["train"]["as_of_day"]) == 510
    assert set(splits["validation"]["as_of_day"]) == {540, 570}
    assert set(splits["holdout"]["as_of_day"]) == {600, 630, 660}
    assert 510 + max(HORIZONS) < 540
    assert 570 + max(HORIZONS) < 600


def test_bootstrap_keeps_household_observation_clusters():
    data = pd.DataFrame({
        "household_key": ["a", "b", "c", "d"] * 2,
        "as_of_day": [600] * 4 + [630] * 4,
        "target": [1, 0, 1, 0, 0, 1, 1, 0],
    })
    reference = np.array([.1, .9, .2, .8, .7, .2, .1, .9])
    better = 1 - reference
    results = bootstrap_model_differences(
        data, {"LR": reference, "LightGBM": better},
        reference="LR", replicates=25, seed=4,
    )
    assert len(results) == 1
    assert results.loc[0, "bootstrap_households"] == 4
    assert results.loc[0, "precision_gap_pp"] > 0
    assert top_capacity_stats(data, better)["selected"] == 2


def test_horizon_rule_never_reads_holdout():
    candidates = [
        {"horizon_days": 7, "lapse_rate": .55, "lift_at_capacity": 1.3},
        {"horizon_days": 14, "lapse_rate": .27, "lift_at_capacity": 1.6},
        {"horizon_days": 28, "lapse_rate": .03, "lift_at_capacity": 4.0},
    ]
    assert choose_horizon(candidates) == 14


def test_economics_are_explicitly_assumed_not_observed_roi():
    data = pd.DataFrame({
        "as_of_day": [600] * 5,
        "household_key": list("abcde"),
        "target": [1, 1, 0, 1, 0],
    })
    report = scenario_table(data, [.9, .8, .7, .6, .5], gross_margin=10, offer_cost=2)
    assert report["break_even_incremental_response"].eq(.2).all()
    assert report["note"].str.contains("not an estimated treatment effect").all()
    with pytest.raises(ValueError):
        scenario_table(data, [.9] * 5, gross_margin=-1)


class FakeModel:
    def predict_proba(self, x):
        return np.column_stack([np.full(len(x), .25), np.full(len(x), .75)])


def test_scoring_returns_dormant_and_unmodeled_profiles():
    source = rows()
    columns = features_frame(source.iloc[[0]], ALL_FAMILIES).columns.tolist()
    records = make_scoring_records(source, FakeModel(), {
        "version": "lapse_v2", "horizon_days": 14,
        "feature_families": list(ALL_FAMILIES), "feature_columns": columns,
    })
    assert len(records) == 5
    assert records[0]["segment"] == "at_risk"
    assert records[0]["lapse_probability"] == pytest.approx(.75)
    assert records[3]["segment"] == "dormant"
    assert records[3]["lapse_probability"] is None


def test_all_horizon_evaluation_runs_on_synthetic_contract(tmp_path, monkeypatch):
    import retail_analytics.retention_analysis as research

    monkeypatch.setattr(research, "REPORTS", tmp_path)
    template = rows().iloc[0].to_dict()
    synthetic = []
    for day in range(180, 661, 30):
        for household in range(35):
            row = dict(template)
            row.update({
                "household_key": str(household),
                "as_of_day": day,
                "recency_days": 2 + household % 16,
                "baskets_90d": 4 + household % 10,
                "overdue_ratio": 0.3 + household % 8 / 2,
                "lapsed_7d": int((household + day // 30) % 3 == 0),
                "lapsed_14d": int((household + day // 30) % 4 == 0),
                "lapsed_28d": int((household + day // 30) % 6 == 0),
            })
            synthetic.append(row)
    data = pd.DataFrame(synthetic)
    data["segment"] = classify_cohort(data)
    result = run_evaluation(data, bootstraps=8)
    assert result["selected_horizon_days"] in HORIZONS
    assert result["holdout_days"] == [600, 630, 660]
    assert (tmp_path / "retention_holdout.csv").exists()
    assert (tmp_path / "retention_holdout_by_date.csv").exists()
    assert (tmp_path / "retention_profit_scenarios.csv").exists()
