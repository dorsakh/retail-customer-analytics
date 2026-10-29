"""Validation of the descriptive KPI, RFM, cohort, and reconciliation SQL.

Fixture tests run the committed SQL against temporary tables inside a
rolled-back transaction, so an empty PostgreSQL database is enough (CI starts
one). Live tests read the populated database in a read-only transaction and
skip without it. Set REQUIRE_POSTGRES=1 to fail instead of skipping when
PostgreSQL itself is unreachable.
"""

import os
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from retail_analytics.data import DATABASE_URL


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TABLES = (
    "analytics.baskets",
    "core.transaction_items",
    "core.products",
    "core.households",
)


def read_sql(relative_path: str) -> str:
    lines = (ROOT / relative_path).read_text().splitlines()
    statement = "\n".join(
        line for line in lines if not line.lstrip().startswith("--")
    )
    return statement.strip().rstrip(";")


def on_temp_tables(statement: str) -> str:
    """Point the committed SQL at session-local fixture tables."""
    for name in SOURCE_TABLES:
        statement = statement.replace(name, f"pg_temp.{name.split('.')[1]}")
    assert not re.search(r"\b(?:analytics|core)\.\w+", statement)
    return statement


def query(connection, statement: str) -> pd.DataFrame:
    return pd.DataFrame(connection.execute(text(statement)).mappings().all())


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        engine.dispose()
        if os.getenv("REQUIRE_POSTGRES") == "1":
            raise
        pytest.skip("PostgreSQL is unavailable")
    yield engine
    engine.dispose()


@pytest.fixture
def fixture_db(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        for statement in (
            """CREATE TEMP TABLE households (household_key TEXT)
               ON COMMIT DROP""",
            """CREATE TEMP TABLE baskets (
                   basket_id TEXT, household_key TEXT, day INTEGER,
                   basket_sales NUMERIC
               ) ON COMMIT DROP""",
            """CREATE TEMP TABLE transaction_items (
                   basket_id TEXT, day INTEGER, product_id TEXT,
                   sales_value NUMERIC, retail_disc NUMERIC,
                   coupon_disc NUMERIC, coupon_match_disc NUMERIC
               ) ON COMMIT DROP""",
            """CREATE TEMP TABLE products (
                   product_id TEXT, sub_commodity_desc TEXT
               ) ON COMMIT DROP""",
            """INSERT INTO products VALUES
                   ('gas', 'GASOLINE-REG UNLEADED'),
                   ('milk', 'FLUID MILK WHITE ONLY')""",
        ):
            connection.execute(text(statement))
        yield connection
        transaction.rollback()


@pytest.fixture
def live_db(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET TRANSACTION READ ONLY"))
        populated = connection.execute(
            text("SELECT to_regclass('analytics.baskets') IS NOT NULL")
        ).scalar_one()
        if not populated:
            transaction.rollback()
            pytest.skip("Populated retail_analytics database is unavailable")
        yield connection
        transaction.rollback()


def test_period_kpis_flag_ramp_and_incomplete_periods(fixture_db):
    fixture_db.execute(text("""
        INSERT INTO baskets VALUES
            ('b1', 'h1',  1, 10),
            ('b2', 'h1', 20,  0),
            ('b3', 'h2', 30, 30),
            ('b4', 'h1', 40, 20),
            ('b5', 'h1', 60, 25),
            ('b6', 'h3', 90, 40)
    """))
    fixture_db.execute(text("""
        INSERT INTO transaction_items VALUES
            ('b1',  1, 'milk', 10, -2,     0,     0),
            ('b4', 40, 'gas',   8,  0,     0,     0),
            ('b4', 40, 'milk', 12, -1, -0.55, -0.45),
            ('b4', 40, 'milk',  0,  0.25,  0,     0)
    """))

    kpis = query(fixture_db, on_temp_tables(
        read_sql("sql/analysis/period_kpis.sql")
    )).set_index("period_number")

    assert kpis.index.tolist() == [1, 2, 3, 4]
    assert kpis["is_complete"].tolist() == [True, True, True, False]
    assert kpis.loc[4, ["start_day", "end_day", "observed_days"]].tolist() == [85, 112, 6]
    # Every period with a first-observed household meets the 1% ramp threshold.
    assert kpis["first_observed_households"].tolist() == [1, 1, 0, 1]
    assert kpis["is_panel_ramp"].tolist() == [True, True, False, True]

    # Zero-value baskets are counted as baskets and in the basket-value denominator.
    assert kpis.loc[1, "baskets"] == 2
    assert kpis.loc[1, "zero_value_baskets"] == 1
    assert kpis.loc[1, "average_basket_value"] == Decimal("5.00")
    # Discount fields stay separate and sign-reversed; a positive retail_disc reduces the total.
    assert kpis.loc[1, "loyalty_discount"] == Decimal("2.00")
    assert kpis.loc[2, ["loyalty_discount", "coupon_match_discount",
                        "manufacturer_coupon_discount"]].tolist() == [
        Decimal("0.75"), Decimal("0.45"), Decimal("0.55"),
    ]
    assert kpis.loc[3, "loyalty_discount"] == 0

    assert kpis.loc[2, "active_households"] == 2
    assert kpis.loc[2, "recorded_sales_value"] == Decimal("50.00")
    assert kpis.loc[2, "sales_per_active_household"] == Decimal("25.00")
    assert kpis.loc[2, "fuel_sales_value"] == Decimal("8.00")
    assert kpis.loc[2, "fuel_share_pct"] == Decimal("16.00")
    assert kpis["recorded_sales_value"].sum() == Decimal("125.00")


def test_rfm_window_scores_ties_and_unscored_households(fixture_db):
    fixture_db.execute(text("""
        INSERT INTO households VALUES ('A'), ('B'), ('C'), ('D'), ('E'), ('F')
    """))
    fixture_db.execute(text("""
        INSERT INTO baskets VALUES
            ('a1', 'A', 600, 100), ('a2', 'A', 700, 100),
            ('a3', 'A', 711, 100), ('a4', 'A', 720, 999),
            ('b1', 'B', 650,  50),
            ('c1', 'C', 100, 500),
            ('c2', 'C', 529, 500),
            ('e1', 'E', 705,  20), ('e2', 'E', 710,  20),
            ('f1', 'F', 540, 200), ('f2', 'F', 545, 200)
    """))

    segments = query(fixture_db, on_temp_tables(
        read_sql("sql/analysis/rfm_segments.sql")
    )).set_index("segment")

    # A: R5 F5 M4; E: R4 F4 M2; B: R3 F2 M3; F: R2 F4 M5 (E and F tie on frequency).
    assert segments["households"].to_dict() == {
        "Champions": 1,
        "Loyal": 1,
        "Recent, lower value": 1,
        "Valuable, less recent": 1,
        "No purchase in window": 2,
    }
    # Day 720 is after the cutoff and day 529 is outside the 182-day window.
    assert segments.loc["Champions", "window_sales_value"] == Decimal("300.00")
    assert segments.loc["No purchase in window", "window_sales_value"] == 0
    # C is 182 days stale; D has no purchase history and no recency.
    assert segments.loc["No purchase in window", "median_recency_days"] == 182
    assert segments["window_sales_value"].sum() == Decimal("790.00")
    assert segments["segment_order"].is_monotonic_increasing


def test_reconciliation_checks_pass_on_live_data(live_db):
    checks = query(live_db, read_sql("sql/checks/kpi_reconciliation.sql"))
    failed = checks.loc[checks["validation"].ne("PASS"), "metric"].tolist()
    assert len(checks) == 9
    assert failed == []


def test_period_kpis_reconcile_with_live_core_totals(live_db):
    kpis = query(live_db, read_sql("sql/analysis/period_kpis.sql"))
    totals = live_db.execute(text("""
        SELECT SUM(sales_value) AS sales, COUNT(DISTINCT basket_id) AS baskets
        FROM core.transaction_items
    """)).one()

    assert kpis["period_number"].tolist() == list(range(1, len(kpis) + 1))
    assert kpis["baskets"].sum() == totals.baskets
    # Each period rounds to cents; the summed rounding error stays below one cent per period.
    assert abs(kpis["recorded_sales_value"].sum() - totals.sales) <= Decimal("0.005") * len(kpis)
    assert (kpis["zero_value_baskets"] <= kpis["baskets"]).all()
    assert kpis["fuel_share_pct"].between(0, 100).all()

    # Only the final period may be incomplete, and ramp periods form an initial run.
    incomplete = kpis.loc[~kpis["is_complete"], "period_number"].tolist()
    assert incomplete in ([], [len(kpis)])
    ramp = kpis.loc[kpis["is_panel_ramp"], "period_number"].tolist()
    assert ramp == list(range(1, len(ramp) + 1))


def test_rfm_segments_cover_live_roster_and_window_sales(live_db):
    segments = query(live_db, read_sql("sql/analysis/rfm_segments.sql"))
    roster = live_db.execute(text("SELECT COUNT(*) FROM core.households")).scalar_one()
    window_sales = live_db.execute(text("""
        SELECT ROUND(SUM(basket_sales), 2)
        FROM analytics.baskets
        WHERE day BETWEEN 530 AND 711
    """)).scalar_one()

    assert segments["households"].sum() == roster
    assert segments["segment"].is_unique
    assert abs(segments["window_sales_value"].sum() - window_sales) <= Decimal("0.01") * len(segments)
    assert abs(segments["household_share_pct"].sum() - 100) <= Decimal("0.05")
    assert abs(segments["sales_share_pct"].sum() - 100) <= Decimal("0.05")


def test_cohort_retention_denominators_are_consistent(live_db):
    cohorts = query(live_db, read_sql("sql/analysis/cohort_retention.sql"))

    assert not cohorts.empty
    assert (cohorts["retained_households"] <= cohorts["eligible_households"]).all()
    assert (cohorts["eligible_households"] <= cohorts["cohort_size"]).all()
    assert cohorts["retention_rate_pct"].between(0, 100).all()
    assert cohorts["period_number"].between(1, 6).all()
