-- Retention of households grouped by their first observed purchase
-- Periods are 30-day intervals relative to each household's first purchase
-- Only fully observable periods are included in the denominator

WITH observation_window AS (
    SELECT MAX(day) AS last_observed_day
    FROM analytics.baskets
),

first_purchases AS (
    SELECT
        household_key,
        MIN(day) AS first_purchase_day,
        1 + 30 * ((MIN(day) - 1) / 30) AS cohort_start_day
    FROM analytics.baskets
    GROUP BY household_key
),

cohort_sizes AS (
    SELECT
        cohort_start_day,
        COUNT(*) AS cohort_size
    FROM first_purchases
    GROUP BY cohort_start_day
),

activity_by_period AS (
    SELECT
        f.household_key,
        (b.day - f.first_purchase_day) / 30 AS period_number,
        COUNT(*) AS basket_count,
        SUM(b.basket_sales) AS period_sales
    FROM analytics.baskets b
    JOIN first_purchases f
        ON b.household_key = f.household_key
    WHERE
        b.day >= f.first_purchase_day
        AND b.day < f.first_purchase_day + 210
    GROUP BY
        f.household_key,
        (b.day - f.first_purchase_day) / 30
),

eligible_periods AS (
    SELECT
        f.household_key,
        f.cohort_start_day,
        p.period_number
    FROM first_purchases f
    CROSS JOIN generate_series(1, 6) AS p(period_number)
    CROSS JOIN observation_window o
    WHERE
        f.first_purchase_day
        + (p.period_number + 1) * 30 - 1
        <= o.last_observed_day
)

SELECT
    e.cohort_start_day,
    e.period_number,
    MAX(c.cohort_size) AS cohort_size,

    COUNT(*) AS eligible_households,

    COUNT(a.household_key) AS retained_households,

    ROUND(
        100.0 * COUNT(a.household_key)
        / NULLIF(COUNT(*), 0),
        2
    ) AS retention_rate_pct,

    COALESCE(
        SUM(a.basket_count),
        0
    ) AS return_baskets,

    ROUND(
        COALESCE(SUM(a.period_sales), 0)::NUMERIC,
        2
    ) AS period_revenue,

    ROUND(
        (
            COALESCE(SUM(a.period_sales), 0)
            / NULLIF(COUNT(*), 0)
        )::NUMERIC,
        2
    ) AS revenue_per_eligible_household

FROM eligible_periods e

JOIN cohort_sizes c
    ON e.cohort_start_day = c.cohort_start_day

LEFT JOIN activity_by_period a
    ON e.household_key = a.household_key
    AND e.period_number = a.period_number

GROUP BY
    e.cohort_start_day,
    e.period_number

HAVING MAX(c.cohort_size) >= 30

ORDER BY
    e.cohort_start_day,
    e.period_number;