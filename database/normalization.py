"""Versioned extraction over saved originals; reruns are idempotent."""
from normalization import extract_four, VERSION
from database.details import prepare


def normalize_saved(dsn):
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        prepare(conn)
        rows = conn.execute('''SELECT v.source_id,s.id,s.description_original,s.original_payload
            FROM serbia_jobs.vacancies v JOIN serbia_jobs.detail_snapshots s ON s.id=v.detail_snapshot_id
            WHERE v.source='infostud' AND (v.four_fields_snapshot_id IS DISTINCT FROM s.id
               OR v.four_fields_version IS DISTINCT FROM %s)
            ORDER BY v.source_id FOR UPDATE OF v''', (VERSION,)).fetchall()
        for source_id, snapshot_id, description, payload in rows:
            fields = extract_four(description, payload)
            conn.execute('''INSERT INTO serbia_jobs.field_extractions
                (detail_snapshot_id,extractor_version,fields) VALUES (%s,%s,%s)
                ON CONFLICT (detail_snapshot_id,extractor_version) DO NOTHING''',
                (snapshot_id, VERSION, Jsonb(fields)))
            # Published fields must match the immutable audit entry for this version.
            fields = conn.execute('''SELECT fields FROM serbia_jobs.field_extractions
                WHERE detail_snapshot_id=%s AND extractor_version=%s''', (snapshot_id,VERSION)).fetchone()[0]
            def known(key):
                return fields[key]['value'] if fields[key]['status']=='KNOWN' else None
            pay = known('salary') or {}
            langs, edu = known('languages'), known('education')
            conn.execute('''UPDATE serbia_jobs.vacancies SET
                four_fields=%s, four_fields_snapshot_id=%s, four_fields_version=%s,
                language_requirements=%s, education_requirements=%s, work_mode=%s,
                salary_min=%s, salary_max=%s, salary_currency=%s, salary_period=%s, salary_basis=%s,
                normalization_status='FOUR_FIELDS_PROCESSED',
                normalization_provenance=COALESCE(normalization_provenance,'{}'::jsonb) || %s
                WHERE source='infostud' AND source_id=%s''',
                (Jsonb(fields),snapshot_id,VERSION,Jsonb(langs) if langs else None,
                 Jsonb(edu) if edu else None, known('work_mode'),pay.get('min'),pay.get('max'),
                 pay.get('currency'),pay.get('period'),pay.get('basis'),
                 Jsonb({'four_fields': {'version':VERSION,'snapshot_id':snapshot_id},
                        'salary':'four_fields.salary.evidence'}),source_id))
    return len(rows)


def run():
    import sys
    try:
        import psycopg
        from database.postgres import connection_dsn
        count = normalize_saved(connection_dsn())
    except (ImportError, ValueError, OSError):
        print('Проверьте зависимости и настройки PostgreSQL.', file=sys.stderr)
        return 1
    except psycopg.Error:
        print('Ошибка PostgreSQL; извлечение отменено без частичного сохранения.', file=sys.stderr)
        return 1
    print(f'Четыре поля: обработано {count} вакансий. UNKNOWN означает отсутствие надёжного результата.')
    return 0
