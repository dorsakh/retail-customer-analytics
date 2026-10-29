"""Like-for-like KPI selection and comparison rules (no database required)."""

import pandas as pd
import pytest

from retail_analytics.descriptive import (
    comparison_windows, like_for_like, like_for_like_summary, load_query,
)


def kpis(periods=12, ramp=3):
    frame = pd.DataFrame({
        "period_number": range(1, periods + 1),
        "is_complete": [True] * (periods - 1) + [False],
        "is_panel_ramp": [True] * ramp + [False] * (periods - ramp),
        "start_day": [1 + 28 * i for i in range(periods)],
        "end_day": [28 * (i + 1) for i in range(periods)],
        "recorded_sales_value": [100.0 + 10 * i for i in range(periods)],
        "active_households": [50.0] * periods,
        "fuel_share_pct": [8.0] * (periods // 2) + [7.0] * (periods - periods // 2),
    })
    return frame


METRICS = {
    "recorded_sales_value": "Recorded Sales Value",
    "active_households": "Active households",
    "fuel_share_pct": "Fuel share (%)",
}


def test_like_for_like_excludes_ramp_and_incomplete_periods():
    comparable = like_for_like(kpis())
    assert comparable["period_number"].tolist() == list(range(4, 12))


@pytest.mark.parametrize("change, message", [
    (lambda f: f.assign(period_number=[1] * len(f)), "Duplicate"),
    (lambda f: f.assign(is_panel_ramp=True), "No complete post-ramp"),
    (lambda f: f.assign(is_complete=[True] * 6 + [False] + [True] * 5), "contiguous"),
    (lambda f: f.drop(columns="is_complete"), "Missing KPI columns"),
])
def test_like_for_like_rejects_invalid_period_tables(change, message):
    with pytest.raises(ValueError, match=message):
        like_for_like(change(kpis()))


def test_comparison_windows_are_offset_from_first_comparable_period():
    early, late = comparison_windows(kpis(), window_periods=3, offset_periods=4)
    assert early["period_number"].tolist() == [4, 5, 6]
    assert late["period_number"].tolist() == [8, 9, 10]

    with pytest.raises(ValueError, match="overlap"):
        comparison_windows(kpis(), window_periods=3, offset_periods=2)
    # Period 12 is incomplete, so a late window reaching it is rejected.
    with pytest.raises(ValueError, match=r"not like-for-like: \[12\]"):
        comparison_windows(kpis(), window_periods=3, offset_periods=6)


def test_summary_states_windows_and_uses_points_for_shares():
    summary = like_for_like_summary(
        kpis(), window_periods=3, offset_periods=4, metrics=METRICS,
    ).set_index("metric")
    sales = summary.loc["recorded_sales_value"]
    assert (sales["early_periods"], sales["late_periods"]) == ("4-6", "8-10")
    assert (sales["early_days"], sales["late_days"]) == ("85-168", "197-280")
    assert sales["definition"].startswith("SUM(sales_value)")
    # Mean of 130/140/150 versus 170/180/190.
    assert sales["change_pct"] == pytest.approx(100 * (180 / 140 - 1), abs=0.01)
    assert pd.isna(sales["change_pp"])
    fuel = summary.loc["fuel_share_pct"]
    assert pd.isna(fuel["change_pct"])
    # Periods 4-6 have an 8% share; periods 8-10 have 7%.
    assert fuel["change_pp"] == pytest.approx(-1.0)


def test_default_windows_are_364_days_apart():
    early, late = comparison_windows(kpis(periods=26, ramp=5))
    assert early["period_number"].tolist() == [6, 7, 8, 9]
    assert late["period_number"].tolist() == [19, 20, 21, 22]
    assert (late["start_day"].to_numpy() - early["start_day"].to_numpy() == 364).all()


def test_committed_queries_load_without_comments_or_terminator():
    for filename in ("period_kpis.sql", "rfm_segments.sql", "cohort_retention.sql"):
        statement = load_query(filename)
        assert statement.startswith("WITH")
        assert not statement.endswith(";")
        assert "\n--" not in statement
