DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM core.households)
       OR EXISTS (SELECT 1 FROM core.products)
       OR EXISTS (SELECT 1 FROM core.campaigns)
       OR EXISTS (SELECT 1 FROM core.campaign_households)
       OR EXISTS (SELECT 1 FROM core.coupon_offers)
       OR EXISTS (SELECT 1 FROM core.coupon_products)
       OR EXISTS (SELECT 1 FROM core.coupon_redemptions)
       OR EXISTS (SELECT 1 FROM core.transaction_items)
    THEN
        RAISE EXCEPTION
            'Core tables already contain data; loading aborted.';
    END IF;
END
$$;


INSERT INTO core.products (
    product_id,
    manufacturer,
    department,
    brand,
    commodity_desc,
    sub_commodity_desc,
    curr_size_of_product
)
SELECT
    product_id,
    manufacturer,
    department,
    brand,
    commodity_desc,
    sub_commodity_desc,
    curr_size_of_product
FROM raw.product;


INSERT INTO core.households (
    household_key,
    age_desc,
    marital_status_code,
    income_desc,
    homeowner_desc,
    hh_comp_desc,
    household_size_desc,
    kid_category_desc
)
SELECT
    h.household_key,
    d.age_desc,
    d.marital_status_code,
    d.income_desc,
    d.homeowner_desc,
    d.hh_comp_desc,
    d.household_size_desc,
    d.kid_category_desc
FROM (
    SELECT household_key FROM raw.transaction_data
    UNION
    SELECT household_key FROM raw.campaign_table
    UNION
    SELECT household_key FROM raw.coupon_redempt
    UNION
    SELECT household_key FROM raw.hh_demographic
) h
LEFT JOIN raw.hh_demographic d
    ON h.household_key = d.household_key;


INSERT INTO core.campaigns (
    campaign,
    description,
    start_day,
    end_day
)
SELECT
    campaign,
    description,
    start_day::INTEGER,
    end_day::INTEGER
FROM raw.campaign_desc;


INSERT INTO core.campaign_households (
    household_key,
    campaign,
    description
)
SELECT
    household_key,
    campaign,
    description
FROM raw.campaign_table;


INSERT INTO core.coupon_offers (
    coupon_upc,
    campaign
)
SELECT DISTINCT
    coupon_upc,
    campaign
FROM raw.coupon;


INSERT INTO core.coupon_products (
    coupon_upc,
    campaign,
    product_id
)
SELECT DISTINCT
    coupon_upc,
    campaign,
    product_id
FROM raw.coupon;


INSERT INTO core.coupon_redemptions (
    household_key,
    day,
    coupon_upc,
    campaign
)
SELECT
    household_key,
    day::INTEGER,
    coupon_upc,
    campaign
FROM raw.coupon_redempt;


INSERT INTO core.transaction_items (
    household_key,
    basket_id,
    day,
    product_id,
    quantity,
    sales_value,
    store_id,
    retail_disc,
    trans_time,
    week_no,
    coupon_disc,
    coupon_match_disc
)
SELECT
    household_key,
    basket_id,
    day::INTEGER,
    product_id,
    quantity::INTEGER,
    sales_value::NUMERIC,
    store_id,
    retail_disc::NUMERIC,
    trans_time,
    week_no::INTEGER,
    coupon_disc::NUMERIC,
    coupon_match_disc::NUMERIC
FROM raw.transaction_data;