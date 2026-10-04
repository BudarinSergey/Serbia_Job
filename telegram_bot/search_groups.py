"""Shared search groups; original source fields are never overwritten."""
import re
from jooble_classification import ALIASES, title_key
from normalization import fold

GROUPS = {
    'sales': 'Продажи и обслуживание клиентов',
    'office': 'Офис, финансы и управление',
    'it': 'IT и цифровые профессии',
    'marketing': 'Маркетинг и дизайн',
    'logistics': 'Логистика, склады и транспорт',
    'production': 'Производство и рабочие специальности',
    'engineering': 'Строительство и инженерия',
    'hospitality': 'Рестораны, гостиницы и туризм',
    'care': 'Медицина, образование и уход',
    'other': 'Другие вакансии',
}
SOURCE_GROUPS = {
    'sales': ['trgovina, prodaja', 'pozivni centri'],
    'office': ['računovodstvo, knjigovodstvo', 'finansije', 'bankarstvo', 'administracija',
               'ljudski resursi (HR)', 'pravo', 'ekonomija (opšte)', 'osiguranje, lizing', 'menadžment'],
    'it': ['IT'],
    'marketing': ['marketing, promocija', 'PR', 'dizajn'],
    'logistics': ['logistika', 'magacin', 'transport', 'saobraćaj'],
    'production': ['proizvodnja i montaža', 'održavanje', 'kontrola kvaliteta', 'zanatstvo'],
    'engineering': ['mašinstvo', 'elektrotehnika', 'građevina, geodezija', 'arhitektura', 'telekomunikacije', 'hemija'],
    'hospitality': ['ugostiteljstvo', 'priprema hrane', 'turizam'],
    'care': ['zdravstvo', 'farmacija', 'obrazovanje, briga o deci'],
    'other': ['ostalo', 'higijena', 'obezbeđenje', 'sport, rekreacija'],
}
CATEGORY_MAP = {fold(name).strip(): group for group,names in SOURCE_GROUPS.items() for name in names}
LEGACY = {'finance':'office','legal':'office','medicine':'care',
          **{x:x for x in ('sales','it','logistics','production','engineering','hospitality','other')}}
TITLE_RULES = {
    'sales': r'\b(?:sales|account manager|key account|customer (?:support|service)|prodav\w*|prodaj\w*|kasir\w*|call cent\w*)\b',
    'office': r'\b(?:accountant|accounting|bookkeeper|knjigov\w*|racunov\w*|finans\w*|financial|hr|recruit\w*|pravnik|lawyer|legal|administrat\w*)\b',
    'it': r'\b(?:developer|programer|software|devops|sysadmin|it administrator|data engineer|data scientist)\b',
    'marketing': r'\b(?:marketing|dizajner|designer|graphic design|seo|social media)\b',
    'logistics': r'\b(?:vozac\w*|driver|kurir\w*|courier|dostavljac\w*|magacion\w*|magacin\w*|warehouse|dispatcher|dispecer\w*|logistik\w*|logistics)\b',
    'production': r'\b(?:operater\w*|proizvod\w*|production|bravar\w*|zavarivac\w*|welder|serviser\w*|elektricar\w*|mehanicar\w*)\b',
    'engineering': r'\b(?:inzenjer\w*|engineer|arhitekt\w*|architect|gradevin\w*|construction|geodet\w*)\b',
    'hospitality': r'\b(?:kuvar\w*|cook|chef|konobar\w*|waiter|sanker\w*|bartender|sobar\w*|pekar\w*|baker|hotel receptionist)\b',
    'care': r'\b(?:lekar\w*|doctor|nurse|medicinsk\w*|farmaceut\w*|pharmacist|nastavnik\w*|ucitelj\w*|vaspitac\w*|teacher|negovatelj\w*)\b',
}


def category_group(category=None, title='', manual=None):
    if manual and manual.get('origin')=='MANUAL':
        return LEGACY.get(manual.get('category'), 'other')
    source = CATEGORY_MAP.get(fold(category or '').strip())
    if source is not None and source != 'other':
        return source
    normalized=fold(title)
    found={key for key,pattern in TITLE_RULES.items() if re.search(pattern,normalized)}
    if 'it' in found:
        found.discard('engineering')
    # A job title alone cannot reliably disambiguate overlapping professions.
    return next(iter(found)) if len(found)==1 else 'other'


CITY_GROUPS = {
    'zemun':'Beograd', 'земун':'Beograd',
    'novi beograd':'Beograd', 'нови београд':'Beograd', 'новый белград':'Beograd',
    'kac':'Novi Sad', 'каћ':'Novi Sad', 'кач':'Novi Sad',
    'sremska kamenica':'Novi Sad', 'сремска каменица':'Novi Sad',
}
CITY_LABELS = {'Beograd':'Белград', 'Novi Sad':'Нови-Сад'}


def city_group(city):
    value=ALIASES.get(title_key(city),city.strip())
    return CITY_GROUPS.get(fold(value),value)


def grouped_cities(cities):
    return list(dict.fromkeys(city_group(c) for c in cities))


def city_options(cities, remote_key):
    rest=set(grouped_cities(cities))-{'Beograd','Novi Sad'}
    return [[remote_key,'Удалённая работа'],['Beograd','Белград'],['Novi Sad','Нови-Сад']]+[
        [city,city] for city in sorted(rest,key=lambda x:(fold(x),x))]


def migrate_categories(keys):
    result=[]
    for key in keys:
        if key.startswith('source:'):
            group=category_group(key[7:])
        elif key.startswith('group:'):
            group=LEGACY.get(key[6:],'other')
        else:
            group=LEGACY.get(key,key if key in GROUPS else 'other')
        if group not in result: result.append(group)
    return result
