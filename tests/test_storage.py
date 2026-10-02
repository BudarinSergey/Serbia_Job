from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from database.storage import save_vacancies
from sources.infostud import Vacancy


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.job = Vacancy('123', 'Inženjer č ć š', 'https://example.com/123',
                           'Компания — Beograd', datetime(2026, 9, 30, tzinfo=timezone.utc))

    def test_persistence_duplicates_and_new_batch(self):
        first = save_vacancies([self.job, self.job], self.path)
        self.assertEqual(first.new_jobs, [self.job])
        self.assertEqual(first.total, 1)
        second = save_vacancies([self.job], self.path)
        self.assertEqual(second.new_jobs, [])
        self.assertEqual(second.total, 1)
        other = replace(self.job, id='124', published_at=None)
        third = save_vacancies([self.job, other], self.path)
        self.assertEqual(third.new_jobs, [other])
        self.assertEqual(third.total, 2)
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT title, summary, published_at, first_seen_at FROM vacancies WHERE source_id=?', ('123',)).fetchone()
        self.assertEqual(row[:3], (self.job.title, self.job.summary, self.job.published_at.isoformat()))
        self.assertIsNotNone(datetime.fromisoformat(row[3]).tzinfo)

    def test_same_id_from_different_sources(self):
        result = save_vacancies([self.job, replace(self.job, source='other')], self.path)
        self.assertEqual(result.total, 2)

    def test_failed_batch_rolls_back_and_preserves_previous_data(self):
        save_vacancies([self.job], self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            save_vacancies([replace(self.job, id='124'), replace(self.job, id='125', title=None)], self.path)
        result = save_vacancies([], self.path)
        self.assertEqual(result.total, 1)

if __name__ == '__main__':
    unittest.main()
