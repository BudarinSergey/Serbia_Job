"""Atomic page archive and conservative structured-field enrichment."""
import hashlib
from pathlib import Path

from sources.infostud_details import parse_detail


def prepare(connection):
    connection.execute(Path(__file__).with_name('details_schema.sql').read_text(encoding='utf-8'))


def pending_jobs(dsn, limit):
    import psycopg
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        prepare(conn)
        return conn.execute('''SELECT source_id, source_url FROM serbia_jobs.vacancies
            WHERE source='infostud' AND detail_fetched_at IS NULL
            ORDER BY published_at DESC NULLS LAST, source_id DESC LIMIT %s''', (limit,)).fetchall()


def save_detail(detail, dsn):
    import psycopg
    from psycopg.types.json import Jsonb
    # Normalize from archived bytes, not mutable caller-supplied fields.
    parsed = parse_detail(detail.raw_content, detail.source_id, detail.source_url)
    f = parsed.fields
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        prepare(conn)
        snapshot = conn.execute('''INSERT INTO serbia_jobs.detail_snapshots
            (source, source_id, source_url, fetched_at, content_sha256, raw_content,
             original_payload, description_original, detail_status)
            VALUES ('infostud', %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (detail.source_id, detail.source_url, detail.fetched_at,
             hashlib.sha256(detail.raw_content).hexdigest(), detail.raw_content,
             Jsonb(parsed.payload), parsed.description, parsed.status)).fetchone()[0]
        provenance = {'method': 'infostud-next-data-v3', 'snapshot_id': snapshot,
            'description': 'textAd', 'company': 'companyDisplayName/companyName',
            'locations': 'cities[].name', 'category': 'primaryCategory.name',
            'employment_type': 'employmentType.nameSr', 'salary': 'displayed salary / textAd',
            'languages': 'not_processed', 'requirements': 'not_processed'}
        conn.execute('''UPDATE serbia_jobs.vacancies SET description_original=%s,
            company=%s, locations=%s, category=%s, employment_type=%s,
            salary_min=%s, salary_max=%s, salary_currency=%s,
            normalization_status='PARTIAL', normalization_provenance=%s,
            language_requirements=NULL, education_requirements=NULL, work_mode=NULL,
            salary_period=NULL, salary_basis=NULL, four_fields=NULL,
            four_fields_snapshot_id=NULL, four_fields_version=NULL,
            detail_snapshot_id=%s, detail_fetched_at=%s, detail_status=%s
            WHERE source='infostud' AND source_id=%s
            AND (detail_fetched_at IS NULL OR detail_fetched_at <= %s)''',
            (parsed.description, f['company'], Jsonb(f['locations']) if f['locations'] else None,
             f['category'], f['employment_type'], f['salary_min'], f['salary_max'],
             f['salary_currency'], Jsonb(provenance), snapshot, detail.fetched_at, parsed.status,
             detail.source_id, detail.fetched_at))
