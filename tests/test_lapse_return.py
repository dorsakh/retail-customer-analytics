"""Censoring and return-window checks for the 14-day lapse audit."""

import pandas as pd
import pytest

from scripts.assess_lapse_return import select_lapsers, summarize_returns


def test_lapsers_require_a_complete_post_lapse_follow_up():
    snapshots = pd.DataFrame({
        "household_key": ["a", "b", "c", "d", "e"],
        "as_of_day": [600, 630, 660, 600, 600],
        "segment": ["eligible", "eligible", "eligible", "inactive", "eligible"],
        "lapsed_14d": [1, 1, 1, 1, 0],
    })
    selected = select_lapsers(snapshots, last_day=711)
    assert selected["household_key"].tolist() == ["a", "b"]
    # Day 660 does not have 14 + 60 observed days through day 711.
    assert selected["as_of_day"].max() <= 711 - 14 - 60


def test_returns_measured_after_the_lapse_not_after_prediction_day():
    observations = pd.DataFrame({
        "household_key": ["a", "b", "c", "d"],
        "as_of_day": [630] * 4,
        "next_day": [None, 654, 684, 709],  # none, +10d, +40d, +65d
    })
    summary = summarize_returns(observations, last_day=711).iloc[0]
    assert summary["lapse_observations"] == 4
    assert summary["distinct_households"] == 4
    assert summary["returned_within_30d_after_lapse"] == pytest.approx(.25)
    assert summary["returned_within_60d_after_lapse"] == pytest.approx(.50)
    assert summary["not_returned_within_60d_after_lapse"] == pytest.approx(.50)
    assert summary["not_returned_by_last_day"] == pytest.approx(.25)
    assert summary["median_days_after_lapse_to_return_within_60d"] == 25


def test_unmatured_and_inconsistent_next_purchase_is_rejected():
    with pytest.raises(ValueError, match="complete post-lapse"):
        summarize_returns(pd.DataFrame({
            "household_key": ["a"], "as_of_day": [660], "next_day": [None]
        }), last_day=711)
    with pytest.raises(ValueError, match="cannot repurchase"):
        summarize_returns(pd.DataFrame({
            "household_key": ["a"], "as_of_day": [600], "next_day": [605]
        }), last_day=711)
