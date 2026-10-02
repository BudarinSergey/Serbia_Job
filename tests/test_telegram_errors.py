import unittest
from unittest.mock import patch
from telegram_bot.client import api, TelegramError

class TelegramErrorTests(unittest.TestCase):
    @patch('telegram_bot.client.dotenv_values',return_value={'TELEGRAM_BOT_TOKEN':'test-only'})
    @patch('telegram_bot.client.requests.post')
    def test_classifies_only_content_errors(self,post,env):
        for code,description,local in [(400,"Bad Request: can't parse entities",True),(400,'Bad Request: message is too long',True),(400,'Bad Request: chat not found',False),(400,'Bad Request: message thread not found',False),(403,'Forbidden',False),(500,'Internal Server Error',False)]:
            with self.subTest(description=description):
                post.return_value.json.return_value={'ok':False,'error_code':code,'description':description}
                with self.assertRaises(TelegramError) as caught:api('sendMessage',text='test')
                self.assertEqual(caught.exception.message_specific,local)
                self.assertEqual(caught.exception.error_code,code)
                self.assertFalse(caught.exception.uncertain)
        post.return_value.json.return_value={'ok':False,'error_code':429,'description':'Too Many Requests','parameters':{'retry_after':7200}}
        with self.assertRaises(TelegramError) as caught:api('sendMessage',text='test')
        self.assertEqual(caught.exception.retry_after,7200)
        self.assertFalse(caught.exception.message_specific)
