import unittest
from unittest.mock import patch
import requests
from sources.infostud import parse_feed, fetch_vacancies, InfostudError

ITEM = '''<item><title>Inženjer č ć š</title><link>http://poslovi.infostud.com/posao/test/company/123?utm_source=rss</link><description>Company - Beograd</description><pubDate>Tue, 29 Sep 2026 11:41:23 +0200</pubDate></item>'''

def rss(items):
    return ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Jobs</title>' + items + '</channel></rss>').encode()

class FeedTests(unittest.TestCase):
    def test_unicode_date_and_deduplication(self):
        jobs = parse_feed(rss(ITEM + ITEM))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].id, '123')
        self.assertEqual(jobs[0].title, 'Inženjer č ć š')
        self.assertEqual(jobs[0].published_at.isoformat(), '2026-09-29T09:41:23+00:00')
        self.assertTrue(jobs[0].url.startswith('https://poslovi.infostud.com/'))

    def test_invalid_and_empty_feed(self):
        for content in (b'<html>Unavailable</html>', b'<rss>', rss('')):
            with self.subTest(content=content), self.assertRaises(InfostudError):
                parse_feed(content)

    def test_missing_or_foreign_link(self):
        for item in (ITEM.replace('poslovi.infostud.com', 'example.com'), ITEM.replace('<title>Inženjer č ć š</title>', '')):
            with self.subTest(item=item), self.assertRaises(InfostudError):
                parse_feed(rss(item))

    def test_bad_entry_does_not_discard_valid_neighbors(self):
        bad = ITEM.replace('poslovi.infostud.com', 'example.com')
        malformed = ITEM.replace('http://poslovi.infostud.com', 'http://[broken')
        newer = ITEM.replace('/123?', '/456?')
        with self.assertLogs('sources.infostud', level='WARNING') as logs:
            jobs = parse_feed(rss(ITEM + bad + malformed + newer))
        self.assertEqual([job.id for job in jobs], ['123', '456'])
        self.assertEqual(len(logs.output), 2)

    @patch('sources.infostud.requests.Session.get', side_effect=requests.Timeout('timeout'))
    def test_network_failure(self, mocked):
        with self.assertRaises(InfostudError):
            fetch_vacancies()

if __name__ == '__main__':
    unittest.main()
