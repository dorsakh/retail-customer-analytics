-- Small, aggregated monitoring outputs. No household-level data is stored here.
CREATE TABLE IF NOT EXISTS analytics.monitoring_reports (
    as_of_day INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    source_max_day INTEGER NOT NULL,
    household_count INTEGER NOT NULL,
    reference_count INTEGER NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    drift_status TEXT NOT NULL CHECK (drift_status IN ('ok', 'watch')),
    feature_drift JSONB NOT NULL,
    prediction_drift JSONB NOT NULL,
    alerts JSONB NOT NULL,
    label_status TEXT NOT NULL CHECK (
        label_status IN ('pending', 'available', 'not_applicable_training_period')
    ),
    outcome_metrics JSONB,
    PRIMARY KEY (as_of_day, model_version)
);
