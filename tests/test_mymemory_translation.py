import unittest
from unittest.mock import Mock,patch
from telegram_bot.mymemory_translation import request_translation,mymemory_translate
from telegram_bot.automatic_translation import TranslationUnavailable

class MyMemoryTests(unittest.TestCase):
    @patch('telegram_bot.mymemory_translation.block_quota')
    @patch('telegram_bot.mymemory_translation.reserve')
    @patch('telegram_bot.mymemory_translation.requests.get')
    def test_valid_response_has_no_email_or_key(self,get,reserve,block):
        get.return_value=Mock(status_code=200)
        get.return_value.json.return_value={'responseStatus':200,'quotaFinished':False,'responseData':{'translatedText':'Оператор производства'}}
        self.assertEqual(request_translation('Operater u proizvodnji','sr','ru','dsn'),'Оператор производства')
        self.assertEqual(get.call_args.kwargs['params'],{'q':'Operater u proizvodnji','langpair':'sr|ru'})
        self.assertEqual(get.call_args.kwargs['timeout'],(10,25))
        reserve.assert_called_once_with('dsn',len('Operater u proizvodnji'))
        block.assert_not_called()

    @patch('telegram_bot.mymemory_translation.block_quota')
    @patch('telegram_bot.mymemory_translation.reserve')
    @patch('telegram_bot.mymemory_translation.requests.get')
    def test_200_is_not_sufficient(self,get,reserve,block):
        get.return_value=Mock(status_code=200)
        for data in ({'responseStatus':403}, {'responseStatus':200,'quotaFinished':True},
                     {'responseStatus':200,'responseData':{'translatedText':''}},
                     {'responseStatus':200,'responseData':{'translatedText':'MYMEMORY WARNING: quota'}},
                     {'responseStatus':200,'responseData':{'translatedText':'test'}}, []):
            get.return_value.json.return_value=data
            with self.assertRaises(TranslationUnavailable):request_translation('test','en','ru','dsn')
        block.assert_called_once_with('dsn')

    @patch('telegram_bot.mymemory_translation.reserve')
    @patch('telegram_bot.mymemory_translation.requests.get')
    def test_utf8_limit_before_request(self,get,reserve):
        with self.assertRaises(TranslationUnavailable):request_translation('я'*251,'ru','sr','dsn')
        get.assert_not_called();reserve.assert_not_called()

    @patch('telegram_bot.mymemory_translation.source_language',return_value='sr')
    @patch('telegram_bot.mymemory_translation.request_translation',return_value='Оператор производства')
    def test_serbian_original_unchanged(self,request,detect):
        pair=mymemory_translate('Operater u proizvodnji','dsn')
        self.assertEqual(pair,{'sr':'Operater u proizvodnji','ru':'Оператор производства'})
        request.assert_called_once_with('Operater u proizvodnji','sr','ru','dsn')

    def test_source_is_always_configured_serbian(self):
        from telegram_bot.mymemory_translation import source_language
        for text in ('Konobar','Kasir','Administrativni radnik','Master / magistratura'):
            self.assertEqual(source_language(text),'sr')

    @patch('telegram_bot.mymemory_translation.request_translation')
    def test_long_title_still_requires_review_without_request(self,request):
        with self.assertRaises(TranslationUnavailable):
            mymemory_translate('č'*251,'dsn')
        request.assert_not_called()
