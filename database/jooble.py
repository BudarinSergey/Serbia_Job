"""Archive Jooble search results. Snippets are not full descriptions.

Imported jobs remain UNKNOWN and outside the publication queue pending review,
translation, and cross-source duplicate resolution.
"""
import hashlib
import json
from datetime import datetime, timezone

def updated_at(job):
    try:
        value=datetime.fromisoformat((job.get("updated") or "").replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    except (ValueError, OverflowError):
        return None


from psycopg.types.json import Jsonb
import psycopg

from database.postgres import SCHEMA_PATH
from sources.jooble import API_URL, JoobleBatch, parse_response


def save_batch(batch: JoobleBatch, dsn: str, max_jobs=None) -> int:
    jobs = parse_response(batch.raw_content)
    jobs=sorted(jobs,key=lambda j:(-(updated_at(j).timestamp() if updated_at(j) else float('-inf')),str(j['id'])))
    if max_jobs is not None:
        jobs=jobs[:max_jobs]
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding='utf-8'))
        conn.execute('ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ')
        conn.execute('''CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_searches (
            snapshot_id BIGINT PRIMARY KEY REFERENCES serbia_jobs.source_snapshots(id),
            query JSONB NOT NULL)''')
        snapshot_id = conn.execute('''INSERT INTO serbia_jobs.source_snapshots
            (source, source_url, fetched_at, content_sha256, raw_content)
            VALUES ('jooble', %s, %s, %s, %s) RETURNING id''',
            (API_URL, batch.fetched_at, hashlib.sha256(batch.raw_content).hexdigest(),
             batch.raw_content)).fetchone()[0]
        conn.execute('INSERT INTO serbia_jobs.jooble_searches VALUES (%s, %s)',
                     (snapshot_id, Jsonb({k: batch.query[k] for k in
                         ('keywords', 'location', 'page', 'ResultOnPage') if k in batch.query})))
        for job in jobs:
            digest = hashlib.sha256(json.dumps(job, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            conn.execute('''INSERT INTO serbia_jobs.vacancies
                (source, source_id, source_url, title, summary_original, company,
                 locations, employment_type, first_seen_at, last_seen_at, snapshot_id, content_sha256, source_updated_at)
                VALUES ('jooble', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    source_url=EXCLUDED.source_url, title=EXCLUDED.title,
                    summary_original=EXCLUDED.summary_original, company=EXCLUDED.company,
                    locations=EXCLUDED.locations, employment_type=EXCLUDED.employment_type,
                    last_seen_at=EXCLUDED.last_seen_at, snapshot_id=EXCLUDED.snapshot_id,
                    content_sha256=EXCLUDED.content_sha256, source_updated_at=EXCLUDED.source_updated_at
                WHERE EXCLUDED.last_seen_at >= serbia_jobs.vacancies.last_seen_at''',
                (str(job['id']), job['link'], job['title'], job.get('snippet') or '',
                 job.get('company') or None,
                 Jsonb([job['location']]) if job.get('location') else None,
                 job.get('type') or None, batch.fetched_at, batch.fetched_at, snapshot_id, digest, updated_at(job)))
    return len(jobs)
