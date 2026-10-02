CREATE TABLE IF NOT EXISTS serbia_jobs.telegram_outbox (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    thread_id BIGINT NOT NULL,
    body TEXT NOT NULL,
    legacy_body TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','sending','sent','uncertain')),
    message_id BIGINT,
    origin TEXT NOT NULL DEFAULT 'postgres',
    format_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (chat_id,source,source_id,thread_id)
);
CREATE TABLE IF NOT EXISTS serbia_jobs.publication_migrations (
    migration_token TEXT PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    backup_path TEXT NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    vacancy_count INTEGER NOT NULL,
    outbox_count INTEGER NOT NULL
);
ALTER TABLE serbia_jobs.telegram_outbox ADD COLUMN IF NOT EXISTS translation_issue TEXT;

ALTER TABLE serbia_jobs.telegram_outbox ADD COLUMN IF NOT EXISTS delivery_issue TEXT;
ALTER TABLE serbia_jobs.telegram_outbox ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ;
