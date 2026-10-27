import pytest
from fastapi.testclient import TestClient

import retail_analytics.api as api


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


def test_health(monkeypatch, client):
    monkeypatch.setattr(
        api,
        "fetch_rows",
        lambda query, params=None: [{"connected": 1}],
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_runs(monkeypatch, client):
    expected = [{
        "as_of_day": 711,
        "model_version": "v1",
        "households_scored": 2326,
    }]

    monkeypatch.setattr(
        api,
        "fetch_rows",
        lambda query, params=None: expected,
    )

    response = client.get("/runs")

    assert response.status_code == 200
    assert response.json() == expected


def test_list_predictions(monkeypatch, client):
    prediction = {
        "household_key": "1907",
        "as_of_day": 711,
        "model_version": "v1",
        "predicted_probability": 0.9899,
        "score_decile": 10,
        "rank": 1,
    }

    def fake_fetch(query, params=None):
        assert params["as_of_day"] == 711
        assert params["model_version"] == "v1"

        if "COUNT(*)" in query:
            return [{"total": 2326}]

        return [prediction]

    monkeypatch.setattr(api, "fetch_rows", fake_fetch)

    response = client.get(
        "/predictions",
        params={"as_of_day": 711, "limit": 20},
    )

    assert response.status_code == 200

    result = response.json()

    assert result["total"] == 2326
    assert result["predictions"] == [prediction]


def test_customer_prediction(monkeypatch, client):
    prediction = {
        "household_key": "1907",
        "as_of_day": 711,
        "model_version": "v1",
        "predicted_probability": 0.9899,
        "score_decile": 10,
        "rank": 1,
    }

    monkeypatch.setattr(
        api,
        "fetch_rows",
        lambda query, params=None: [prediction],
    )

    response = client.get(
        "/predictions/1907",
        params={"as_of_day": 711},
    )

    assert response.status_code == 200
    assert response.json()["household_key"] == "1907"


def test_unknown_customer(monkeypatch, client):
    monkeypatch.setattr(
        api,
        "fetch_rows",
        lambda query, params=None: [],
    )

    response = client.get(
        "/predictions/999999",
        params={"as_of_day": 711},
    )

    assert response.status_code == 404


def test_invalid_limit(client):
    response = client.get(
        "/predictions",
        params={
            "as_of_day": 711,
            "limit": 1000,
        },
    )

    assert response.status_code == 422