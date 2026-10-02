import unittest
from telegram_bot.jooble_preview import prepare, duplicate_candidates
from telegram_bot.preview import render_post


def job(identity='1', source='jooble', company='Primer'):
    return dict(source=source,source_id=identity,source_url='https://rs.jooble.org/jdp/'+identity,
                title='Magacioner',company=company,locations=['Beograd'],snapshot_id=3)


class JooblePreviewTests(unittest.TestCase):
    def test_title_is_required_before_company_and_city_match(self):
        a=job()
        self.assertFalse(duplicate_candidates(a,[dict(job('2'),title='Vozac')]))
        self.assertEqual(len(duplicate_candidates(a,[dict(job('2'),title='  MAGACIONER! ')])),1)
        self.assertFalse(duplicate_candidates(a,[dict(job('2'),locations=['Novi Sad'])]))
        self.assertFalse(duplicate_candidates(a,[job('2',company='Other')]))
        self.assertEqual(len(duplicate_candidates(a,[dict(job('2'),title='Changed',source_url=a['source_url'])])),1)

    def test_daily_salary_and_unknown_languages(self):
        value=prepare(job(),{'salary':'dnevnica 3.500 din','snippet':'<b>Magacioner</b>'},[])
        self.assertEqual(value['four_fields']['salary']['value']['period'],'DAY')
        self.assertIn('3\u202f500 RSD dnevno',value['body'])
        self.assertIn('3\u202f500 RSD в день',value['body'])
        self.assertIn('Языки: не указано',value['body'])
        self.assertIn('Jezici: nije navedeno',value['body'])
        self.assertLess(value['body'].index('🇷🇸'),value['body'].index('🇷🇺'))
        self.assertEqual(value['four_fields']['salary']['evidence'][0]['source_path'],'jooble.salary')

    def test_suspicious_salary_not_corrected(self):
        value=prepare(job(),{'salary':'70 din','snippet':''},[])
        self.assertEqual(value['four_fields']['salary']['status'],'REVIEW')
        self.assertIsNone(value['four_fields']['salary']['value'])
        self.assertIn('требует уточнения',value['body'])
        self.assertNotIn('70\u202f000',value['body'])

    def test_text_salary_no_invented_currency_or_period(self):
        value=prepare(job(),{'snippet':'<b>Plata</b> 100.000'},[])
        pay=value['four_fields']['salary']['value']
        self.assertEqual(pay['min'],'100000')
        self.assertIsNone(pay['currency'])
        self.assertIsNone(pay['period'])

    def test_duplicates_flagged_across_sources_without_removal(self):
        a,b=job(),job('2','infostud')
        b['source_url']='https://poslovi.infostud.com/posao/a/b/2'
        self.assertEqual(len(duplicate_candidates(a,[a,b,job('3',company='Other')])),1)
        value=prepare(a,{},[a,b])
        self.assertTrue(value['body'])
        self.assertEqual(value['review_status'],'REVIEW')
        self.assertFalse(duplicate_candidates(dict(a,company=None),[b]))

    def test_untranslated_title_and_unsafe_link(self):
        value=prepare(dict(job(),title='Unreviewed title'),{},[])
        self.assertFalse(value['body'])
        self.assertEqual(value['review_status'],'REVIEW')
        with self.assertRaises(ValueError):
            render_post(dict(job(),source_url='https://evil.example/jdp/1'))
        with self.assertRaises(ValueError):
            render_post(dict(job(),source='infostud'))

    def test_conflicting_salary_preserved_for_review(self):
        value=prepare(job(),{'salary':'80.000 din','snippet':'Plata 100.000 din'},[])
        self.assertEqual(value['four_fields']['salary']['status'],'REVIEW')
        self.assertEqual(len(value['four_fields']['salary']['evidence']),2)
