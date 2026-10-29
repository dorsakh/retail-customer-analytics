-- Business KPIs per 28-day period (four whole weeks, not calendar months)
-- Period 1 starts on day 1; a period is complete only if its last day is observed
-- Recorded Sales Value is SUM(sales_value), documented as the amount the retailer
-- receives from the sale. Manufacturer coupons may be reimbursed to the retailer,
-- so it is not necessarily what customers paid. It includes fuel and is not net
-- revenue or profit; the source records no returns, refunds, cancellations, tax,
-- or cost
-- Baskets include zero-value baskets, which are also counted separately
-- Average basket value = Recorded Sales Value / all baskets in the period
-- Discount fields are reported separately as recorded amounts (sign reversed so
-- discounts are positive); no combined customer-discount rate is derived
-- Panel-ramp periods (at least 1% of households first observed) are retained
-- but should be excluded from business-growth interpretation
-- No item-unit metrics: fuel quantities are not comparable with product units

WITH observation_window AS (
    SELECT
        MAX(day) AS last_observed_day,
        COUNT(DISTINCT household_key) AS panel_households
    FROM analytics.baskets
),

periods AS (
    SELECT
        p.period_number,
        1 + 28 * (p.period_number - 1) AS start_day,
        28 * p.period_number AS end_day
    FROM observation_window o
    CROSS JOIN generate_series(
        1,
        (o.last_observed_day + 27) / 28
    ) AS p(period_number)
),

basket_activity AS (
    SELECT
        (day - 1) / 28 + 1 AS period_number,
        COUNT(*) AS baskets,
        COUNT(*) FILTER (
            WHERE basket_sales = 0
        ) AS zero_value_baskets,
        COUNT(DISTINCT household_key) AS active_households,
        SUM(basket_sales) AS recorded_sales_value
    FROM analytics.baskets
    GROUP BY (day - 1) / 28 + 1
),

line_activity AS (
    SELECT
        (t.day - 1) / 28 + 1 AS period_number,
        SUM(t.sales_value) FILTER (
            WHERE p.sub_commodity_desc = 'GASOLINE-REG UNLEADED'
        ) AS fuel_sales_value,
        -SUM(COALESCE(t.retail_disc, 0)) AS loyalty_discount,
        -SUM(COALESCE(t.coupon_match_disc, 0)) AS coupon_match_discount,
        -SUM(COALESCE(t.coupon_disc, 0)) AS manufacturer_coupon_discount
    FROM core.transaction_items t
    LEFT JOIN core.products p
        ON t.product_id = p.product_id
    GROUP BY (t.day - 1) / 28 + 1
),

first_purchases AS (
    SELECT
        household_key,
        MIN(day) AS first_purchase_day
    FROM analytics.baskets
    GROUP BY household_key
),

first_observed AS (
    SELECT
        (first_purchase_day - 1) / 28 + 1 AS period_number,
        COUNT(*) AS first_observed_households
    FROM first_purchases
    GROUP BY (first_purchase_day - 1) / 28 + 1
)

SELECT
    p.period_number,
    p.start_day,
    p.end_day,
    LEAST(p.end_day, o.last_observed_day) - p.start_day + 1
        AS observed_days,
    p.end_day <= o.last_observed_day AS is_complete,

    COALESCE(f.first_observed_households, 0)
        >= 0.01 * o.panel_households AS is_panel_ramp,

    COALESCE(f.first_observed_households, 0)
        AS first_observed_households,

    COALESCE(a.active_households, 0) AS active_households,
    COALESCE(a.baskets, 0) AS baskets,
    COALESCE(a.zero_value_baskets, 0) AS zero_value_baskets,

    ROUND(COALESCE(a.recorded_sales_value, 0), 2)
        AS recorded_sales_value,

    ROUND(COALESCE(l.fuel_sales_value, 0), 2)
        AS fuel_sales_value,

    ROUND(
        100.0 * COALESCE(l.fuel_sales_value, 0)
        / NULLIF(a.recorded_sales_value, 0),
        2
    ) AS fuel_share_pct,

    ROUND(
        a.recorded_sales_value / NULLIF(a.active_households, 0),
        2
    ) AS sales_per_active_household,

    ROUND(
        a.baskets::NUMERIC / NULLIF(a.active_households, 0),
        2
    ) AS baskets_per_active_household,

    ROUND(
        a.recorded_sales_value / NULLIF(a.baskets, 0),
        2
    ) AS average_basket_value,

    ROUND(COALESCE(l.loyalty_discount, 0), 2) AS loyalty_discount,
    ROUND(COALESCE(l.coupon_match_discount, 0), 2) AS coupon_match_discount,
    ROUND(COALESCE(l.manufacturer_coupon_discount, 0), 2)
        AS manufacturer_coupon_discount

FROM periods p

CROSS JOIN observation_window o

LEFT JOIN basket_activity a
    ON p.period_number = a.period_number

LEFT JOIN line_activity l
    ON p.period_number = l.period_number

LEFT JOIN first_observed f
    ON p.period_number = f.period_number

ORDER BY p.period_number;
