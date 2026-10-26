-- Checking the uniqueness of candidate primary keys

SELECT
    'product.product_id' AS candidate_key,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT product_id) AS distinct_keys,
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(product_id), '') IS NULL
    ) AS missing_keys
FROM raw.product

UNION ALL

SELECT
    'hh_demographic.household_key',
    COUNT(*),
    COUNT(DISTINCT household_key),
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(household_key), '') IS NULL
    )
FROM raw.hh_demographic

UNION ALL

SELECT
    'campaign_desc.campaign',
    COUNT(*),
    COUNT(DISTINCT campaign),
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(campaign), '') IS NULL
    )
FROM raw.campaign_desc

UNION ALL

SELECT
    'campaign_table.(household_key, campaign)',
    COUNT(*),
    COUNT(DISTINCT (household_key, campaign)),
    COUNT(*) FILTER (
        WHERE household_key IS NULL OR campaign IS NULL
    )
FROM raw.campaign_table

UNION ALL

SELECT
    'coupon.(coupon_upc, product_id, campaign)',
    COUNT(*),
    COUNT(DISTINCT (coupon_upc, product_id, campaign)),
    COUNT(*) FILTER (
        WHERE coupon_upc IS NULL
           OR product_id IS NULL
           OR campaign IS NULL
    )
FROM raw.coupon;


-- Checking whether each basket belongs to one household, one day, one store, and one transaction time

SELECT
    COUNT(*) AS inconsistent_baskets
FROM (
    SELECT basket_id
    FROM raw.transaction_data
    GROUP BY basket_id
    HAVING COUNT(DISTINCT household_key) > 1
        OR COUNT(DISTINCT day) > 1
        OR COUNT(DISTINCT store_id) > 1
        OR COUNT(DISTINCT trans_time) > 1
) AS basket_checks;


-- Checking required identifiers and numeric values

SELECT
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(household_key), '') IS NULL
           OR NULLIF(TRIM(basket_id), '') IS NULL
           OR NULLIF(TRIM(product_id), '') IS NULL
    ) AS rows_with_missing_identifiers,

    COUNT(*) FILTER (
        WHERE day IS NOT NULL
          AND NOT pg_input_is_valid(day, 'integer')
    ) AS invalid_days,

    COUNT(*) FILTER (
        WHERE quantity IS NOT NULL
          AND NOT pg_input_is_valid(quantity, 'integer')
    ) AS invalid_quantities,

    COUNT(*) FILTER (
        WHERE sales_value IS NOT NULL
          AND NOT pg_input_is_valid(sales_value, 'numeric')
    ) AS invalid_sales_values

FROM raw.transaction_data;


-- Checking product references against the product catalog

SELECT
    COUNT(*) AS unknown_product_ids
FROM (
    SELECT product_id
    FROM raw.transaction_data
    WHERE product_id IS NOT NULL

    EXCEPT

    SELECT product_id
    FROM raw.product
    WHERE product_id IS NOT NULL
) AS missing_products;

-- Examine duplicate coupon mappings

WITH repeated_mappings AS (
    SELECT
        coupon_upc,
        product_id,
        campaign,
        COUNT(*) AS occurrences
    FROM raw.coupon
    GROUP BY coupon_upc, product_id, campaign
    HAVING COUNT(*) > 1
)
SELECT
    COUNT(*) AS repeated_mapping_groups,
    COALESCE(SUM(occurrences - 1), 0) AS excess_rows,
    COALESCE(MAX(occurrences), 0) AS max_occurrences
FROM repeated_mappings;


-- Inspect the most frequently repeated mappings

SELECT
    coupon_upc,
    product_id,
    campaign,
    COUNT(*) AS occurrences
FROM raw.coupon
GROUP BY coupon_upc, product_id, campaign
HAVING COUNT(*) > 1
ORDER BY occurrences DESC, coupon_upc
LIMIT 10;


-- Validate references between source tables

SELECT
    'Coupon products missing from catalog' AS check_name,
    COUNT(*) AS unmatched_rows
FROM raw.coupon c
WHERE NOT EXISTS (
    SELECT 1
    FROM raw.product p
    WHERE p.product_id = c.product_id
)

UNION ALL

SELECT
    'Coupon campaigns missing from campaign descriptions',
    COUNT(*)
FROM raw.coupon c
WHERE NOT EXISTS (
    SELECT 1
    FROM raw.campaign_desc d
    WHERE d.campaign = c.campaign
)

UNION ALL

SELECT
    'Household campaign assignments missing campaign descriptions',
    COUNT(*)
FROM raw.campaign_table ct
WHERE NOT EXISTS (
    SELECT 1
    FROM raw.campaign_desc d
    WHERE d.campaign = ct.campaign
)

UNION ALL

SELECT
    'Coupon redemptions missing coupon definitions',
    COUNT(*)
FROM raw.coupon_redempt r
WHERE NOT EXISTS (
    SELECT 1
    FROM raw.coupon c
    WHERE c.coupon_upc = r.coupon_upc
      AND c.campaign = r.campaign
);