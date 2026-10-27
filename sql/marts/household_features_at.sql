-- Generate household features at any observation day
-- Uses only purchases on or before p_as_of_day
-- Does not calculate or access future repurchase labels

CREATE OR REPLACE FUNCTION analytics.household_features_at(
    p_as_of_day INTEGER
)
RETURNS TABLE (
    as_of_day INTEGER,
    household_key TEXT,
    recency_days INTEGER,
    baskets_90d BIGINT,
    baskets_30d BIGINT,
    baskets_previous_30d BIGINT,
    sales_90d NUMERIC,
    sales_30d NUMERIC,
    sales_previous_30d NUMERIC,
    sales_growth_30d NUMERIC,
    avg_basket_value_90d NUMERIC,
    basket_value_volatility_90d NUMERIC,
    avg_product_diversity_90d NUMERIC,
    distinct_stores_90d BIGINT,
    discount_share_90d NUMERIC,
    avg_days_between_visits_90d NUMERIC,
    visit_interval_volatility_90d NUMERIC
)
LANGUAGE SQL
STABLE
AS $$
WITH visit_days AS (
    SELECT DISTINCT
        b.household_key,
        b.day
    FROM analytics.baskets b
    WHERE b.day BETWEEN p_as_of_day - 89 AND p_as_of_day
),

visit_gaps AS (
    SELECT
        v.household_key,
        v.day - LAG(v.day) OVER (
            PARTITION BY v.household_key
            ORDER BY v.day
        ) AS days_since_previous_visit
    FROM visit_days v
),

basket_history AS (
    SELECT
        b.household_key,

        p_as_of_day - MAX(b.day) AS recency_days,

        COUNT(*) AS baskets_90d,

        COUNT(*) FILTER (
            WHERE b.day >= p_as_of_day - 29
        ) AS baskets_30d,

        COUNT(*) FILTER (
            WHERE b.day BETWEEN p_as_of_day - 59
                            AND p_as_of_day - 30
        ) AS baskets_previous_30d,

        SUM(b.basket_sales) AS sales_90d,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day >= p_as_of_day - 29
            ), 0
        ) AS sales_30d,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day BETWEEN p_as_of_day - 59
                                AND p_as_of_day - 30
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

    FROM analytics.baskets b

    WHERE b.day BETWEEN p_as_of_day - 89 AND p_as_of_day

    GROUP BY b.household_key
),

gap_history AS (
    SELECT
        v.household_key,

        AVG(v.days_since_previous_visit::NUMERIC)
            AS avg_days_between_visits_90d,

        STDDEV_SAMP(v.days_since_previous_visit::NUMERIC)
            AS visit_interval_volatility_90d

    FROM visit_gaps v
    GROUP BY v.household_key
)

SELECT
    p_as_of_day,
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
    ON h.household_key = g.household_key;

$$;