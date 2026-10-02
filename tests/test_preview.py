import contextlib
import io
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import main
from sources.infostud import FeedBatch, InfostudError, Vacancy, fetch_feed


class PreviewTests(unittest.TestCase):
    @patch('main.publish')
    @patch('main.save_vacancies')
    @patch('main.fetch_feed')
    def test_preview_limits_output_without_writing_or_publishing(self, fetch, save, publish):
        jobs = [Vacancy(str(i), f'JOB-{i}', 'https://poslovi.infostud.com', 'Company - Beograd', None)
                for i in range(10)]
        fetch.return_value = FeedBatch(b'', datetime.now(timezone.utc), jobs)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main.main(['--preview', '--limit', '5']), 0)
        self.assertIn('JOB-4', output.getvalue())
        self.assertNotIn('JOB-5', output.getvalue())
        self.assertIn('UNKNOWN', output.getvalue())
        save.assert_not_called()
        publish.assert_not_called()

    @patch('main.fetch_feed', side_effect=InfostudError('offline'))
    def test_preview_failure(self, fetch):
        self.assertEqual(main.main(['--preview']), 1)

    @patch('sources.infostud.requests.Session.get')
    def test_exact_raw_bytes_retained(self, get):
        from tests.test_infostud import ITEM, rss
        raw = rss(ITEM)
        get.return_value.content = raw
        batch = fetch_feed()
        self.assertEqual(batch.raw_content, raw)
        self.assertEqual(batch.jobs[0].id, '123')
        self.assertIsNotNone(batch.fetched_at.tzinfo)
