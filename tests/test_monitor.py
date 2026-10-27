import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import retail_analytics.api as api
import retail_analytics.monitor as monitor
import retail_analytics.scheduler as scheduler
from retail_analytics.data import FEATURE_COLUMNS


def test_psi_is_zero_for_unchanged_constant_data():
    values = [3] * 50
    assert monitor.population_stability_index(values, values) == pytest.approx(0)


def test_psi_detects_shift_even_with_constant_reference():
    reference = [3] * 100
    current = [9] * 100
    assert monitor.population_stability_index(reference, current) > 0.2


def test_psi_detects_missingness_shift():
    reference = [1.0] * 100
    current = [1.0] * 50 + [np.nan] * 50
    assert monitor.population_stability_index(reference, current) > 0.2


def test_feature_report_flags_drift_without_changing_inputs():
    reference = pd.DataFrame({name: [1.0] * 100 for name in FEATURE_COLUMNS})
    current = reference.copy()
    current["baskets_90d"] = 20.0
    result = monitor.feature_drift_report(reference, current)
    flagged = {row["feature"] for row in result if row["warning"]}
    assert "baskets_90d" in flagged
    assert "recency_days" not in flagged
    assert len(result) == len(FEATURE_COLUMNS)


def test_outcome_metrics_are_correct_for_perfect_ranking():
    result = monitor.evaluate_matured_predictions(
        [0.9, 0.8, 0.1, 0.2],
        [1, 1, 0, 0],
    )
    assert result["brier"] == pytest.approx(0.025)
    assert result["roc_auc"] == pytest.approx(1.0)
    assert result["precision_at_20"] == pytest.approx(1.0)
    assert result["lift_at_20"] == pytest.approx(2.0)


def test_single_class_does_not_fabricate_roc_auc():
    result = monitor.evaluate_matured_predictions([0.8, 0.4], [1, 1])
    assert result["roc_auc"] is None


def test_future_outcome_is_not_reported_early():
    state, metrics = monitor._outcomes_if_mature(
        None, day=711, version="v1", source_max_day=711, training_last_day=690,
    )
    assert state == "pending"
    assert metrics is None


def test_training_period_is_not_reported_as_held_out():
    state, metrics = monitor._outcomes_if_mature(
        None, day=690, version="v1", source_max_day=711, training_last_day=690,
    )
    assert state == "not_applicable_training_period"
    assert metrics is None


def test_monitoring_api_shows_aggregate_results(monkeypatch):
    monkeypatch.setattr(
        api, "fetch_rows",
        lambda _query, _params: [{"as_of_day": 711, "label_status": "pending"}],
    )
    with TestClient(api.app) as client:
        response = client.get("/monitoring/latest")
    assert response.status_code == 200
    assert response.json()["label_status"] == "pending"


def test_scheduler_monitors_even_when_scoring_is_skipped(monkeypatch):
    monitored = []
    monkeypatch.setattr(
        scheduler, "run_once",
        lambda **_options: {"status": "skipped", "as_of_day": 711},
    )
    monkeypatch.setattr(
        scheduler, "run_monitor",
        lambda **kwargs: monitored.append(kwargs) or {"drift_status": "ok"},
    )
    monkeypatch.setattr(scheduler, "monotonic", lambda: 0)

    def stop(_seconds):
        raise SystemExit

    monkeypatch.setattr(scheduler, "sleep", stop)
    with pytest.raises(SystemExit):
        scheduler.serve(interval_hours=24)
    assert monitored == [{"as_of_day": 711}]
