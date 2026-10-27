-- Read-only presentation tables for Behind the Basket.
-- Source records remain in the existing analytics schema.

CREATE TABLE IF NOT EXISTS analytics.explorer_profiles (
    household_key TEXT NOT NULL,
    as_of_day INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    predicted_probability DOUBLE PRECISION NOT NULL
        CHECK (predicted_probability BETWEEN 0 AND 1),
    propensity_rank INTEGER NOT NULL CHECK (propensity_rank > 0),
    score_decile INTEGER NOT NULL CHECK (score_decile BETWEEN 1 AND 10),
    features JSONB NOT NULL,
    dna JSONB NOT NULL,
    purchase_history JSONB NOT NULL,
    PRIMARY KEY (household_key, as_of_day, model_version)
);

CREATE TABLE IF NOT EXISTS analytics.explorer_game_cases (
    household_key TEXT NOT NULL,
    as_of_day INTEGER NOT NULL,
    predicted_probability DOUBLE PRECISION NOT NULL
        CHECK (predicted_probability BETWEEN 0 AND 1),
    repurchased_7d BOOLEAN NOT NULL,
    baseline_rank INTEGER NOT NULL CHECK (baseline_rank > 0),
    features JSONB NOT NULL,
    purchase_history JSONB NOT NULL,
    PRIMARY KEY (household_key, as_of_day)
);

CREATE INDEX IF NOT EXISTS explorer_game_probability_idx
    ON analytics.explorer_game_cases (predicted_probability);
