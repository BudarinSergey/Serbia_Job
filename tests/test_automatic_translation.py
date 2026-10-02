import os
import unittest
from unittest.mock import patch,Mock
from telegram_bot.automatic_translation import azure_translate,TranslationUnavailable,validate,resolver
from telegram_bot.localization import translate,TITLES,TranslationRequired

class AutomaticTranslationTests(unittest.TestCase):
    @patch.dict(os.environ,{},clear=True)
    @patch('telegram_bot.automatic_translation.requests.post')
    def test_no_key_or_paid_tier_never_requests(self,post):
        with self.assertRaises(TranslationUnavailable): azure_translate('Role')
        with patch.dict(os.environ,{'AZURE_TRANSLATOR_KEY':'secret','AZURE_TRANSLATOR_TIER':'S1'}):
            with self.assertRaises(TranslationUnavailable): azure_translate('Role')
        post.assert_not_called()

    @patch.dict(os.environ,{'AZURE_TRANSLATOR_KEY':'secret','AZURE_TRANSLATOR_TIER':'F0'})
    @patch('telegram_bot.automatic_translation.requests.post')
    def test_api_targets_both_languages_and_rejects_failures(self,post):
        post.return_value=Mock(status_code=200)
        post.return_value.json.return_value=[{'translations':[{'to':'ru','text':'Диспетчер'},{'to':'sr-Latn','text':'Dispečer'}]}]
        self.assertEqual(azure_translate('Dispatcher'),{'sr':'Dispečer','ru':'Диспетчер'})
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        for code in (403,429,500):
            post.return_value.status_code=code
            with self.assertRaises(TranslationUnavailable) as e: azure_translate('Dispatcher')
            self.assertNotIn('secret',str(e.exception))

    def test_invalid_or_changed_numbers_rejected(self):
        for pair in ({'sr':'tekst'},{'sr':'','ru':'текст'},{'sr':'<b>test</b>','ru':'текст'},
                     {'sr':'2 godine','ru':'3 года'}):
            with self.assertRaises(TranslationUnavailable):validate('2 years',pair)

    def test_manual_dictionary_wins_and_failures_hold_unknowns(self):
        fn=Mock(return_value='translated')
        token=resolver.set(fn)
        try:
            self.assertEqual(translate(TITLES,'Magacioner','ru'),'Кладовщик')
            fn.assert_not_called()
            self.assertEqual(translate(TITLES,'Novel role','ru'),'translated')
            fn.side_effect=TranslationUnavailable()
            with self.assertRaises(TranslationRequired):translate(TITLES,'Novel role','ru')
        finally:resolver.reset(token)
