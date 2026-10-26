WITH expected (table_name, expected_rows) AS (
    VALUES
        ('campaign_desc', 30::BIGINT),
        ('campaign_table', 7208::BIGINT),
        ('coupon_redempt', 2318::BIGINT),
        ('coupon', 124548::BIGINT),
        ('hh_demographic', 801::BIGINT),
        ('product', 92353::BIGINT),
        ('transaction_data', 2595732::BIGINT)
),
actual AS (
    SELECT 'campaign_desc' AS table_name, COUNT(*) AS actual_rows
    FROM raw.campaign_desc

    UNION ALL

    SELECT 'campaign_table', COUNT(*)
    FROM raw.campaign_table

    UNION ALL

    SELECT 'coupon_redempt', COUNT(*)
    FROM raw.coupon_redempt

    UNION ALL

    SELECT 'coupon', COUNT(*)
    FROM raw.coupon

    UNION ALL

    SELECT 'hh_demographic', COUNT(*)
    FROM raw.hh_demographic

    UNION ALL

    SELECT 'product', COUNT(*)
    FROM raw.product

    UNION ALL

    SELECT 'transaction_data', COUNT(*)
    FROM raw.transaction_data
)
SELECT
    e.table_name,
    e.expected_rows,
    a.actual_rows,
    CASE
        WHEN e.expected_rows = a.actual_rows THEN 'PASS'
        ELSE 'FAIL'
    END AS validation
FROM expected e
JOIN actual a USING (table_name)
ORDER BY e.table_name;