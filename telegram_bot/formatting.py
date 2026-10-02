"""Conservative RSS routing and escaped Telegram HTML."""
import re
import unicodedata
from html import escape


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


def route(job):
    company, sep, location = job.summary.rpartition(' - ')
    if not sep or not location.strip():
        return ['other_cities']
    location = normalize(location)
    if re.search(r'\b(rad od kuce|rad na daljinu|remote|удаленно)\b', location):
        return ['remote']
    cities = [c.strip() for c in re.split(r'[,;/]', location) if c.strip()]
    routes = []
    for city in cities:
        if re.search(r'\b(beograd|belgrade|београд)\b', city):
            key = 'belgrade'
        elif re.search(r'\b(novi sad|нови сад)\b', city):
            key = 'novi_sad'
        elif any(x in city for x in ('srbija', 'serbia', 'vise lokacija', 'teren')):
            key = 'other_cities'
        else:
            key = 'other_cities'
        if key not in routes:
            routes.append(key)
    return routes or ['other_cities']


def sector(title):
    title = normalize(title)
    rules = [
        (r'vozac|freight|transport|logistik|magacion|magacin|sklad', '#логистика'),
        (r'program|developer|software|\bit\b', '#IT'),
        (r'knjigov|racunov|account|finans', '#финансы'),
        (r'pravnik|legal|lawyer', '#юриспруденция'),
        (r'farmace|medicin|lekar|nurse', '#медицина'),
        (r'kuvar|konobar|sanker|pekar|sobar|hotel', '#общепит_и_гостиницы'),
        (r'prodav|prodaj|sales|kasir', '#продажи'),
        (r'elektric|serviser|odrzavanje|tehnicar|proizvod', '#производство_и_сервис'),
        (r'engineer|inzenjer|gradevin', '#инженерия_и_строительство'),
    ]
    return next((tag for pattern, tag in rules if re.search(pattern, title)), '#другие_сферы')


def render(job):
    return (f'<b>{escape(job.title[:300])}</b>\n\n'
            f'{escape(job.summary[:1400])}\n\n'
            f'{sector(job.title)}\n\n'
            f'<a href="{escape(job.url, quote=True)}">Открыть вакансию на Infostud</a>')
