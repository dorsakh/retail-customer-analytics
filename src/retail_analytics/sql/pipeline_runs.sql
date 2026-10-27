-- Operational history for scheduled scoring. Source tables are untouched.
CREATE TABLE IF NOT EXISTS analytics.pipeline_runs (
    run_id UUID PRIMARY KEY,
    as_of_day INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    source_max_day INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('running', 'succeeded', 'failed', 'skipped')
    ),
    input_rows INTEGER,
    scored_rows INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    error_type TEXT,
    error_message TEXT
);
