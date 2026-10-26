CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.campaign_desc (
    description TEXT,
    campaign TEXT,
    start_day TEXT,
    end_day TEXT
);

CREATE TABLE IF NOT EXISTS raw.campaign_table (
    description TEXT,
    household_key TEXT,
    campaign TEXT
);

CREATE TABLE IF NOT EXISTS raw.coupon_redempt (
    household_key TEXT,
    day TEXT,
    coupon_upc TEXT,
    campaign TEXT
);

CREATE TABLE IF NOT EXISTS raw.coupon (
    coupon_upc TEXT,
    product_id TEXT,
    campaign TEXT
);

CREATE TABLE IF NOT EXISTS raw.hh_demographic (
    age_desc TEXT,
    marital_status_code TEXT,
    income_desc TEXT,
    homeowner_desc TEXT,
    hh_comp_desc TEXT,
    household_size_desc TEXT,
    kid_category_desc TEXT,
    household_key TEXT
);

CREATE TABLE IF NOT EXISTS raw.product (
    product_id TEXT,
    manufacturer TEXT,
    department TEXT,
    brand TEXT,
    commodity_desc TEXT,
    sub_commodity_desc TEXT,
    curr_size_of_product TEXT
);

CREATE TABLE IF NOT EXISTS raw.transaction_data (
    household_key TEXT,
    basket_id TEXT,
    day TEXT,
    product_id TEXT,
    quantity TEXT,
    sales_value TEXT,
    store_id TEXT,
    retail_disc TEXT,
    trans_time TEXT,
    week_no TEXT,
    coupon_disc TEXT,
    coupon_match_disc TEXT
);