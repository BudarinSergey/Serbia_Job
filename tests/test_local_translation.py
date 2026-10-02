import unittest
from unittest.mock import Mock,patch
from telegram_bot.local_translation import local_translate
from telegram_bot.automatic_translation import TranslationUnavailable

class LocalTranslationTests(unittest.TestCase):
    @patch('telegram_bot.local_translation.runtime')
    def test_offline_tokens_and_serbian_latin(self,runtime):
        model,sp,detector=Mock(),Mock(),Mock()
        runtime.return_value=model,sp,detector
        detector.classify.return_value=('en',0.99)
        sp.encode.return_value=['word']
        model.translate_batch.return_value=[Mock(hypotheses=[['__sr__','translated']])]
        sp.decode.side_effect=['Радник складишта','Работник склада']
        self.assertEqual(local_translate('Warehouse worker'),{'sr':'Radnik skladišta','ru':'Работник склада'})
        self.assertEqual(model.translate_batch.call_args_list[0].args[0],[['__en__','word','</s>']])

    @patch('telegram_bot.local_translation.runtime')
    def test_uncertain_language_and_overlong_input_hold(self,runtime):
        model,sp,detector=Mock(),Mock(),Mock()
        runtime.return_value=model,sp,detector
        detector.classify.return_value=('sr',0.4)
        with self.assertRaises(TranslationUnavailable):local_translate('X')
        detector.classify.return_value=('sr',0.99)
        sp.encode.return_value=['x']*257
        with self.assertRaises(TranslationUnavailable):local_translate('X')
        model.translate_batch.assert_not_called()
