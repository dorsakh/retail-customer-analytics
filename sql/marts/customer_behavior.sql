CREATE SCHEMA IF NOT EXISTS analytics;

CREATE MATERIALIZED VIEW analytics.baskets AS
SELECT
    basket_id,
    MIN(household_key) AS household_key,
    MIN(day) AS day,
    MIN(store_id) AS store_id,
    SUM(sales_value) AS basket_sales,
    COUNT(*) AS product_lines,
    COUNT(DISTINCT product_id) AS distinct_products,
    -SUM(
        COALESCE(retail_disc, 0)
        + COALESCE(coupon_disc, 0)
        + COALESCE(coupon_match_disc, 0)
    ) AS discount_amount
FROM core.transaction_items
GROUP BY basket_id;

CREATE UNIQUE INDEX baskets_basket_id_idx
    ON analytics.baskets (basket_id);

CREATE INDEX baskets_household_day_idx
    ON analytics.baskets (household_key, day);