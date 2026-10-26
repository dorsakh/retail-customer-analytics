-- Reconcile transaction aggregates across raw and core layers

WITH raw_totals AS (
    SELECT
        COUNT(*)::NUMERIC AS line_items,
        COUNT(DISTINCT basket_id)::NUMERIC AS baskets,
        SUM(quantity::NUMERIC) AS quantity,
        SUM(sales_value::NUMERIC) AS sales_value,
        SUM(retail_disc::NUMERIC) AS retail_disc,
        SUM(coupon_disc::NUMERIC) AS coupon_disc,
        SUM(coupon_match_disc::NUMERIC) AS coupon_match_disc
    FROM raw.transaction_data
),
core_totals AS (
    SELECT
        COUNT(*)::NUMERIC AS line_items,
        COUNT(DISTINCT basket_id)::NUMERIC AS baskets,
        SUM(quantity::NUMERIC) AS quantity,
        SUM(sales_value) AS sales_value,
        SUM(retail_disc) AS retail_disc,
        SUM(coupon_disc) AS coupon_disc,
        SUM(coupon_match_disc) AS coupon_match_disc
    FROM core.transaction_items
)
SELECT
    metric,
    raw_value,
    core_value,
    CASE
        WHEN raw_value IS NOT DISTINCT FROM core_value
        THEN 'PASS'
        ELSE 'FAIL'
    END AS validation
FROM raw_totals r
CROSS JOIN core_totals c
CROSS JOIN LATERAL (
    VALUES
        ('line_items', r.line_items, c.line_items),
        ('baskets', r.baskets, c.baskets),
        ('quantity', r.quantity, c.quantity),
        ('sales_value', r.sales_value, c.sales_value),
        ('retail_disc', r.retail_disc, c.retail_disc),
        ('coupon_disc', r.coupon_disc, c.coupon_disc),
        ('coupon_match_disc', r.coupon_match_disc, c.coupon_match_disc)
) AS metrics(metric, raw_value, core_value);


-- Profile quantity and sales distributions

SELECT
    ROUND(AVG(quantity::NUMERIC), 2) AS mean_quantity,
    PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY quantity
    ) AS median_quantity,
    PERCENTILE_CONT(0.99) WITHIN GROUP (
        ORDER BY quantity
    ) AS p99_quantity,
    MAX(quantity) AS max_quantity,
    COUNT(*) FILTER (
        WHERE quantity > 100
    ) AS rows_above_100_units,
    COUNT(*) FILTER (
        WHERE quantity <= 0
    ) AS nonpositive_quantity_rows,
    COUNT(*) FILTER (
        WHERE sales_value < 0
    ) AS negative_sales_rows,
    COUNT(*) FILTER (
        WHERE sales_value <> ROUND(sales_value, 2)
    ) AS sales_values_beyond_cents
FROM core.transaction_items;


-- Inspect transactions with the largest quantities

SELECT
    t.quantity,
    t.sales_value,
    t.product_id,
    p.department,
    p.commodity_desc,
    t.basket_id,
    t.day
FROM core.transaction_items t
LEFT JOIN core.products p
    ON t.product_id = p.product_id
ORDER BY t.quantity DESC
LIMIT 10;