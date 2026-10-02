import unittest
from normalization import extract_four, salary, amount, languages, education, work_mode


class ExtractionTests(unittest.TestCase):
    def test_missing_is_unknown_and_only_four_fields(self):
        fields=extract_four('We are a global company offering competitive compensation.', {})
        self.assertEqual(set(fields), {'languages','education','work_mode','salary'})
        self.assertTrue(all(f['status']=='UNKNOWN' and f['value'] is None for f in fields.values()))

    def test_language_obligation_and_level(self):
        fields=languages('Uslovi:\nZnanje engleskog jezika B2\nSrpski jezik nije obavezan\nPoznavanje nemačkog jezika je prednost')
        values={v['language']:v for v in fields['value']}
        self.assertEqual(values['en']['requirement'],'REQUIRED')
        self.assertEqual(values['en']['level'],'B2')
        self.assertEqual(values['sr']['requirement'],'NOT_REQUIRED')
        self.assertEqual(values['de']['requirement'],'PREFERRED')

    def test_mixed_language_clauses(self):
        values=languages('Requirements\nEnglish language skills suitable for international support; German is beneficial')['value']
        self.assertEqual([(v['language'],v['requirement']) for v in values],[('en','REQUIRED'),('de','PREFERRED')])
        self.assertEqual(languages('No English required')['value'][0]['requirement'],'NOT_REQUIRED')
        values=languages('English not required but Serbian is mandatory')['value']
        self.assertEqual([(v['language'],v['requirement']) for v in values],[('en','NOT_REQUIRED'),('sr','REQUIRED')])

    def test_shared_language_evidence(self):
        values=languages('Requirements\nGood German and English language skills')['value']
        self.assertEqual({v['language'] for v in values},{'de','en'})
        self.assertTrue(all(v['level'] is None for v in values))

    def test_language_of_ad_and_courses_are_not_requirements(self):
        self.assertIsNone(languages('We serve English clients.\nFree English language courses.')['value'])

    def test_language_conflict_requires_review(self):
        self.assertEqual(languages('English required\nEnglish not required')['status'],'REVIEW')

    def test_education_alternatives_and_preferences(self):
        fields=education('Uslov:\nminimum SSS, poželjno VSS ekonomskog usmerenja;', {})
        self.assertEqual([v['requirement'] for v in fields['value']],['REQUIRED','PREFERRED'])
        fields=education('Basic Qualifications\nUndergraduate degree in Computer Science and/or equivalent experience.',{})
        self.assertTrue(fields['value'][0]['has_alternatives'])

    def test_education_biography_not_candidate_requirement(self):
        self.assertIsNone(education('Our team consists of 20 people with a degree in Computer Science.',{})['value'])

    def test_education_metadata_has_unknown_obligation(self):
        value=education(None, {'educationRequirements':[{'level':'min','srName':'Srednja škola'}]})['value'][0]
        self.assertEqual(value['requirement'],'UNKNOWN')
        self.assertEqual(value['evidence']['source_path'],'original_payload.educationRequirements[0].srName')

    def test_remote_tools_do_not_mean_remote_work(self):
        self.assertIsNone(work_mode('Provide remote support using remote access and hybrid-cloud connectivity.')['value'])
        self.assertIsNone(work_mode('Remote work is not available.')['value'])

    def test_explicit_work_modes(self):
        for text, expected in [('Mesto rada: kancelarija Novi Sad','OFFICE'),('Remote position','REMOTE'),('Hybrid work model','HYBRID')]:
            self.assertEqual(work_mode(text)['value'],expected)
        self.assertEqual(work_mode('Possibility of remote work')['status'],'REVIEW')
        self.assertEqual(work_mode('Remote position\nOffice-based role')['status'],'REVIEW')

    def test_salary_display_beats_minor_units(self):
        f=salary('Redovnu platu u iznosu od 81.300,00',{'salary':'neto 81.300 RSD (mesečno)', 'unformattedSalary':{'from':'8130000'}})
        self.assertEqual(f['value'],{'min':'81300','max':'81300','currency':'RSD','period':'MONTH','basis':'NET'})
        self.assertEqual(len(f['evidence']),2)

    def test_salary_range_and_unknown_parts(self):
        f=salary('',{'salary':'neto 180.000 - 220.000 RSD (mesečno)'})
        self.assertEqual((f['value']['min'],f['value']['max']),('180000','220000'))
        f=salary('Zaradu u iznosu od 90.000 RSD',{})
        self.assertEqual(f['value']['min'],'90000')
        self.assertEqual(f['value']['max'],'90000')
        self.assertIsNone(f['value']['period'])
        self.assertIsNone(f['value']['basis'])

    def test_unknown_and_conflicting_salary(self):
        self.assertIsNone(salary('Competitive salary',{'unformattedSalary':{'from':'8130000','currency':'RSD'}})['value'])
        self.assertEqual(salary('Salary: 1000 EUR',{'salary':'2000 EUR'})['status'],'REVIEW')
        self.assertIsNone(salary('Salary review after 3 months',{})['value'])
        self.assertIsNone(salary('Salary increase of 50%',{})['value'])

    def test_localized_salary_numbers(self):
        for text,expected in [('81.300,00','81300.00'),('1,500.50','1500.50'),('120 000','120000'),('1.234.567','1234567')]:
            self.assertEqual(amount(text),expected)
        self.assertIsNone(amount('12.34.56'))

    def test_exact_evidence_is_in_original(self):
        text='Uslovi:\nZnanje engleskog jezika B2\nMinimum SSS\nMesto rada: kancelarija Beograd\nPlata: 90.000 RSD'
        for item in extract_four(text,{}).values():
            for proof in item['evidence']:
                self.assertIn(proof['quote'],text)
                if proof.get('context'):
                    self.assertIn(proof['context'],text)
