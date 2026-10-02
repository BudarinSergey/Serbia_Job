-- Initial PostgreSQL layer. Does not migrate or modify the SQLite outbox.
CREATE SCHEMA IF NOT EXISTS serbia_jobs;

CREATE TABLE IF NOT EXISTS serbia_jobs.source_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_content BYTEA NOT NULL
);

CREATE TABLE IF NOT EXISTS serbia_jobs.vacancies (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    summary_original TEXT NOT NULL,
    description_original TEXT,
    published_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    snapshot_id BIGINT NOT NULL REFERENCES serbia_jobs.source_snapshots(id),
    content_sha256 TEXT NOT NULL,
    company TEXT,
    locations JSONB,
    category TEXT,
    subcategory TEXT,
    salary_min NUMERIC CHECK (salary_min >= 0),
    salary_max NUMERIC CHECK (salary_max >= 0),
    salary_currency TEXT,
    salary_period TEXT,
    language_requirements JSONB,
    employment_type TEXT,
    work_mode TEXT,
    experience_min NUMERIC CHECK (experience_min >= 0),
    requirements_original TEXT,
    normalization_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    normalization_provenance JSONB,
    PRIMARY KEY (source, source_id),
    CHECK (salary_max >= salary_min)
);
