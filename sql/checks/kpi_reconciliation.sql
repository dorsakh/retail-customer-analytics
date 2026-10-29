-- Reconcile the basket mart used by the descriptive KPIs against core line items
-- and verify the source assumptions behind recorded sales value

WITH core_totals AS (
    SELECT
        SUM(sales_value) AS sales_value,
        COUNT(DISTINCT basket_id)::NUMERIC AS baskets,
        COUNT(DISTINCT household_key)::NUMERIC AS households,
        COUNT(*) FILTER (
            WHERE sales_value < 0
        )::NUMERIC AS negative_sales_lines,
        COUNT(*) FILTER (
            WHERE sales_value IS NULL OR day IS NULL OR day < 1
        )::NUMERIC AS lines_without_valid_day_or_sales
    FROM core.transaction_items
),

mart_totals AS (
    SELECT
        SUM(basket_sales) AS sales_value,
        COUNT(*)::NUMERIC AS baskets,
        COUNT(DISTINCT household_key)::NUMERIC AS households
    FROM analytics.baskets
),

multi_day_baskets AS (
    SELECT COUNT(*)::NUMERIC AS baskets
    FROM (
        SELECT basket_id
        FROM core.transaction_items
        GROUP BY basket_id
        HAVING COUNT(DISTINCT day) > 1
            OR COUNT(DISTINCT household_key) > 1
    ) AS inconsistent
),

core_period_sales AS (
    SELECT
        (day - 1) / 28 + 1 AS period_number,
        SUM(sales_value) AS sales_value
    FROM core.transaction_items
    GROUP BY (day - 1) / 28 + 1
),

mart_period_sales AS (
    SELECT
        (day - 1) / 28 + 1 AS period_number,
        SUM(basket_sales) AS sales_value
    FROM analytics.baskets
    GROUP BY (day - 1) / 28 + 1
),

period_mismatches AS (
    SELECT COUNT(*)::NUMERIC AS periods
    FROM core_period_sales c
    FULL JOIN mart_period_sales m
        ON c.period_number = m.period_number
    WHERE c.sales_value IS DISTINCT FROM m.sales_value
),

rfm_window_sales AS (
    SELECT
        (
            SELECT SUM(sales_value)
            FROM core.transaction_items
            WHERE day BETWEEN 530 AND 711
        ) AS core_value,
        (
            SELECT SUM(basket_sales)
            FROM analytics.baskets
            WHERE day BETWEEN 530 AND 711
        ) AS mart_value
),

roster AS (
    SELECT COUNT(*)::NUMERIC AS households
    FROM core.households
)

SELECT
    metric,
    expected_value,
    actual_value,
    CASE
        WHEN expected_value IS NOT DISTINCT FROM actual_value
        THEN 'PASS'
        ELSE 'FAIL'
    END AS validation
FROM core_totals c
CROSS JOIN mart_totals m
CROSS JOIN multi_day_baskets d
CROSS JOIN period_mismatches p
CROSS JOIN rfm_window_sales w
CROSS JOIN roster r
CROSS JOIN LATERAL (
    VALUES
        ('recorded_sales_value', c.sales_value, m.sales_value),
        ('baskets', c.baskets, m.baskets),
        ('households_with_baskets', c.households, m.households),
        ('household_roster', r.households, m.households),
        ('negative_sales_lines', 0, c.negative_sales_lines),
        ('lines_without_valid_day_or_sales', 0, c.lines_without_valid_day_or_sales),
        ('baskets_spanning_days_or_households', 0, d.baskets),
        ('periods_28d_with_sales_mismatch', 0, p.periods),
        ('rfm_window_sales_value', w.core_value, w.mart_value)
) AS metrics(metric, expected_value, actual_value);
