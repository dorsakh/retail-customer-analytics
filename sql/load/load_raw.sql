DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM raw.campaign_desc)
       OR EXISTS (SELECT 1 FROM raw.campaign_table)
       OR EXISTS (SELECT 1 FROM raw.coupon_redempt)
       OR EXISTS (SELECT 1 FROM raw.coupon)
       OR EXISTS (SELECT 1 FROM raw.hh_demographic)
       OR EXISTS (SELECT 1 FROM raw.product)
       OR EXISTS (SELECT 1 FROM raw.transaction_data)
    THEN
        RAISE EXCEPTION
            'Raw tables already contain data. Import aborted to prevent duplicates.';
    END IF;
END
$$;

\copy raw.campaign_desc FROM 'data/raw/complete_journey/campaign_desc.csv' WITH (FORMAT csv, HEADER true)
\copy raw.campaign_table FROM 'data/raw/complete_journey/campaign_table.csv' WITH (FORMAT csv, HEADER true)
\copy raw.coupon_redempt FROM 'data/raw/complete_journey/coupon_redempt.csv' WITH (FORMAT csv, HEADER true)
\copy raw.coupon FROM 'data/raw/complete_journey/coupon.csv' WITH (FORMAT csv, HEADER true)
\copy raw.hh_demographic FROM 'data/raw/complete_journey/hh_demographic.csv' WITH (FORMAT csv, HEADER true)
\copy raw.product FROM 'data/raw/complete_journey/product.csv' WITH (FORMAT csv, HEADER true)
\copy raw.transaction_data FROM 'data/raw/complete_journey/transaction_data.csv' WITH (FORMAT csv, HEADER true)