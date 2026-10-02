"""Integration test against a disposable database on an explicitly selected server.

Set TEST_POSTGRES_ADMIN_DSN to enable. Requires CREATE DATABASE permission.
Only the uniquely named database created by this test is removed afterwards.
"""
from datetime import datetime, timedelta, timezone
import os
import unittest
import uuid
from unittest.mock import patch

from sources.infostud import FeedBatch, parse_feed
from tests.test_infostud import ITEM, rss


class ConnectionConfigTests(unittest.TestCase):
    @patch('dotenv.load_dotenv')
    def test_standard_pg_settings_default_to_project_database(self, load):
        from database.postgres import connection_dsn
        from psycopg.conninfo import conninfo_to_dict
        with patch.dict(os.environ, {'PGUSER': 'postgres', 'PGPASSWORD': 'test-only'}, clear=True):
            dsn = connection_dsn()
            self.assertEqual(conninfo_to_dict(dsn), {'dbname': 'serbia_jobs'})
            self.assertNotIn('test-only', dsn)

    @patch('dotenv.load_dotenv')
    def test_explicit_database_and_url(self, load):
        from database.postgres import connection_dsn
        from psycopg.conninfo import conninfo_to_dict
        with patch.dict(os.environ, {'PGUSER': 'postgres', 'PGDATABASE': 'custom_jobs'}, clear=True):
            self.assertEqual(conninfo_to_dict(connection_dsn())['dbname'], 'custom_jobs')
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://localhost/example'}, clear=True):
            self.assertEqual(connection_dsn(), 'postgresql://localhost/example')

    @patch('dotenv.load_dotenv')
    def test_missing_settings_are_rejected(self, load):
        from database.postgres import connection_dsn
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            connection_dsn()


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_ADMIN_DSN'),
                     'No disposable PostgreSQL test server configured')
class PostgresTests(unittest.TestCase):
    def test_original_nulls_deduplication_updates_and_rollback(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from database.postgres import save_batch

        admin_dsn = os.environ['TEST_POSTGRES_ADMIN_DSN']
        name = 'serbia_jobs_test_' + uuid.uuid4().hex
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                dsn = make_conninfo(admin_dsn, dbname=name)
                raw = rss(ITEM)
                now = datetime.now(timezone.utc)
                batch = FeedBatch(raw, now, parse_feed(raw))
                save_batch(batch, dsn)
                save_batch(batch, dsn)
                with psycopg.connect(dsn) as conn:
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.vacancies').fetchone()[0], 1)
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.source_snapshots').fetchone()[0], 2)
                    self.assertEqual(bytes(conn.execute('SELECT raw_content FROM serbia_jobs.source_snapshots LIMIT 1').fetchone()[0]), raw)
                    values = conn.execute('''SELECT salary_min, salary_max, language_requirements,
                        company, locations, description_original, normalization_status
                        FROM serbia_jobs.vacancies''').fetchone()
                    self.assertEqual(values, (None, None, None, None, None, None, 'UNKNOWN'))
                changed = rss(ITEM.replace('Company - Beograd', 'Company - Novi Sad'))
                from database.details import save_detail, pending_jobs
                from sources.infostud_details import parse_detail
                from tests.test_details import page, URL
                self.assertEqual(len(pending_jobs(dsn, 10)), 1)
                detail = parse_detail(page(), '123', URL)
                save_detail(detail, dsn)
                save_detail(detail, dsn)
                self.assertEqual(pending_jobs(dsn, 10), [])
                with psycopg.connect(dsn) as conn:
                    row = conn.execute('''SELECT description_original, company, locations,
                        language_requirements, salary_min, normalization_status
                        FROM serbia_jobs.vacancies''').fetchone()
                    self.assertEqual(row, (detail.description, 'Real company', ['Novi Sad'], None, None, 'PARTIAL'))
                    archived = conn.execute('SELECT raw_content FROM serbia_jobs.detail_snapshots LIMIT 1').fetchone()[0]
                    self.assertEqual(bytes(archived), detail.raw_content)
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.vacancies').fetchone()[0], 1)
                from database.normalization import normalize_saved
                self.assertEqual(normalize_saved(dsn), 1)
                self.assertEqual(normalize_saved(dsn), 0)
                newer = parse_detail(page(textAd='<h3>Requirements</h3><p>English required</p><p>Minimum SSS</p><p>Work from home</p>',
                                          salary='neto 81.300 RSD (mesečno)'), '123', URL)
                save_detail(newer, dsn)
                with psycopg.connect(dsn) as conn:
                    self.assertIsNone(conn.execute('SELECT four_fields FROM serbia_jobs.vacancies').fetchone()[0])
                self.assertEqual(normalize_saved(dsn), 1)
                with psycopg.connect(dsn) as conn:
                    normalized = conn.execute('SELECT four_fields, salary_min, work_mode FROM serbia_jobs.vacancies').fetchone()
                    self.assertEqual(set(normalized[0]), {'languages','education','work_mode','salary'})
                    self.assertEqual(normalized[0]['languages']['value'][0]['requirement'], 'REQUIRED')
                    self.assertEqual(normalized[1], 81300)
                    self.assertEqual(normalized[2], 'REMOTE')
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.field_extractions').fetchone()[0], 2)
                save_batch(FeedBatch(changed, now + timedelta(seconds=1), parse_feed(changed)), dsn)
                save_batch(batch, dsn)  # An older fetch cannot overwrite the newer source fields.
                with psycopg.connect(dsn) as conn:
                    self.assertEqual(conn.execute('SELECT summary_original, first_seen_at FROM serbia_jobs.vacancies').fetchone(),
                                     ('Company - Novi Sad', now))
                    # Force a vacancy insert failure after the snapshot has been inserted.
                    conn.execute("ALTER TABLE serbia_jobs.vacancies ADD CONSTRAINT test_reject CHECK (source_id <> '999')")
                failing = rss(ITEM.replace('/123?', '/999?'))
                with self.assertRaises(psycopg.errors.CheckViolation):
                    save_batch(FeedBatch(failing, now, parse_feed(failing)), dsn)
                with psycopg.connect(dsn) as conn:
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.source_snapshots').fetchone()[0], 4)
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.vacancies').fetchone()[0], 1)
            finally:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
