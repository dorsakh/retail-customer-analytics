import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import retail_analytics.api as api
from retail_analytics.data import FEATURE_COLUMNS
from retail_analytics.explorer import brier_loss, cohort_dna, find_paradox_pairs


def test_dna_is_cohort_relative_and_keeps_missing_values():
    data = pd.DataFrame({
        "baskets_90d": [2, 8, 20],
        "visit_interval_volatility_90d": [1.0, 4.0, np.nan],
        "sales_90d": [10, 20, 30],
        "sales_growth_30d": [-0.2, 0.0, 0.4],
        "discount_share_90d": [0.0, 0.1, 0.3],
    })
    dna = cohort_dna(data)
    assert dna.loc[2, "activity"] == 100
    assert dna.loc[0, "regularity"] == 100
    assert pd.isna(dna.loc[2, "regularity"])


def test_game_scoring():
    assert brier_loss(0.8, True) == pytest.approx(0.04)
    assert brier_loss(0.2, False) == pytest.approx(0.04)
    with pytest.raises(ValueError):
        brier_loss(float("nan"), True)


def test_paradox_match_does_not_reuse_households():
    frame = pd.DataFrame([
        {"household_key": "A", "recency_days": 3, "baskets_90d": 12, "predicted_probability": 0.85},
        {"household_key": "B", "recency_days": 3, "baskets_90d": 13, "predicted_probability": 0.44},
        {"household_key": "C", "recency_days": 3, "baskets_90d": 14, "predicted_probability": 0.25},
        {"household_key": "D", "recency_days": 10, "baskets_90d": 13, "predicted_probability": 0.08},
    ])
    pairs = find_paradox_pairs(frame)
    assert len(pairs) == 1
    assert pairs[0]["high_household"] == "A"
    assert pairs[0]["low_household"] == "C"


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


def test_game_hides_future_outcomes(monkeypatch, client):
    returned = {"household_key": "42", "as_of_day": 690,
                "features": {"recency_days": 7}, "purchase_history": []}
    monkeypatch.setattr(api, "fetch_rows", lambda *args, **kwargs: [returned])
    response = client.get("/explorer/game")
    assert response.status_code == 200
    assert response.json() == returned
    assert "repurchased_7d" not in response.json()
    assert "predicted_probability" not in response.json()


def test_game_reveal_compares_probability_losses(monkeypatch, client):
    monkeypatch.setattr(api, "fetch_rows", lambda *args, **kwargs: [{
        "predicted_probability": 0.6, "repurchased_7d": True,
        "baseline_rank": 36,
    }])
    response = client.post(
        "/explorer/game/690/42/guess", json={"predicted_probability": 0.9}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["beat_model"] is True
    assert result["model_brier"] == pytest.approx(0.16)
    assert result["your_brier"] == pytest.approx(0.01)


def test_dna_uses_live_saved_model(monkeypatch, client):
    features = dict.fromkeys(FEATURE_COLUMNS, 2.0)
    monkeypatch.setattr(api, "fetch_rows", lambda *args, **kwargs: [{
        "household_key": "42", "as_of_day": 711, "model_version": "v1",
        "propensity_rank": 55, "score_decile": 10,
        "features": features, "dna": {"activity": 90},
        "purchase_history": [], "predicted_probability": 0.7,
    }])

    class FakeModel:
        def predict(self, frame, validate_features=False):
            assert list(frame.columns) == FEATURE_COLUMNS
            assert validate_features
            return [0.72]

    monkeypatch.setattr(api, "get_explorer_model", lambda: FakeModel())
    result = client.get("/explorer/dna/42")
    assert result.status_code == 200
    assert result.json()["live_model_probability"] == pytest.approx(0.72)


def test_explorer_home_exists(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Beat the Model" in response.text
    assert "Shopping DNA" in response.text
