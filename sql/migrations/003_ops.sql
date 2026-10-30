-- Бизнес-статусы запусков. Это не состояния задач Airflow:
-- например, partial_success в Airflow не существует.

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE ops.pipeline_runs (
    run_id TEXT PRIMARY KEY,
    airflow_run_id TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'success', 'partial_success', 'failed')),
    sources_total INT,
    sources_success INT,
    rows_inserted INT,
    staging_rows INT,
    transformed_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE ops.source_runs (
    run_id TEXT NOT NULL REFERENCES ops.pipeline_runs (run_id),
    source_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('success', 'empty', 'unavailable', 'failed')),
    reason TEXT,
    attempt INT NOT NULL DEFAULT 1,
    listing_pages_ok INT NOT NULL DEFAULT 0,
    publication_pages_ok INT NOT NULL DEFAULT 0,
    links_found INT NOT NULL DEFAULT 0,
    accepted INT NOT NULL DEFAULT 0,
    rejected INT NOT NULL DEFAULT 0,
    rows_inserted INT,
    http_errors JSONB NOT NULL DEFAULT '{}'::JSONB,
    other_errors JSONB NOT NULL DEFAULT '{}'::JSONB,
    output_file TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    PRIMARY KEY (run_id, source_id)
);
