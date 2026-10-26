-- Campaign-level reach, coupon response, and purchasing behaviour
-- Spending comparisons use equal-length pre-campaign and campaign windows
-- Descriptive associations only, results are not causal lift estimates

WITH observation_bounds AS (
    SELECT
        MIN(day) AS first_day,
        MAX(day) AS last_day
    FROM analytics.baskets
),

campaign_windows AS (
    SELECT
        c.campaign,
        c.description,
        c.start_day,
        c.end_day,
        c.end_day - c.start_day + 1 AS campaign_days,

        c.start_day - (c.end_day - c.start_day + 1)
            AS pre_start_day,

        (
            c.start_day >= o.first_day
            AND c.end_day <= o.last_day
            AND c.end_day >= c.start_day
        ) AS campaign_fully_observed,

        (
            c.start_day - (c.end_day - c.start_day + 1)
                >= o.first_day
            AND c.end_day <= o.last_day
            AND c.end_day >= c.start_day
        ) AS periods_comparable

    FROM core.campaigns c
    CROSS JOIN observation_bounds o
),

targeted_households AS (
    SELECT
        h.household_key,
        w.campaign,
        w.start_day,
        w.end_day,
        w.pre_start_day
    FROM core.campaign_households h
    JOIN campaign_windows w
        ON h.campaign = w.campaign
),

campaign_reach AS (
    SELECT
        campaign,
        COUNT(*) AS targeted_households
    FROM targeted_households
    GROUP BY campaign
),

household_activity AS (
    SELECT
        t.campaign,
        t.household_key,

        COUNT(b.basket_id) FILTER (
            WHERE b.day BETWEEN t.pre_start_day
                            AND t.start_day - 1
        ) AS pre_baskets,

        COUNT(b.basket_id) FILTER (
            WHERE b.day BETWEEN t.start_day
                            AND t.end_day
        ) AS campaign_baskets,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day BETWEEN t.pre_start_day
                                AND t.start_day - 1
            ),
            0
        ) AS pre_sales,

        COALESCE(
            SUM(b.basket_sales) FILTER (
                WHERE b.day BETWEEN t.start_day
                                AND t.end_day
            ),
            0
        ) AS campaign_sales

    FROM targeted_households t

    LEFT JOIN analytics.baskets b
        ON b.household_key = t.household_key
        AND b.day BETWEEN t.pre_start_day AND t.end_day

    GROUP BY
        t.campaign,
        t.household_key,
        t.pre_start_day,
        t.start_day,
        t.end_day
),

campaign_activity AS (
    SELECT
        campaign,

        COUNT(*) FILTER (
            WHERE pre_baskets > 0
        ) AS pre_active_households,

        COUNT(*) FILTER (
            WHERE campaign_baskets > 0
        ) AS campaign_active_households,

        SUM(pre_baskets) AS pre_baskets,
        SUM(campaign_baskets) AS campaign_baskets,

        SUM(pre_sales) AS pre_sales,
        SUM(campaign_sales) AS campaign_sales

    FROM household_activity
    GROUP BY campaign
),

coupon_response AS (
    SELECT
        t.campaign,

        COUNT(r.redemption_id) AS redemption_events,

        COUNT(DISTINCT r.household_key)
            AS redeeming_households

    FROM targeted_households t

    LEFT JOIN core.coupon_redemptions r
        ON r.campaign = t.campaign
        AND r.household_key = t.household_key
        AND r.day BETWEEN t.start_day AND t.end_day

    GROUP BY t.campaign
)

SELECT
    w.campaign,
    w.description,
    w.start_day,
    w.end_day,
    w.campaign_days,

    w.campaign_fully_observed,
    w.periods_comparable,

    COALESCE(reach.targeted_households, 0)
        AS targeted_households,

    COALESCE(r.redeeming_households, 0)
        AS redeeming_households,

    COALESCE(r.redemption_events, 0)
        AS redemption_events,

    CASE
        WHEN w.campaign_fully_observed
        THEN ROUND(
            100.0 * COALESCE(r.redeeming_households, 0)
            / NULLIF(reach.targeted_households, 0),
            2
        )
    END AS household_redemption_rate_pct,

    CASE
        WHEN w.campaign_fully_observed
        THEN ROUND(
            100.0 * COALESCE(a.campaign_active_households, 0)
            / NULLIF(reach.targeted_households, 0),
            2
        )
    END AS campaign_purchase_rate_pct,

    CASE
        WHEN w.periods_comparable
        THEN ROUND(COALESCE(a.pre_sales, 0), 2)
    END AS pre_campaign_revenue,

    CASE
        WHEN w.periods_comparable
        THEN ROUND(COALESCE(a.campaign_sales, 0), 2)
    END AS campaign_revenue,

    CASE
        WHEN w.periods_comparable
        THEN ROUND(
            COALESCE(a.pre_sales, 0)
            / NULLIF(reach.targeted_households, 0),
            2
        )
    END AS pre_revenue_per_household,

    CASE
        WHEN w.periods_comparable
        THEN ROUND(
            COALESCE(a.campaign_sales, 0)
            / NULLIF(reach.targeted_households, 0),
            2
        )
    END AS campaign_revenue_per_household,

    CASE
        WHEN w.periods_comparable
             AND COALESCE(a.pre_sales, 0) > 0
        THEN ROUND(
            100.0 * (a.campaign_sales - a.pre_sales)
            / a.pre_sales,
            2
        )
    END AS spending_change_pct

FROM campaign_windows w

LEFT JOIN campaign_reach reach
    ON w.campaign = reach.campaign

LEFT JOIN campaign_activity a
    ON w.campaign = a.campaign

LEFT JOIN coupon_response r
    ON w.campaign = r.campaign

ORDER BY
    w.start_day,
    w.campaign;