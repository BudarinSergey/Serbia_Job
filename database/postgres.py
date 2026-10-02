"""Optional PostgreSQL ingestion; never sends Telegram messages.

Every fetch is retained byte-for-byte. RSS summaries are not full job descriptions.
No company/city/salary/language inference is performed here.
"""
import hashlib
import json
from pathlib import Path

from sources.infostud import FeedBatch, parse_feed


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connection_dsn() -> str:
    """Read DATABASE_URL or standard PG* settings without logging secrets."""
    import os
    from dotenv import load_dotenv
    from psycopg.conninfo import make_conninfo

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if not os.environ.get("PGUSER"):
        raise ValueError("Configure DATABASE_URL or PGUSER and PG connection settings")
    # libpq reads PGHOST, PGPORT, PGUSER and PGPASSWORD from the environment.
    return make_conninfo(dbname=os.environ.get("PGDATABASE") or "serbia_jobs")


def save_batch(batch: FeedBatch, dsn: str) -> int:
    """Save snapshot and RSS fields atomically. Return number of observed jobs.

Create the tables on first use. Repeated IDs update source fields without
overwriting future enrichment. Full original responses remain in snapshots.
"""
    import psycopg

    # Reparse the actual bytes so callers cannot persist mismatched source data.
    jobs = parse_feed(batch.raw_content)
    with psycopg.connect(dsn, connect_timeout=10) as connection:
        connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        snapshot_id = connection.execute("""
            INSERT INTO serbia_jobs.source_snapshots
                (source, source_url, fetched_at, content_sha256, raw_content)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, ("infostud", batch.source_url, batch.fetched_at,
              hashlib.sha256(batch.raw_content).hexdigest(), batch.raw_content)).fetchone()[0]
        for job in jobs:
            content_hash = hashlib.sha256(json.dumps(
                [job.title, job.summary, job.url,
                 job.published_at.isoformat() if job.published_at else None],
                ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            connection.execute("""
                INSERT INTO serbia_jobs.vacancies
                    (source, source_id, source_url, title, summary_original,
                     published_at, first_seen_at, last_seen_at, snapshot_id, content_sha256)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    source_url = EXCLUDED.source_url,
                    title = EXCLUDED.title,
                    summary_original = EXCLUDED.summary_original,
                    published_at = EXCLUDED.published_at,
                    last_seen_at = EXCLUDED.last_seen_at,
                    snapshot_id = EXCLUDED.snapshot_id,
                    content_sha256 = EXCLUDED.content_sha256,
                    normalization_status = CASE
                        WHEN serbia_jobs.vacancies.content_sha256 <> EXCLUDED.content_sha256
                        THEN 'UNKNOWN'
                        ELSE serbia_jobs.vacancies.normalization_status END
                WHERE EXCLUDED.last_seen_at >= serbia_jobs.vacancies.last_seen_at
            """, (job.source, job.id, job.url, job.title, job.summary,
                  job.published_at, batch.fetched_at, batch.fetched_at,
                  snapshot_id, content_hash))
    return len(jobs)
