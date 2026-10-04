import unittest
from jooble_classification import title_key, category_for, location_for
from telegram_bot.jooble_preview import prepare
from tests.test_jooble_preview import job

class ClassificationTests(unittest.TestCase):
    def test_cautious_title_and_manual_priority(self):
        self.assertEqual(title_key('  SENIOR   C++ Developer '), title_key('Senior C++ Developer'))
        self.assertNotEqual(title_key('C++ Developer'), title_key('C Developer'))
        self.assertNotEqual(title_key('Junior Developer'), title_key('Senior Developer'))
        self.assertNotEqual(title_key('Vozač'), title_key('Vozac'))
        self.assertEqual(category_for('Sales Engineer')['status'], 'REVIEW')
        self.assertEqual(category_for('New occupation')['status'], 'UNKNOWN')
        result=category_for('Sales Engineer', {title_key('Sales Engineer'):dict(category='sales',origin='MANUAL')})
        self.assertEqual(result, dict(key='sales',origin='MANUAL',status='KNOWN'))

    def test_locations_do_not_infer_from_employer_or_prose(self):
        self.assertEqual(location_for('', 'Kompanija iz Beograda radi u Srbiji')['status'], 'UNKNOWN')
        self.assertEqual(location_for('Srbija')['cities'], [])
        self.assertEqual(location_for('Beograd ili Novi Sad')['status'], 'REVIEW')
        result=location_for('Beograd; Novi Sad; Remote; Srbija')
        self.assertEqual(result['cities'], ['Beograd','Novi Sad'])
        self.assertEqual(result['topics'], ['belgrade','novi_sad','remote'])
        self.assertEqual(location_for('', 'Mesto rada: Niš')['cities'], ['Niš'])
        self.assertEqual(location_for('Novi Beograd')['status'], 'REVIEW')
        self.assertEqual(location_for('Beograd, Unknown village')['status'], 'REVIEW')

    def test_post_uses_category_and_multiple_destinations(self):
        value=prepare(job(), {'location':'Beograd; Novi Sad; Remote'}, [])
        self.assertEqual(value['topic_keys'], ['belgrade','novi_sad','remote'])
        self.assertIn('#Logistika', value['body'])
        self.assertIn('Beograd, Novi Sad, Rad na daljinu', value['body'])
        self.assertEqual(value['location']['original'],'Beograd; Novi Sad; Remote')
        self.assertEqual(prepare(job(), {'location':'Unknown'}, [])['review_status'], 'REVIEW')
