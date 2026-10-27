DO $$
DECLARE
    mismatch_count BIGINT;
BEGIN
    WITH check_days AS (
        SELECT UNNEST(
            ARRAY[300, 540, 600, 690]
        ) AS as_of_day
    ),

    historical AS (
        SELECT s.*
        FROM analytics.household_snapshots s
        WHERE s.as_of_day IN (
            SELECT as_of_day FROM check_days
        )
    ),

    generated AS (
        SELECT f.*
        FROM check_days d
        CROSS JOIN LATERAL
            analytics.household_features_at(d.as_of_day) f
    ),

    differences AS (
        (
            SELECT * FROM historical
            EXCEPT ALL
            SELECT * FROM generated
        )

        UNION ALL

        (
            SELECT * FROM generated
            EXCEPT ALL
            SELECT * FROM historical
        )
    )

    SELECT COUNT(*)
    INTO mismatch_count
    FROM differences;

    IF mismatch_count > 0 THEN
        RAISE EXCEPTION
            'Feature parity failed: % mismatched rows',
            mismatch_count;
    END IF;

    RAISE NOTICE
        'Feature parity passed for days 300, 540, 600, 690';
END;
$$;