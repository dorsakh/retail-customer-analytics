"""Descriptive analytics: 28-day business KPIs, 30-day cohorts, and RFM.

Runs the committed SQL in ``sql/analysis/`` in a read-only transaction,
writes reporting tables to ``reports/tables/`` and three figures to
``reports/figures/``.

Recorded Sales Value is the documented amount the retailer receives
(fuel included). It is not customer expenditure, net revenue, or profit.
Like-for-like comparisons exclude panel-ramp and incomplete KPI periods;
the reporting tables keep every period.

    python -m retail_analytics.descriptive
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql" / "analysis"
REPORT_DIR = ROOT / "reports" / "tables"

WINDOW_PERIODS = 4
OFFSET_PERIODS = 13  # 13 x 28 = 364 days, the same weeks one year later
TREND_METRICS = {
    "recorded_sales_value": "Recorded Sales Value",
    "active_households": "Active households",
    "sales_per_active_household": "Recorded Sales Value per active household",
    "baskets_per_active_household": "Baskets per active household",
    "average_basket_value": "Average basket value",
    "fuel_share_pct": "Fuel share of Recorded Sales Value (%)",
}
DEFINITIONS = {
    "recorded_sales_value": "SUM(sales_value) in the 28-day period, fuel included",
    "active_households": "Households with at least one basket in the period",
    "sales_per_active_household": "Recorded Sales Value / active households",
    "baskets_per_active_household": "All baskets, including zero-value, / active households",
    "average_basket_value": "Recorded Sales Value / all baskets, including zero-value",
    "fuel_share_pct": "Fuel Recorded Sales Value / Recorded Sales Value",
}


def load_query(filename: str) -> str:
    """Return a committed analysis query without comments or the final semicolon."""
    lines = (SQL_DIR / filename).read_text().splitlines()
    statement = "\n".join(
        line for line in lines if not line.lstrip().startswith("--")
    )
    return statement.strip().rstrip(";")


def to_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert PostgreSQL NUMERIC (Decimal) columns to floats for reporting."""
    frame = frame.copy()
    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, Decimal)).any():
            frame[column] = frame[column].astype(float)
    return frame


def like_for_like(kpis: pd.DataFrame) -> pd.DataFrame:
    """Complete, post-ramp periods only; these support trend comparisons."""
    required = {"period_number", "is_complete", "is_panel_ramp"}
    if required - set(kpis.columns):
        raise ValueError(f"Missing KPI columns: {sorted(required - set(kpis.columns))}")
    if kpis["period_number"].duplicated().any():
        raise ValueError("Duplicate KPI periods")

    comparable = kpis.loc[
        kpis["is_complete"].astype(bool) & ~kpis["is_panel_ramp"].astype(bool)
    ].sort_values("period_number")
    if comparable.empty:
        raise ValueError("No complete post-ramp periods to compare")
    if comparable["period_number"].diff().dropna().ne(1).any():
        raise ValueError("Like-for-like periods must be contiguous")
    return comparable


def comparison_windows(
    kpis: pd.DataFrame,
    *,
    window_periods: int = WINDOW_PERIODS,
    offset_periods: int = OFFSET_PERIODS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """First like-for-like window and the window ``offset_periods`` later.

    The default 13-period offset is 364 days, so both windows cover the same
    part of the year (52 weeks apart).
    """
    if offset_periods < window_periods:
        raise ValueError("Comparison windows must not overlap")
    comparable = like_for_like(kpis).set_index("period_number", drop=False)
    first = int(comparable.index[0])
    early_periods = range(first, first + window_periods)
    late_periods = range(first + offset_periods, first + offset_periods + window_periods)
    missing = [p for p in [*early_periods, *late_periods] if p not in comparable.index]
    if missing:
        raise ValueError(f"Comparison periods are not like-for-like: {missing}")
    return comparable.loc[list(early_periods)], comparable.loc[list(late_periods)]


def like_for_like_summary(
    kpis: pd.DataFrame,
    *,
    window_periods: int = WINDOW_PERIODS,
    offset_periods: int = OFFSET_PERIODS,
    metrics=TREND_METRICS,
) -> pd.DataFrame:
    """Compare mean KPIs in two equal windows 364 days apart (by default).

    Each window value is the unweighted mean of its period-level KPIs.
    """

    def span(window, column):
        return f"{window[column].min()}-{window[column].max()}"

    early, late = comparison_windows(
        kpis, window_periods=window_periods, offset_periods=offset_periods,
    )
    rows = []
    for column, label in metrics.items():
        early_mean = early[column].astype(float).mean()
        late_mean = late[column].astype(float).mean()
        rows.append({
            "metric": column,
            "label": label,
            "definition": DEFINITIONS.get(column, ""),
            "early_periods": span(early, "period_number"),
            "early_days": f"{early['start_day'].min()}-{early['end_day'].max()}",
            "late_periods": span(late, "period_number"),
            "late_days": f"{late['start_day'].min()}-{late['end_day'].max()}",
            "early_mean": round(early_mean, 2),
            "late_mean": round(late_mean, 2),
            # Shares change in percentage points; levels change in percent.
            "change_pct": (
                None if column.endswith("_pct")
                else round(100 * (late_mean / early_mean - 1), 2)
            ),
            "change_pp": (
                round(late_mean - early_mean, 2) if column.endswith("_pct") else None
            ),
        })
    return pd.DataFrame(rows)


def run_queries(engine) -> dict[str, pd.DataFrame]:
    queries = {
        "period_kpis": "period_kpis.sql",
        "cohort_retention": "cohort_retention.sql",
        "rfm_segments": "rfm_segments.sql",
    }
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET TRANSACTION READ ONLY"))
        frames = {
            name: to_numeric(pd.read_sql(text(load_query(filename)), connection))
            for name, filename in queries.items()
        }
        transaction.rollback()
    return frames


def plot_kpi_trend(kpis: pd.DataFrame) -> None:
    from .visualize import COLORS, plt, save_figure

    panels = {
        "sales_per_active_household": ("Recorded Sales Value per active household ($)", "{:,.2f}"),
        "average_basket_value": ("Average basket value ($, all baskets)", "{:,.2f}"),
        "active_households": ("Active households", "{:,.0f}"),
        "baskets_per_active_household": ("Baskets per active household", "{:,.2f}"),
    }
    comparable = like_for_like(kpis)
    early, late = comparison_windows(kpis)
    summary = like_for_like_summary(
        kpis, metrics={column: label for column, (label, _) in panels.items()},
    ).set_index("metric")

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    for ax, (column, (label, value_format)) in zip(axes.flat, panels.items()):
        ax.plot(
            comparable["period_number"], comparable[column],
            color=COLORS["LightGBM"], linewidth=2, marker="o", markersize=4,
        )
        for window, mean in (
            (early, summary.loc[column, "early_mean"]),
            (late, summary.loc[column, "late_mean"]),
        ):
            left = window["period_number"].min() - 0.4
            right = window["period_number"].max() + 0.4
            ax.axvspan(left, right, color="#E2E8F0", zorder=0)
            ax.hlines(mean, left, right, color="#334155", linewidth=1.5, linestyles="--")
            ax.annotate(
                f"mean {value_format.format(mean)}", (left + 0.1, mean),
                xytext=(0, 5), textcoords="offset points",
                fontsize=8.5, color="#334155", zorder=3,
                bbox={"boxstyle": "round,pad=0.15", "facecolor": "white", "edgecolor": "none", "alpha": 0.85},
            )
        change = summary.loc[column, "change_pct"]
        ax.set_title(f"{label}: {change:+.1f}%", loc="left", fontsize=10.5)

    for ax in axes[1]:
        ax.set_xticks(comparable["period_number"][::2])
        ax.set_xticklabels([f"P{p}" for p in comparable["period_number"][::2]])
        ax.set_xlabel("28-day period")

    fig.suptitle(
        f"Like-for-like 28-day KPIs, P{comparable['period_number'].min()}–"
        f"P{comparable['period_number'].max()}. Shaded: comparison windows "
        f"P{early['period_number'].min()}–P{early['period_number'].max()} "
        f"(days {early['start_day'].min()}–{early['end_day'].max()}) vs "
        f"P{late['period_number'].min()}–P{late['period_number'].max()} "
        f"(days {late['start_day'].min()}–{late['end_day'].max()}), 364 days apart",
        x=0.01, ha="left", fontsize=11,
    )
    fig.text(
        0.01, -0.01,
        "Dashed lines and % changes use unweighted four-period means. "
        "Panel-ramp P1–P5 and the incomplete final period are excluded.",
        fontsize=8.5, color="#475569",
    )
    fig.tight_layout()
    save_figure(fig, "kpi_trend.png")


def plot_cohort_retention(cohorts: pd.DataFrame) -> None:
    from matplotlib.ticker import PercentFormatter

    from .visualize import COLORS, plt, save_figure

    colors = [COLORS["LightGBM"], COLORS["Logistic regression"], COLORS["XGBoost"], COLORS["HistGradientBoosting"]]
    markers = ["o", "s", "^", "D"]
    fig, ax = plt.subplots(figsize=(9, 5))
    for index, (start_day, cohort) in enumerate(cohorts.groupby("cohort_start_day")):
        cohort = cohort.sort_values("period_number")
        label = (
            f"First observed days {start_day}–{start_day + 29} "
            f"(n = {int(cohort['cohort_size'].iloc[0]):,})"
        )
        ax.plot(
            cohort["period_number"], cohort["retention_rate_pct"],
            color=colors[index], marker=markers[index], markersize=6,
            linewidth=2, label=label,
        )

    ax.set_ylim(0, 100)
    ax.set_xticks(range(1, int(cohorts["period_number"].max()) + 1))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.set_title(
        "Share of each first-observed cohort purchasing in each 30-day period",
        loc="left",
    )
    ax.set_xlabel(
        "30-day period after first observed purchase "
        "(cohorts reflect panel enrollment, not verified acquisition)"
    )
    ax.set_ylabel("Households with a purchase")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    save_figure(fig, "cohort_retention.png")


def plot_rfm_concentration(rfm: pd.DataFrame) -> None:
    import numpy as np

    from .visualize import COLORS, plt, save_figure

    rfm = rfm.sort_values("segment_order", ascending=False)
    y = np.arange(len(rfm))
    height = 0.38

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = {
        "household_share_pct": ("Share of households", COLORS["Recency + frequency"], height / 2 + 0.01),
        "sales_share_pct": ("Share of Recorded Sales Value", COLORS["LightGBM"], -height / 2 - 0.01),
    }
    for column, (label, color, offset) in bars.items():
        ax.barh(y + offset, rfm[column], height=height, color=color, label=label)
        for position, value in zip(y + offset, rfm[column]):
            ax.annotate(
                f"{value:.1f}%", (value, position), xytext=(4, 0),
                textcoords="offset points", va="center", fontsize=8.5, color="#334155",
            )

    ax.set_yticks(y)
    ax.set_yticklabels(rfm["segment"])
    ax.set_xlim(0, max(rfm["household_share_pct"].max(), rfm["sales_share_pct"].max()) * 1.15)
    ax.grid(axis="y", visible=False)
    ax.set_title(
        "RFM segments at end of day 711: households vs Recorded Sales Value",
        loc="left",
    )
    ax.set_xlabel("Share (%), trailing 182 days (days 530–711); descriptive, not predictive")
    ax.legend(frameon=False, loc="lower right")
    save_figure(fig, "rfm_value_concentration.png")


def main() -> None:
    engine = create_engine(DATABASE_URL)
    try:
        frames = run_queries(engine)
    finally:
        engine.dispose()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(REPORT_DIR / f"{name}.csv", index=False)

    summary = like_for_like_summary(frames["period_kpis"])
    summary.to_csv(REPORT_DIR / "kpi_like_for_like.csv", index=False)

    from .visualize import FIGURE_DIR

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    plot_kpi_trend(frames["period_kpis"])
    plot_cohort_retention(frames["cohort_retention"])
    plot_rfm_concentration(frames["rfm_segments"])

    print(summary.to_string(index=False))
    print(f"\nTables saved to {REPORT_DIR}; figures saved to {FIGURE_DIR}")


if __name__ == "__main__":
    main()
