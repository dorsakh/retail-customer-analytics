CREATE MATERIALIZED VIEW analytics.household_snapshots AS

WITH cutoffs AS (
    SELECT generate_series(
        180,
        (SELECT MAX(day) - 7 FROM analytics.baskets),
        30
    ) AS as_of_day
),

visit_days AS (
    SELECT DISTINCT
        household_key,
        day
    FROM analytics.baskets
),

visit_gaps AS (
    SELECT
        household_key,
        day,
        day - LAG(day) OVER (
            PARTITION BY household_key
            ORDER BY day
        ) AS days_since_previous_visit
    FROM visit_days
),

basket_history AS (
    SELECT
        c.as_of_day,
        b.household_key,

        c.as_of_day - MAX(b.day) AS recency_days,

        COUNT(*) AS baskets_90d,

        COUNT(*) FILTER (
            WHERE b.day >= c.as_of_day - 29
        ) AS baskets_30d,

        COUNT(*) FILTER (
            WHERE b.day BETWEEN c.as_of_day - 59
                            AND c.as_of_day - 30
        ) AS baskets_previous_30d,

        SUM(b.basket_sales) AS sales_90d,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day >= c.as_of_day - 29
            ), 0
        ) AS sales_30d,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day BETWEEN c.as_of_day - 59
                                AND c.as_of_day - 30
            ), 0
        ) AS sales_previous_30d,

        AVG(b.basket_sales) AS avg_basket_value_90d,

        STDDEV_SAMP(b.basket_sales)
            AS basket_value_volatility_90d,

        AVG(b.distinct_products::NUMERIC)
            AS avg_product_diversity_90d,

        COUNT(DISTINCT b.store_id)
            AS distinct_stores_90d,

        SUM(b.discount_amount)
            AS discount_amount_90d,

        SUM(b.basket_sales + b.discount_amount)
            AS gross_value_90d

    FROM cutoffs c
    JOIN analytics.baskets b
        ON b.day BETWEEN c.as_of_day - 89
                     AND c.as_of_day

    GROUP BY
        c.as_of_day,
        b.household_key
),

gap_history AS (
    SELECT
        c.as_of_day,
        g.household_key,

        AVG(g.days_since_previous_visit::NUMERIC)
            AS avg_days_between_visits_90d,

        STDDEV_SAMP(g.days_since_previous_visit::NUMERIC)
            AS visit_interval_volatility_90d

    FROM cutoffs c
    JOIN visit_gaps g
        ON g.day BETWEEN c.as_of_day - 89
                     AND c.as_of_day

    GROUP BY
        c.as_of_day,
        g.household_key
)

SELECT
    h.as_of_day,
    h.household_key,

    h.recency_days,
    h.baskets_90d,
    h.baskets_30d,
    h.baskets_previous_30d,

    h.sales_90d,
    h.sales_30d,
    h.sales_previous_30d,

    (h.sales_30d - h.sales_previous_30d)
        / NULLIF(h.sales_previous_30d, 0)
        AS sales_growth_30d,

    h.avg_basket_value_90d,
    h.basket_value_volatility_90d,
    h.avg_product_diversity_90d,
    h.distinct_stores_90d,

    h.discount_amount_90d
        / NULLIF(h.gross_value_90d, 0)
        AS discount_share_90d,

    g.avg_days_between_visits_90d,
    g.visit_interval_volatility_90d

FROM basket_history h
LEFT JOIN gap_history g
    ON h.as_of_day = g.as_of_day
   AND h.household_key = g.household_key;


CREATE UNIQUE INDEX household_snapshots_key_idx
    ON analytics.household_snapshots (
        household_key,
        as_of_day
    );


CREATE VIEW analytics.repurchase_7d AS
SELECT
    s.household_key,
    s.as_of_day,

    EXISTS (
        SELECT 1
        FROM analytics.baskets b
        WHERE b.household_key = s.household_key
          AND b.day BETWEEN s.as_of_day + 1
                        AND s.as_of_day + 7
    ) AS repurchased_7d

FROM analytics.household_snapshots s;