CREATE TABLE IF NOT EXISTS analytics.customer_predictions (
    household_key TEXT NOT NULL,

    as_of_day INTEGER NOT NULL
        CHECK (as_of_day > 0),

    model_version TEXT NOT NULL,

    predicted_probability DOUBLE PRECISION NOT NULL
        CHECK (
            predicted_probability >= 0
            AND predicted_probability <= 1
        ),

    score_decile INTEGER NOT NULL
        CHECK (score_decile BETWEEN 1 AND 10),

    propensity_rank INTEGER NOT NULL
        CHECK (propensity_rank > 0),

    scored_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        household_key,
        as_of_day,
        model_version
    )
);


CREATE INDEX IF NOT EXISTS customer_predictions_lookup_idx
ON analytics.customer_predictions (
    as_of_day,
    model_version,
    propensity_rank
);