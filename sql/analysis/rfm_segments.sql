-- Descriptive RFM segmentation at the end of day 711 (day-711 baskets included)
-- Recency: days from each household's last basket to day 711, using all history
-- Frequency and monetary: baskets and Recorded Sales Value (fuel included) in
-- the trailing 182 days, days 530-711 inclusive
-- Scores are 1-5 cumulative-distribution quintiles among households with at
-- least one basket in the window; tied values share a score
-- Households with no basket in the window form a separate, unscored segment
-- Descriptive only; separate from the predictive lifecycle segments

WITH parameters AS (
    SELECT
        711 AS cutoff_day,
        182 AS window_days
),

household_history AS (
    SELECT
        h.household_key,
        p.cutoff_day - MAX(b.day) AS recency_days,

        COUNT(b.basket_id) FILTER (
            WHERE b.day > p.cutoff_day - p.window_days
        ) AS frequency_baskets,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day > p.cutoff_day - p.window_days
            ),
            0
        ) AS monetary_value

    FROM core.households h
    CROSS JOIN parameters p
    LEFT JOIN analytics.baskets b
        ON b.household_key = h.household_key
        AND b.day <= p.cutoff_day
    GROUP BY
        h.household_key,
        p.cutoff_day
),

window_ranks AS (
    SELECT
        household_key,
        COUNT(*) OVER () AS scored_households,

        COUNT(*) OVER (
            ORDER BY recency_days DESC
        ) AS recency_position,

        COUNT(*) OVER (
            ORDER BY frequency_baskets
        ) AS frequency_position,

        COUNT(*) OVER (
            ORDER BY monetary_value
        ) AS monetary_position

    FROM household_history
    WHERE frequency_baskets > 0
),

-- Integer ceiling of 5 * cumulative share avoids floating-point boundary errors
scores AS (
    SELECT
        household_key,
        (5 * recency_position + scored_households - 1)
            / scored_households AS recency_score,
        (5 * frequency_position + scored_households - 1)
            / scored_households AS frequency_score,
        (5 * monetary_position + scored_households - 1)
            / scored_households AS monetary_score
    FROM window_ranks
),

segmented AS (
    SELECT
        h.*,
        CASE
            WHEN h.frequency_baskets = 0
                THEN 'No purchase in window'
            WHEN s.recency_score >= 4
                 AND s.frequency_score + s.monetary_score >= 8
                THEN 'Champions'
            WHEN s.recency_score >= 3
                 AND s.frequency_score + s.monetary_score >= 6
                THEN 'Loyal'
            WHEN s.recency_score >= 3
                THEN 'Recent, lower value'
            WHEN s.frequency_score + s.monetary_score >= 6
                THEN 'Valuable, less recent'
            ELSE 'Low value, less recent'
        END AS segment
    FROM household_history h
    LEFT JOIN scores s
        ON h.household_key = s.household_key
)

SELECT
    CASE segment
        WHEN 'Champions' THEN 1
        WHEN 'Loyal' THEN 2
        WHEN 'Recent, lower value' THEN 3
        WHEN 'Valuable, less recent' THEN 4
        WHEN 'Low value, less recent' THEN 5
        ELSE 6
    END AS segment_order,

    segment,
    COUNT(*) AS households,

    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
        2
    ) AS household_share_pct,

    SUM(frequency_baskets) AS window_baskets,
    ROUND(SUM(monetary_value), 2) AS window_sales_value,

    ROUND(
        100.0 * SUM(monetary_value)
        / NULLIF(SUM(SUM(monetary_value)) OVER (), 0),
        2
    ) AS sales_share_pct,

    PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY recency_days
    ) AS median_recency_days,

    ROUND(AVG(frequency_baskets), 2) AS baskets_per_household,
    ROUND(AVG(monetary_value), 2) AS sales_value_per_household

FROM segmented
GROUP BY segment
ORDER BY segment_order;
