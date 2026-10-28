-- Point-in-time features for the retention/lapse extension.
-- Unlike the v1 90-day scorer, retain every household with a purchase
-- on or before the requested day; dormant households remain in the roster.
-- All source dates used below are <= p_as_of_day.

CREATE INDEX IF NOT EXISTS retention_items_day_household_idx
    ON core.transaction_items(day, household_key);

CREATE INDEX IF NOT EXISTS retention_redemption_day_household_idx
    ON core.coupon_redemptions(day, household_key);

CREATE OR REPLACE FUNCTION analytics.retention_features_at(p_as_of_day INTEGER)
RETURNS TABLE (
    as_of_day INTEGER,
    household_key TEXT,
    recency_days INTEGER,
    lifetime_baskets BIGINT,
    baskets_90d BIGINT,
    baskets_30d BIGINT,
    baskets_prev_30d BIGINT,
    sales_90d DOUBLE PRECISION,
    sales_30d DOUBLE PRECISION,
    sales_prev_30d DOUBLE PRECISION,
    avg_basket_value_90d DOUBLE PRECISION,
    basket_value_volatility_90d DOUBLE PRECISION,
    discount_share_90d DOUBLE PRECISION,
    distinct_stores_90d BIGINT,
    avg_product_diversity_90d DOUBLE PRECISION,
    typical_visit_gap_90d DOUBLE PRECISION,
    visit_gap_volatility_90d DOUBLE PRECISION,
    overdue_ratio DOUBLE PRECISION,
    department_diversity_90d BIGINT,
    grocery_sales_share_90d DOUBLE PRECISION,
    private_brand_share_90d DOUBLE PRECISION,
    prior_campaigns BIGINT,
    coupon_redemptions_90d BIGINT,
    age_desc TEXT,
    income_desc TEXT,
    household_size_desc TEXT
)
LANGUAGE SQL STABLE AS $$
WITH known AS (
    SELECT b.household_key,
           MAX(b.day) AS last_day,
           COUNT(*)::BIGINT AS lifetime_baskets
    FROM analytics.baskets b
    WHERE b.day <= p_as_of_day
    GROUP BY b.household_key
),
recent_baskets AS (
    SELECT b.* FROM analytics.baskets b
    WHERE b.day BETWEEN p_as_of_day - 89 AND p_as_of_day
),
basket_agg AS (
    SELECT b.household_key,
           COUNT(*)::BIGINT AS baskets_90d,
           COUNT(*) FILTER (WHERE b.day >= p_as_of_day - 29)::BIGINT AS baskets_30d,
           COUNT(*) FILTER (WHERE b.day BETWEEN p_as_of_day - 59 AND p_as_of_day - 30)::BIGINT AS baskets_prev_30d,
           SUM(b.basket_sales)::DOUBLE PRECISION AS sales_90d,
           COALESCE(SUM(b.basket_sales) FILTER (WHERE b.day >= p_as_of_day - 29), 0)::DOUBLE PRECISION AS sales_30d,
           COALESCE(SUM(b.basket_sales) FILTER (WHERE b.day BETWEEN p_as_of_day - 59 AND p_as_of_day - 30), 0)::DOUBLE PRECISION AS sales_prev_30d,
           AVG(b.basket_sales)::DOUBLE PRECISION AS avg_basket_value_90d,
           STDDEV_SAMP(b.basket_sales)::DOUBLE PRECISION AS basket_value_volatility_90d,
           (SUM(b.discount_amount) / NULLIF(SUM(b.basket_sales + b.discount_amount), 0))::DOUBLE PRECISION AS discount_share_90d,
           COUNT(DISTINCT b.store_id)::BIGINT AS distinct_stores_90d,
           AVG(b.distinct_products)::DOUBLE PRECISION AS avg_product_diversity_90d
    FROM recent_baskets b
    GROUP BY b.household_key
),
visit_days AS (
    SELECT DISTINCT b.household_key, b.day FROM recent_baskets b
),
gaps AS (
    SELECT household_key,
           day - LAG(day) OVER (PARTITION BY household_key ORDER BY day) AS gap_days
    FROM visit_days
),
gap_agg AS (
    SELECT household_key,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap_days)::DOUBLE PRECISION AS typical_visit_gap_90d,
           STDDEV_SAMP(gap_days)::DOUBLE PRECISION AS visit_gap_volatility_90d
    FROM gaps
    WHERE gap_days IS NOT NULL
    GROUP BY household_key
),
item_agg AS (
    SELECT t.household_key,
           COUNT(DISTINCT p.department)::BIGINT AS department_diversity_90d,
           (SUM(t.sales_value) FILTER (WHERE UPPER(p.department) = 'GROCERY') /
                NULLIF(SUM(t.sales_value), 0))::DOUBLE PRECISION AS grocery_sales_share_90d,
           (SUM(t.sales_value) FILTER (WHERE UPPER(COALESCE(p.brand, '')) LIKE '%PRIVATE%') /
                NULLIF(SUM(t.sales_value), 0))::DOUBLE PRECISION AS private_brand_share_90d
    FROM core.transaction_items t
    JOIN core.products p ON p.product_id = t.product_id
    WHERE t.day BETWEEN p_as_of_day - 89 AND p_as_of_day
    GROUP BY t.household_key
),
campaign_agg AS (
    SELECT ch.household_key, COUNT(DISTINCT ch.campaign)::BIGINT AS prior_campaigns
    FROM core.campaign_households ch
    JOIN core.campaigns c ON c.campaign = ch.campaign
    WHERE c.start_day <= p_as_of_day
    GROUP BY ch.household_key
),
redemption_agg AS (
    SELECT household_key, COUNT(*)::BIGINT AS coupon_redemptions_90d
    FROM core.coupon_redemptions
    WHERE day BETWEEN p_as_of_day - 89 AND p_as_of_day
    GROUP BY household_key
)
SELECT p_as_of_day,
       k.household_key,
       p_as_of_day - k.last_day,
       k.lifetime_baskets,
       COALESCE(b.baskets_90d, 0),
       COALESCE(b.baskets_30d, 0),
       COALESCE(b.baskets_prev_30d, 0),
       COALESCE(b.sales_90d, 0),
       COALESCE(b.sales_30d, 0),
       COALESCE(b.sales_prev_30d, 0),
       b.avg_basket_value_90d,
       b.basket_value_volatility_90d,
       b.discount_share_90d,
       COALESCE(b.distinct_stores_90d, 0),
       b.avg_product_diversity_90d,
       g.typical_visit_gap_90d,
       g.visit_gap_volatility_90d,
       ((p_as_of_day - k.last_day)::DOUBLE PRECISION /
           NULLIF(g.typical_visit_gap_90d, 0)) AS overdue_ratio,
       COALESCE(i.department_diversity_90d, 0),
       COALESCE(i.grocery_sales_share_90d, 0),
       COALESCE(i.private_brand_share_90d, 0),
       COALESCE(c.prior_campaigns, 0),
       COALESCE(r.coupon_redemptions_90d, 0),
       h.age_desc, h.income_desc, h.household_size_desc
FROM known k
JOIN core.households h USING (household_key)
LEFT JOIN basket_agg b USING (household_key)
LEFT JOIN gap_agg g USING (household_key)
LEFT JOIN item_agg i USING (household_key)
LEFT JOIN campaign_agg c USING (household_key)
LEFT JOIN redemption_agg r USING (household_key);
$$;
