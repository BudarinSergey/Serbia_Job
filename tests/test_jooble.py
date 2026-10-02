import json
import os
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock
import requests

from sources.jooble import JoobleBatch, JoobleError, fetch_jobs, parse_response


def raw(**changes):
    job = dict(id=123, title='Kasir', company='Primer', location='Beograd',
               snippet='Kratak opis', link='https://rs.jooble.org/jdp/123', salary='')
    job.update(changes)
    return json.dumps(dict(totalCount=1, jobs=[job]), ensure_ascii=False).encode()


class JoobleTests(unittest.TestCase):
    def test_empty_and_invalid_responses(self):
        self.assertEqual(parse_response(b'{"jobs": []}'), [])
        for value in (b'html', b'{}', raw(link='https://evil.example/jdp/123'),
                      raw(title=None), raw(id=None), raw(location=[])):
            with self.assertRaises(JoobleError):
                parse_response(value)

    def test_duplicate_ids_and_original_fields(self):
        job = json.loads(raw())['jobs'][0]
        self.assertEqual(parse_response(json.dumps({'jobs': [job, job]}).encode()), [job])

    @patch('sources.jooble.requests.post')
    def test_bounded_request_and_secret_redaction(self, post):
        with self.assertRaises(JoobleError):
            fetch_jobs('', 'kasir')
        with self.assertRaises(JoobleError):
            fetch_jobs('secret', '')
        post.assert_not_called()
        post.return_value = Mock(status_code=200, content=raw())
        batch = fetch_jobs('secret', 'kasir', limit=50)
        self.assertEqual(batch.query['ResultOnPage'], 50)
        self.assertEqual(batch.raw_content, raw())
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertEqual(batch.query['page'], 1)
        post.side_effect = requests.ConnectionError('https://rs.jooble.org/api/secret')
        with self.assertRaises(JoobleError) as caught:
            fetch_jobs('secret', 'kasir')
        self.assertNotIn('secret', str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    @patch('sources.jooble.requests.post')
    def test_http_errors_do_not_echo_body(self, post):
        for status in (302, 403, 429, 500):
            post.return_value = Mock(status_code=status, content=b'secret')
            with self.assertRaises(JoobleError) as caught:
                fetch_jobs('secret', 'kasir')
            self.assertNotIn('secret', str(caught.exception))


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_ADMIN_DSN'), 'No test database configured')
class JoobleStorageTests(unittest.TestCase):
    def test_originals_nulls_idempotency_and_stale_response(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from database.jooble import save_batch
        admin_dsn = os.environ['TEST_POSTGRES_ADMIN_DSN']
        name = 'serbia_jooble_test_' + uuid.uuid4().hex
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                dsn = make_conninfo(admin_dsn, dbname=name)
                now = datetime.now(timezone.utc)
                batch = JoobleBatch(raw(), now, {'keywords': 'kasir', 'key': 'secret'})
                save_batch(batch, dsn)
                save_batch(batch, dsn)
                save_batch(JoobleBatch(raw(title='Old'), now-timedelta(days=1), {}), dsn)
                with psycopg.connect(dsn) as conn:
                    row = conn.execute('''SELECT source, title, company, locations,
                        description_original, salary_min, language_requirements,
                        work_mode, published_at, normalization_status
                        FROM serbia_jobs.vacancies''').fetchall()
                    self.assertEqual(row, [('jooble', 'Kasir', 'Primer', ['Beograd'],
                                           None, None, None, None, None, 'UNKNOWN')])
                    self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.source_snapshots').fetchone()[0], 3)
                    stored = conn.execute('SELECT raw_content FROM serbia_jobs.source_snapshots ORDER BY id LIMIT 1').fetchone()[0]
                    self.assertEqual(bytes(stored), raw())
                    self.assertNotIn('secret', str(conn.execute('SELECT query FROM serbia_jobs.jooble_searches').fetchall()))
            finally:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
