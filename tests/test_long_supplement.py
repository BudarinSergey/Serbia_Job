import unittest
from unittest.mock import Mock
from telegram_bot.localization import field_text,translate,TITLES,TranslationRequired
from telegram_bot.automatic_translation import resolver

class LongSupplementTests(unittest.TestCase):
    def test_long_education_skipped_in_both_languages_without_translation(self):
        lookup=Mock(side_effect=AssertionError('Unexpected translation'))
        token=resolver.set(lookup)
        statement='č'*251
        fields={'education':{'status':'KNOWN','value':[{'statement':statement},{'statement':'SSS'}]}}
        try:
            ru=field_text(fields,'education','ru')
            sr=field_text(fields,'education','sr')
            self.assertIn('Смотрите оригинал',ru)
            self.assertIn('Среднее профессиональное',ru)
            self.assertIn('Pogledajte original',sr)
            self.assertNotIn(statement,ru)
            self.assertEqual(fields['education']['value'][0]['statement'],statement)
            lookup.assert_not_called()
        finally:resolver.reset(token)

    def test_title_is_not_silently_omitted(self):
        with self.assertRaises(TranslationRequired):
            translate(TITLES,'Unknown title '+ 'č'*251,'ru')
