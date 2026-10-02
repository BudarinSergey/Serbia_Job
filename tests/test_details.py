import json
import unittest
from decimal import Decimal
from sources.infostud_details import parse_detail, DetailError, checked_url

URL = 'https://poslovi.infostud.com/posao/test/company/123'


def page(**changes):
    job = {'id': 123, 'textAd': '<h3>Requirements</h3><p>Knowledge of English.</p>',
           'companyName': 'Real company', 'cities': [{'name': 'Novi Sad'}],
           'companyProfile': {'companyName': 'Wrong parent company'},
           'seo': {'description': 'Generic advertisement'},
           'unformattedSalary': {'from': None, 'to': None, 'currency': None}}
    job.update(changes)
    return ('<html><script id="__NEXT_DATA__" type="application/json">' +
            json.dumps({'props': {'pageProps': {'job': job}}}) + '</script></html>').encode()


class DetailTests(unittest.TestCase):
    def test_original_not_seo_and_unknown_fields(self):
        result = parse_detail(page(), '123', URL)
        self.assertEqual(result.description, 'Requirements\nKnowledge of English.')
        self.assertEqual(result.fields['company'], 'Real company')
        self.assertEqual(result.fields['locations'], ['Novi Sad'])
        self.assertIsNone(result.fields['salary_min'])
        self.assertIsNone(result.fields['salary_currency'])

    def test_missing_description_and_wrong_identity_rejected(self):
        for raw in (page(textAd=None), page(textAd='<div></div>'), page(id=999), b'<html>Captcha</html>'):
            with self.subTest(raw=raw), self.assertRaises(DetailError):
                parse_detail(raw, '123', URL)

    def test_salary_only_explicit_values(self):
        result = parse_detail(page(salary='neto 120.000 - 150.000 RSD (mesečno)', unformattedSalary={'from': 12000000, 'to': 15000000, 'currency': 'RSD'}), '123', URL)
        self.assertEqual(Decimal(result.fields['salary_min']), Decimal('120000'))
        self.assertEqual(result.fields['salary_currency'], 'RSD')
        for salary in ({'from': '120.000,00', 'to': None, 'currency': 'RSD'},
                       {'from': 150000, 'to': 120000, 'currency': 'RSD'},
                       {'from': float('nan'), 'to': True, 'currency': 'RSD'}):
            result = parse_detail(page(unformattedSalary=salary), '123', URL)
            self.assertIsNone(result.fields['salary_min'])
            self.assertIsNone(result.fields['salary_currency'])

    def test_no_language_inference_from_text(self):
        result = parse_detail(page(textAd='<p>This entire job is in English.</p>'), '123', URL)
        self.assertNotIn('language_requirements', result.fields)

    def test_url_boundary(self):
        self.assertEqual(checked_url(URL + '?utm_source=rss', '123'), URL)
        for url in (URL.replace('https:', 'http:'), URL.replace('poslovi.infostud.com', 'example.com'), URL.replace('123', '999')):
            with self.assertRaises(DetailError):
                checked_url(url, '123')

    def test_image_only_and_hidden_tracking_are_not_full_text(self):
        html = '<img src="ad.jpg"><div style="display: none"><ul><li>Reference: tracking-token</li></ul></div>'
        result = parse_detail(page(textAd=html), '123', URL)
        self.assertIsNone(result.description)
        self.assertEqual(result.status, 'IMAGE_ONLY')
        result = parse_detail(page(textAd='<p>Real description<br/>Second line</p>' + html), '123', URL)
        self.assertEqual(result.description, 'Real description\nSecond line')
        self.assertEqual(result.status, 'TEXT_WITH_IMAGES')
