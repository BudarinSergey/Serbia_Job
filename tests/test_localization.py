import unittest
from normalization import extract_four
from telegram_bot.localization import field_text, TranslationRequired
from telegram_bot.preview import render_post


class LocalizationTests(unittest.TestCase):
    def job(self, text='', payload=None):
        return {'source_id':'1','title':'Saradnik u finansijama','source_url':'https://poslovi.infostud.com/posao/a/b/1',
                'company':'B4B d.o.o.','locations':['Beograd'],'summary_original':'Company - Beograd',
                'four_fields':extract_four(text,payload or {}),'four_fields_snapshot_id':1,'detail_snapshot_id':1}

    def test_serbian_first_and_company_once(self):
        body,_=render_post(self.job('Uslov:\nminimum SSS, poželjno VSS ekonomskog ili srodnog usmerenja;'))
        self.assertLess(body.index('Jezici:'),body.index('Языки:'))
        self.assertLess(body.index('Obrazovanje:'),body.index('Образование:'))
        self.assertEqual(body.count('B4B d.o.o.'),1)
        self.assertIn('Высшее экономическое или смежное образование (желательно)',body)
        self.assertIn('Visoka stručna sprema ekonomskog ili srodnog usmerenja (poželjno)',body)
        self.assertIn('Detaljnije / Prijavite se · Подробнее / Откликнуться',body)

    def test_absent_values_in_both_languages(self):
        body,_=render_post(self.job())
        for text in ('Zarada: nije navedena','Jezici: nije navedeno','Obrazovanje: nije navedeno','Način rada: nije naveden',
                     'Зарплата: не указана','Языки: не указано','Образование: не указано','Формат работы: не указан'):
            self.assertIn(text,body)

    def test_salary_equivalence(self):
        f=extract_four('',{'salary':'neto 81.300 RSD (mesečno)'})
        self.assertEqual(field_text(f,'salary','sr'),'81\u202f300 RSD mesečno, neto')
        self.assertEqual(field_text(f,'salary','ru'),'81\u202f300 RSD в месяц, нетто')

    def test_language_negation_and_level(self):
        f=extract_four('Uslovi:\nSrpski jezik nije obavezan\nZnanje engleskog jezika B2',{})
        self.assertIn('Srpski — nije navedeno',field_text(f,'languages','sr'))
        self.assertIn('Сербский — не указано',field_text(f,'languages','ru'))
        self.assertIn('Engleski — B2',field_text(f,'languages','sr'))
        self.assertIn('Английский — B2',field_text(f,'languages','ru'))

    def test_work_mode_translated(self):
        f=extract_four('Mesto rada: kancelarija Beograd',{})
        self.assertEqual(field_text(f,'work_mode','sr'),'rad u kancelariji')
        self.assertEqual(field_text(f,'work_mode','ru'),'работа в офисе')

    def test_unknown_translation_not_guessed(self):
        job=self.job();job['title']='Unseen specialist role'
        with self.assertRaises(TranslationRequired): render_post(job)
        job=self.job('Requirements\nDegree in a new specialized discipline')
        with self.assertRaises(TranslationRequired): render_post(job)
