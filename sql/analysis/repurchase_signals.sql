-- Examine the relationship between purchase recency, spending momentum, and subsequent repurchase

WITH labeled AS (
    SELECT
        s.as_of_day,
        s.household_key,
        s.recency_days,
        s.sales_30d,
        s.sales_previous_30d,
        s.baskets_30d,
        r.repurchased_7d::INTEGER AS repurchased

    FROM analytics.household_snapshots s
    JOIN analytics.repurchase_7d r
        USING (household_key, as_of_day)

    WHERE s.as_of_day <= 540
),

segments AS (
    SELECT
        CASE
            WHEN recency_days <= 3 THEN '01: 0-3 days'
            WHEN recency_days <= 7 THEN '02: 4-7 days'
            WHEN recency_days <= 14 THEN '03: 8-14 days'
            ELSE '04: 15+ days'
        END AS recency_segment,

        CASE
            WHEN sales_previous_30d = 0
                THEN 'No prior-period spend'
            WHEN sales_30d < 0.8 * sales_previous_30d
                THEN 'Declining'
            WHEN sales_30d > 1.2 * sales_previous_30d
                THEN 'Growing'
            ELSE 'Stable'
        END AS spending_pattern,

        repurchased

    FROM labeled
)

SELECT
    recency_segment,
    spending_pattern,
    COUNT(*) AS observations,
    ROUND(
        100.0 * AVG(repurchased::NUMERIC),
        1
    ) AS repurchase_rate_pct

FROM segments
GROUP BY recency_segment, spending_pattern
HAVING COUNT(*) >= 50
ORDER BY recency_segment, spending_pattern;


-- Compare simple selection strategies against the base rate

WITH labeled AS (
    SELECT
        s.as_of_day,
        s.household_key,
        s.recency_days,
        s.baskets_30d,
        r.repurchased_7d::INTEGER AS repurchased

    FROM analytics.household_snapshots s
    JOIN analytics.repurchase_7d r
        USING (household_key, as_of_day)

    WHERE s.as_of_day <= 540
),

ranked AS (
    SELECT
        *,

        NTILE(5) OVER (
            PARTITION BY as_of_day
            ORDER BY recency_days, household_key
        ) AS recency_quintile,

        NTILE(5) OVER (
            PARTITION BY as_of_day
            ORDER BY
                recency_days,
                baskets_30d DESC,
                household_key
        ) AS recency_frequency_quintile

    FROM labeled
),

performance AS (
    SELECT
        'Recency only' AS strategy,
        COUNT(*) FILTER (
            WHERE recency_quintile = 1
        ) AS selected_observations,
        AVG(repurchased::NUMERIC) AS baseline_rate,
        AVG(repurchased::NUMERIC) FILTER (
            WHERE recency_quintile = 1
        ) AS selected_rate
    FROM ranked

    UNION ALL

    SELECT
        'Recency + frequency',
        COUNT(*) FILTER (
            WHERE recency_frequency_quintile = 1
        ),
        AVG(repurchased::NUMERIC),
        AVG(repurchased::NUMERIC) FILTER (
            WHERE recency_frequency_quintile = 1
        )
    FROM ranked
)

SELECT
    strategy,
    selected_observations,
    ROUND(100 * baseline_rate, 2) AS baseline_rate_pct,
    ROUND(100 * selected_rate, 2) AS selected_rate_pct,
    ROUND(
        selected_rate / NULLIF(baseline_rate, 0),
        3
    ) AS predictive_lift

FROM performance
ORDER BY strategy;