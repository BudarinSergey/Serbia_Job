import tempfile
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from sources.infostud import Vacancy
from telegram_bot.formatting import route, render
from telegram_bot.publisher import publish
from telegram_bot.client import TelegramError

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.job = Vacancy('1','IT tehničar <test>','https://poslovi.infostud.com/posao/a/b/1','Company - Beograd',None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name)/'db.sqlite3'
        self.config = {'chat_id':1,'bot_id':2,'topics':{'all':{'message_thread_id':3},'belgrade':{'message_thread_id':3}}}

    @patch('telegram_bot.publisher.time.sleep')
    @patch('telegram_bot.publisher.api')
    def test_no_extra_all_delivery(self, api, sleep):
        self.config['topics']['all']['message_thread_id'] = 7
        api.side_effect = [{'id':2}, {'message_id':20}, {'message_id':21}]
        self.assertEqual(publish([self.job], self.db, self.config), 1)
        self.assertEqual(publish([self.job], self.db, self.config), 0)
        sends = [c.kwargs['message_thread_id'] for c in api.call_args_list if c.args[0] == 'sendMessage']
        self.assertEqual(sends, [3])

    def test_routes(self):
        from dataclasses import replace
        for summary, expected in [('Company Beograd - Novi Sad',['novi_sad']),('Company - Beograd, Novi Sad, Niš',['belgrade','novi_sad','other_cities']),('Company - Rad od kuće',['remote']),('Company',['other_cities'])]:
            self.assertEqual(route(replace(self.job,summary=summary)),expected)
        self.assertIn('&lt;test&gt;',render(self.job))

    @patch('telegram_bot.publisher.time.sleep')
    @patch('telegram_bot.publisher.api')
    def test_persistent_dedup(self, api, sleep):
        api.side_effect = [{'id':2},{'message_id':10}]
        self.assertEqual(publish([self.job],self.db,self.config),1)
        self.assertEqual(publish([self.job],self.db,self.config),0)
        self.assertEqual(api.call_count,2)

    @patch('telegram_bot.publisher.api')
    def test_uncertain_not_resent(self, api):
        api.side_effect = [{'id':2},TelegramError('timeout',uncertain=True)]
        with self.assertRaises(TelegramError): publish([self.job],self.db,self.config)
        self.assertEqual(publish([self.job],self.db,self.config),0)
        self.assertEqual(api.call_count,2)

    @patch('telegram_bot.publisher.time.sleep')
    @patch('telegram_bot.publisher.api')
    def test_explicit_rejection_retries_from_queue(self, api, sleep):
        api.side_effect = [{'id':2},TelegramError('429')]
        with self.assertRaises(TelegramError): publish([self.job],self.db,self.config)
        api.side_effect = [{'id':2},{'message_id':11}]
        self.assertEqual(publish([],self.db,self.config),1)
