import subprocess

import numpy as np
import pandas as pd
import pytest

import retail_analytics.pipeline as pipeline
from retail_analytics.data import FEATURE_COLUMNS


def sample_features():
    rows = pd.DataFrame({name: [1.0, 2.0] for name in FEATURE_COLUMNS})
    rows["household_key"] = ["101", "102"]
    rows["as_of_day"] = 711
    rows["recency_days"] = [3, 40]
    rows["baskets_90d"] = [4, 5]
    rows["baskets_30d"] = [1, 2]
    rows["baskets_previous_30d"] = [1, 1]
    rows["visit_interval_volatility_90d"] = [np.nan, 3.0]
    return rows


def test_validates_feature_consistency_without_rejecting_missing_volatility():
    frame = sample_features()
    assert pipeline.validate_batch(frame, 711) == 2
    frame.loc[0, "baskets_30d"] = 5
    with pytest.raises(ValueError, match="exceed"):
        pipeline.validate_batch(frame, 711)


def test_rejects_duplicate_households_and_infinite_inputs():
    frame = sample_features()
    frame.loc[1, "household_key"] = "101"
    with pytest.raises(ValueError, match="unique"):
        pipeline.validate_batch(frame, 711)
    frame = sample_features()
    frame.loc[1, "sales_90d"] = np.inf
    with pytest.raises(ValueError, match="Infinite"):
        pipeline.validate_batch(frame, 711)


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, statement, _params=None):
        query = str(statement)
        if "MAX(day)" in query:
            return FakeResult(711)
        if "pg_try_advisory_lock" in query or "pg_advisory_unlock" in query:
            return FakeResult(True)
        if "COUNT(*)" in query:
            return FakeResult(2)
        raise AssertionError(f"Unexpected SQL in test: {query}")

    def commit(self):
        pass


class FakeEngine:
    def __init__(self):
        self.disposed = False

    def connect(self):
        return FakeConnection()

    def dispose(self):
        self.disposed = True


@pytest.fixture
def prepared_pipeline(monkeypatch):
    engine = FakeEngine()
    changes = []
    commands = []
    monkeypatch.setattr(pipeline, "create_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(
        pipeline, "load_saved_model",
        lambda: (object(), {"model_version": "v1", "model_sha256": "abc"}),
    )
    monkeypatch.setattr(pipeline, "load_scoring_features", lambda _day: sample_features())
    monkeypatch.setattr(pipeline, "_initialize_runs", lambda _engine: None)
    monkeypatch.setattr(pipeline, "_already_completed", lambda *_a, **_k: None)
    monkeypatch.setattr(
        pipeline, "_save_run",
        lambda *_a, **k: changes.append(("insert", k["status"])),
    )
    monkeypatch.setattr(
        pipeline, "_finish_run",
        lambda *_a, **k: changes.append(("finish", k["status"])),
    )
    monkeypatch.setattr(
        pipeline.subprocess, "run",
        lambda command, check: commands.append((command, check)),
    )
    return engine, changes, commands


def test_pipeline_scores_and_records_success(prepared_pipeline):
    engine, changes, commands = prepared_pipeline
    output = pipeline.run_once()
    assert output["status"] == "succeeded"
    assert output["scored_rows"] == 2
    assert changes == [("insert", "running"), ("finish", "succeeded")]
    assert commands[0][0][-2:] == ["--as-of-day", "711"]
    assert commands[0][1] is True
    assert engine.disposed


def test_pipeline_skip_avoids_redundant_scoring(monkeypatch, prepared_pipeline):
    _, changes, commands = prepared_pipeline
    monkeypatch.setattr(pipeline, "_already_completed", lambda *_a, **_k: 2)
    result = pipeline.run_once()
    assert result["status"] == "skipped"
    assert changes == [("insert", "skipped")]
    assert commands == []


def test_pipeline_failure_is_recorded(monkeypatch, prepared_pipeline):
    _, changes, _ = prepared_pipeline

    def fail_command(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "scorer")

    monkeypatch.setattr(pipeline.subprocess, "run", fail_command)
    with pytest.raises(subprocess.CalledProcessError):
        pipeline.run_once()
    assert changes == [("insert", "running"), ("finish", "failed")]


def test_dry_run_has_no_writes(prepared_pipeline):
    _, changes, commands = prepared_pipeline
    result = pipeline.run_once(dry_run=True)
    assert result["status"] == "dry_run"
    assert changes == []
    assert commands == []


def test_pipeline_history_api_excludes_internal_error_details(monkeypatch):
    from fastapi.testclient import TestClient

    import retail_analytics.api as api

    def fake_fetch(query, params):
        assert "error_message" not in query
        assert params == {"limit": 5}
        return [{"status": "succeeded", "scored_rows": 2326}]

    monkeypatch.setattr(api, "fetch_rows", fake_fetch)
    with TestClient(api.app) as client:
        response = client.get("/pipeline/runs?limit=5")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "succeeded"
