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
        self.assertIn('3\u202f500 RSD',value['body'])
        self.assertIn('3\u202f500 RSD',value['body'])
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

    def test_description_salary_ignored_when_field_empty(self):
        value=prepare(job(),{'snippet':'Plata 100.000'},[])
        self.assertEqual(value['four_fields']['salary']['status'],'UNKNOWN')
        self.assertIsNone(value['four_fields']['salary']['value'])

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
        self.assertEqual(value['body'].count('Unreviewed title'),1)
        self.assertEqual(value['review_status'],'REVIEW')
        self.assertEqual(value['category']['status'],'UNKNOWN')
        with self.assertRaises(ValueError):
            render_post(dict(job(),source_url='https://evil.example/jdp/1'))
        with self.assertRaises(ValueError):
            render_post(dict(job(),source='infostud'))

    def test_salary_field_is_authoritative_without_description_period(self):
        value=prepare(job(),{'salary':'500 - 550 din','snippet':'Plata 500 rsd/h'},[])
        pay=value['four_fields']['salary']
        self.assertEqual(pay['status'],'KNOWN')
        self.assertEqual(pay['value']['min'],'500')
        self.assertEqual(pay['value']['max'],'550')
        self.assertIsNone(pay['value']['period'])
        self.assertTrue(all(e['source_path']=='jooble.salary' for e in pay['evidence']))
        self.assertEqual(value['review_status'],'DRAFT')

    def test_truncated_company_allowed_without_reconstruction(self):
        value=prepare(job(company='Novotek d...'),{},[])
        self.assertEqual(value['review_status'],'DRAFT')
        self.assertIn('Novotek d...',value['body'])
