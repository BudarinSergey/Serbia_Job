from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from normalization import extract_four
from telegram_bot.preview import render_post, salary_text, read_history, history_label
from telegram_bot.localization import TITLES


class TelegramPreviewTests(unittest.TestCase):
    def setUp(self):
        patcher=patch.dict(TITLES,{'Assistant <test>':('Asistent <test>','Ассистент <test>')})
        patcher.start()
        self.addCleanup(patcher.stop)
    def job(self):
        return {'source_id':'123','title':'Assistant <test>','source_url':'https://poslovi.infostud.com/posao/a/b/123',
                'company':'A & B','locations':['Beograd','Novi Sad'],'summary_original':'',
                'four_fields':extract_four('Requirements\nEnglish preferred\nMinimum SSS',{'salary':'neto 81.300 RSD (mesečno)'}),
                'detail_snapshot_id':1,'four_fields_snapshot_id':1,'detail_status':'TEXT'}

    def test_correct_salary_and_safe_html(self):
        body,topics=render_post(self.job())
        self.assertIn('81\u202f300 RSD, нетто',body)
        self.assertIn('Английский — не указано',body)
        self.assertIn('Asistent &lt;test&gt;',body)
        self.assertIn('A &amp; B',body)
        self.assertEqual(topics,['belgrade','novi_sad'])
        self.assertNotIn('цитат',body)

    def test_unknown_is_not_no_requirement(self):
        job=self.job(); job['four_fields']=extract_four('',{})
        body,_=render_post(job)
        self.assertIn('Языки: не указано',body)
        self.assertNotIn('не требуется',body)

    def test_stale_extraction_not_shown(self):
        job=self.job(); job['four_fields_snapshot_id']=2
        body,_=render_post(job)
        self.assertNotIn('81\u202f300',body)

    def test_no_unstated_salary_basis(self):
        fields=extract_four('Zaradu u iznosu od 90.000 RSD',{})
        self.assertEqual(salary_text(fields),'90\u202f000 RSD')

    def test_uncertain_history_takes_priority(self):
        rows=[('infostud','123',1,'sent',42),('infostud','123',2,'uncertain',None)]
        self.assertIn('ручная сверка',history_label(rows,'123'))

    def test_history_read_does_not_mutate_or_create(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'history.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE telegram_outbox (chat_id,source,source_id,thread_id,status,message_id)')
                db.execute("INSERT INTO telegram_outbox VALUES (1,'infostud','123',2,'pending',NULL)")
                db.commit()
            before=path.read_bytes()
            self.assertEqual(len(read_history(path,1)),1)
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(sqlite3.Error): read_history(Path(temp)/'missing.db',1)

    @patch('telegram_bot.preview.build_preview',return_value=([],{}))
    @patch('database.postgres.connection_dsn',return_value='unused')
    @patch('main.publish',side_effect=AssertionError('Unexpected send'))
    @patch('telegram_bot.client.api',side_effect=AssertionError('Unexpected Telegram call'))
    def test_cli_preview_never_sends(self,api,publish,dsn,build):
        import main
        self.assertEqual(main.main(['--telegram-preview','--limit','5']),0)
        api.assert_not_called(); publish.assert_not_called()
