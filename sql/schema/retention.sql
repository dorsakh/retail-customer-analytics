-- Separate v2 results: no mutation of saved v1 predictions or explorer views.
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.retention_scores (
    household_key TEXT NOT NULL,
    as_of_day INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    horizon_days INTEGER NOT NULL CHECK (horizon_days IN (7, 14, 28)),
    segment TEXT NOT NULL,
    lapse_probability DOUBLE PRECISION CHECK (lapse_probability BETWEEN 0 AND 1),
    risk_rank INTEGER CHECK (risk_rank > 0),
    recency_days INTEGER NOT NULL,
    baskets_90d BIGINT NOT NULL,
    typical_visit_gap_90d DOUBLE PRECISION,
    overdue_ratio DOUBLE PRECISION,
    sales_90d DOUBLE PRECISION,
    scored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (household_key, as_of_day, model_version)
);

CREATE INDEX IF NOT EXISTS retention_scores_directory_idx
    ON analytics.retention_scores(as_of_day, model_version, risk_rank);
