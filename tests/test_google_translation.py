import json
import subprocess
import unittest
from unittest.mock import Mock,patch
from telegram_bot.google_translation import google_translate
from telegram_bot.automatic_translation import TranslationUnavailable

class GoogleTranslationTests(unittest.TestCase):
    @patch('telegram_bot.google_translation.subprocess.run')
    def test_bounded_worker_and_valid_pair(self,run):
        pair={'sr':'Operater u proizvodnji','ru':'Оператор производства'}
        run.return_value=Mock(returncode=0,stdout=json.dumps(pair))
        self.assertEqual(google_translate('Operater u proizvodnji'),pair)
        self.assertEqual(run.call_args.kwargs['timeout'],45)
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['text'],'Operater u proizvodnji')

    @patch('telegram_bot.google_translation.subprocess.run')
    def test_rate_limit_and_bad_data_fail_closed(self,run):
        for code,output in [(1,'RATE_LIMIT'),(1,''),(0,'html'),(0,'{}'),(0,'{"sr":"2 godine","ru":"3 года"}')]:
            run.return_value=Mock(returncode=code,stdout=output)
            with self.assertRaises(TranslationUnavailable) as error:google_translate('2 years')
            if output=='RATE_LIMIT':self.assertIn('429',str(error.exception))
        run.side_effect=subprocess.TimeoutExpired('worker',45)
        with self.assertRaises(TranslationUnavailable):google_translate('text')
