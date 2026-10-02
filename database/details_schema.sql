CREATE TABLE IF NOT EXISTS serbia_jobs.detail_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_content BYTEA NOT NULL,
    original_payload JSONB NOT NULL,
    description_original TEXT,
    FOREIGN KEY (source, source_id) REFERENCES serbia_jobs.vacancies(source, source_id)
);
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS detail_snapshot_id BIGINT
    REFERENCES serbia_jobs.detail_snapshots(id);
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS detail_fetched_at TIMESTAMPTZ;
ALTER TABLE serbia_jobs.detail_snapshots ALTER COLUMN description_original DROP NOT NULL;
ALTER TABLE serbia_jobs.detail_snapshots ADD COLUMN IF NOT EXISTS detail_status TEXT NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS detail_status TEXT NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS education_requirements JSONB;
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS salary_basis TEXT;
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS four_fields JSONB;
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS four_fields_snapshot_id BIGINT
    REFERENCES serbia_jobs.detail_snapshots(id);
ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS four_fields_version TEXT;
CREATE TABLE IF NOT EXISTS serbia_jobs.field_extractions (
    detail_snapshot_id BIGINT NOT NULL REFERENCES serbia_jobs.detail_snapshots(id),
    extractor_version TEXT NOT NULL,
    fields JSONB NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (detail_snapshot_id, extractor_version)
);
