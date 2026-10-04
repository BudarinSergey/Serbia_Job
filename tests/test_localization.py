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
        self.assertIn('Высшее экономическое или смежное образование',body)
        self.assertIn('Visoka stručna sprema ekonomskog ili srodnog usmerenja',body)
        self.assertIn('Detaljnije / Prijavite se · Подробнее / Откликнуться',body)

    def test_absent_values_in_both_languages(self):
        body,_=render_post(self.job())
        for text in ('Zarada: nije navedena','Jezici: nije navedeno','Obrazovanje: nije navedeno','Način rada: nije naveden',
                     'Зарплата: не указана','Языки: не указано','Образование: не указано','Формат работы: не указан'):
            self.assertIn(text,body)

    def test_salary_equivalence(self):
        f=extract_four('',{'salary':'neto 81.300 RSD (mesečno)'})
        self.assertEqual(field_text(f,'salary','sr'),'81\u202f300 RSD, neto')
        self.assertEqual(field_text(f,'salary','ru'),'81\u202f300 RSD, нетто')

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
        body,_=render_post(job)
        self.assertEqual(body.count('Unseen specialist role'),1)
        job=self.job('Requirements\nDegree in a new specialized discipline')
        body,_=render_post(job)
        self.assertIn('Образование: Degree in a new specialized discipline',body)

    def test_failed_title_translation_uses_escaped_original_once(self):
        from unittest.mock import Mock
        from telegram_bot.automatic_translation import resolver,TranslationUnavailable
        lookup=Mock(side_effect=TranslationUnavailable('quota exhausted'))
        token=resolver.set(lookup)
        try:
            job=self.job();job['title']='Unseen <role> & title'
            body,topics=render_post(job)
            self.assertEqual(body.count('Unseen &lt;role&gt; &amp; title'),1)
            self.assertNotIn('<role>',body)
            self.assertIn('Зарплата: не указана',body)
            self.assertEqual(topics,['belgrade'])
        finally:resolver.reset(token)

    def test_education_max_removed_and_min_has_no_label(self):
        fields={'education':{'status':'KNOWN','value':[
            {'statement':'SSS/VSS','bound':'min'},
            {'statement':'Untranslated maximum','bound':'max'}]}}
        self.assertEqual(field_text(fields,'education','ru'),'SSS/VSS')
        self.assertEqual(field_text(fields,'education','sr'),'SSS/VSS')
        self.assertEqual(len(fields['education']['value']),2)
        fields['education']['value']=fields['education']['value'][1:]
        self.assertEqual(field_text(fields,'education','ru'),'не указано')

    def test_education_has_no_generated_qualifier(self):
        fields={'education':{'status':'KNOWN','value':[
            {'statement':'minimum SSS','requirement':'PREFERRED'}]}}
        self.assertEqual(field_text(fields,'education','ru'),'Среднее профессиональное образование (SSS)')
        self.assertEqual(field_text(fields,'education','sr'),'Srednja stručna sprema (SSS)')

    def test_salary_compact_optional_parts_and_range(self):
        for low,high,currency,basis,expected in [
            ('70000','80000','RSD',None,'70\u202f000–80\u202f000 RSD'),
            ('1000',None,'EUR','GROSS','1\u202f000 EUR, брутто'),
            (None,'500',None,None,'500')]:
            fields={'salary':{'status':'KNOWN','value':{'min':low,'max':high,'currency':currency,'basis':basis,'period':'HOUR'}}}
            self.assertEqual(field_text(fields,'salary','ru'),expected)
            self.assertEqual(fields['salary']['value']['period'],'HOUR')

    def test_jooble_has_link_without_snippet_disclaimer(self):
        job=self.job();job.update(source='jooble',source_url='https://rs.jooble.org/jdp/1')
        body,_=render_post(job)
        self.assertIn('https://rs.jooble.org/jdp/1',body)
        self.assertNotIn('Данные из краткого описания',body)
        self.assertNotIn('Podaci iz kratkog opisa',body)
