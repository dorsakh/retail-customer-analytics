CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE core.households (
    household_key TEXT PRIMARY KEY,
    age_desc TEXT,
    marital_status_code TEXT,
    income_desc TEXT,
    homeowner_desc TEXT,
    hh_comp_desc TEXT,
    household_size_desc TEXT,
    kid_category_desc TEXT
);

CREATE TABLE core.products (
    product_id TEXT PRIMARY KEY,
    manufacturer TEXT,
    department TEXT,
    brand TEXT,
    commodity_desc TEXT,
    sub_commodity_desc TEXT,
    curr_size_of_product TEXT
);

CREATE TABLE core.campaigns (
    campaign TEXT PRIMARY KEY,
    description TEXT,
    start_day INTEGER,
    end_day INTEGER
);

CREATE TABLE core.campaign_households (
    household_key TEXT NOT NULL
        REFERENCES core.households(household_key),
    campaign TEXT NOT NULL
        REFERENCES core.campaigns(campaign),
    description TEXT,
    PRIMARY KEY (household_key, campaign)
);

CREATE TABLE core.coupon_offers (
    coupon_upc TEXT NOT NULL,
    campaign TEXT NOT NULL
        REFERENCES core.campaigns(campaign),
    PRIMARY KEY (coupon_upc, campaign)
);

CREATE TABLE core.coupon_products (
    coupon_upc TEXT NOT NULL,
    campaign TEXT NOT NULL,
    product_id TEXT NOT NULL
        REFERENCES core.products(product_id),
    PRIMARY KEY (coupon_upc, campaign, product_id),
    FOREIGN KEY (coupon_upc, campaign)
        REFERENCES core.coupon_offers(coupon_upc, campaign)
);

CREATE TABLE core.coupon_redemptions (
    redemption_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    household_key TEXT NOT NULL
        REFERENCES core.households(household_key),
    day INTEGER NOT NULL,
    coupon_upc TEXT NOT NULL,
    campaign TEXT NOT NULL,
    FOREIGN KEY (coupon_upc, campaign)
        REFERENCES core.coupon_offers(coupon_upc, campaign)
);

CREATE TABLE core.transaction_items (
    transaction_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    household_key TEXT NOT NULL
        REFERENCES core.households(household_key),
    basket_id TEXT NOT NULL,
    day INTEGER NOT NULL,
    product_id TEXT NOT NULL
        REFERENCES core.products(product_id),
    quantity INTEGER,
    sales_value NUMERIC,
    store_id TEXT,
    retail_disc NUMERIC,
    trans_time TEXT,
    week_no INTEGER,
    coupon_disc NUMERIC,
    coupon_match_disc NUMERIC
);