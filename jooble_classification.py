"""Conservative classification; original Jooble fields are never overwritten."""
import re
import unicodedata
from telegram_bot.formatting import normalize

CATEGORIES = {
    'logistics': ('Логистика', '#логистика'),
    'it': ('IT', '#IT'),
    'finance': ('Финансы', '#финансы'),
    'legal': ('Юриспруденция', '#юриспруденция'),
    'medicine': ('Медицина', '#медицина'),
    'hospitality': ('Общепит и гостиницы', '#общепит_и_гостиницы'),
    'sales': ('Продажи', '#продажи'),
    'production': ('Производство и сервис', '#производство_и_сервис'),
    'engineering': ('Инженерия и строительство', '#инженерия_и_строительство'),
    'other': ('Другие сферы', '#другие_сферы'),
}

def title_key(title):
    # Preserve accents, punctuation, seniority, qualifications and alphabet.
    return ' '.join(unicodedata.normalize('NFC', title).casefold().split())

def category_for(title, mappings=None):
    from telegram_bot.formatting import SECTOR_RULES
    mapped = (mappings or {}).get(title_key(title))
    if mapped and mapped['origin'] == 'MANUAL':
        return {'key': mapped['category'], 'origin': 'MANUAL', 'status': 'KNOWN'}
    matches = {tag for pattern, tag in SECTOR_RULES if re.search(pattern, normalize(title))}
    if len(matches) == 1:
        key = next(key for key, (_, tag) in CATEGORIES.items() if tag in matches)
        return {'key': key, 'origin': 'RULE', 'status': 'KNOWN'}
    return {'key': None, 'origin': 'RULE', 'status': 'REVIEW' if matches else 'UNKNOWN'}

# Exact aliases only: a mention in an employer name or arbitrary prose is not a location.
CITY_ALIASES = {
    'Beograd': ('beograd', 'belgrade', 'београд', 'белград'),
    'Novi Sad': ('novi sad', 'нови сад', 'нови-сад'),
    'Niš': ('niš', 'nis', 'ниш', 'ниш'),
    'Kragujevac': ('kragujevac', 'крагујевац'),
    'Subotica': ('subotica', 'суботица'),
    'Pančevo': ('pančevo', 'pancevo', 'панчево'),
    'Zrenjanin': ('zrenjanin', 'зрењанин'),
    'Čačak': ('čačak', 'cacak', 'чачак'),
    'Kraljevo': ('kraljevo', 'краљево'),
    'Kruševac': ('kruševac', 'krusevac', 'крушевац'),
    'Šabac': ('šabac', 'sabac', 'шабац'),
    'Smederevo': ('smederevo', 'смедерево'),
    'Valjevo': ('valjevo', 'ваљево'),
    'Leskovac': ('leskovac', 'лесковац'),
    'Vranje': ('vranje', 'врање'),
    'Sombor': ('sombor', 'сомбор'),
    'Novi Pazar': ('novi pazar', 'нови пазар'),
    'Ripanj': ('ripanj', 'рипањ'),
    'Stara Pazova': ('stara pazova', 'стара пазова'),
    'Nova Pazova': ('nova pazova', 'нова пазова'),
    'Inđija': ('inđija', 'indjija', 'инђија'),
    'Ruma': ('ruma', 'рума'),
    'Bačka Topola': ('bačka topola', 'backa topola', 'бачка топола'),
}
ALIASES = {title_key(alias): city for city, aliases in CITY_ALIASES.items() for alias in aliases}
REMOTE = {'remote', 'rad od kuće', 'rad od kuce', 'rad na daljinu', 'удалённо', 'удаленно'}
COUNTRY = {'srbija', 'serbia', 'србија', 'сербия', 'rs'}

def location_for(raw, snippet='', manual=None, explicit_remote=False):
    if manual:
        cities, remote = manual['cities'], manual['remote']
        origin, unknown, evidence = 'MANUAL', [], manual['reason']
    else:
        value = raw.strip()
        origin = 'jooble.location'
        if not value:
            # Only a labelled location line is evidence; never scan unrelated city mentions.
            lines = re.findall(r'(?im)^\s*(?:mesto rada|lokacija|location)\s*:\s*([^\n]+)', snippet)
            value = '; '.join(lines)
            origin = 'jooble.snippet' if value else 'UNKNOWN'
        evidence, cities, unknown, remote = value, [], [], explicit_remote
        for part in re.split(r'[,;/|\n]+|\s+&\s+|\s+i\s+', value):
            key = title_key(part)
            if not key or key in COUNTRY:
                continue
            if key in REMOTE:
                remote = True
            elif key in ALIASES:
                if ALIASES[key] not in cities:
                    cities.append(ALIASES[key])
            else:
                unknown.append(part.strip())
    topics = list(dict.fromkeys('belgrade' if c == 'Beograd' else 'novi_sad' if c == 'Novi Sad' else 'other_cities' for c in cities))
    if remote:
        topics.append('remote')
    status = 'REVIEW' if unknown else 'KNOWN' if topics else 'UNKNOWN'
    return dict(cities=cities, remote=remote, topics=topics, status=status, origin=origin,
                original=raw, evidence=evidence, unresolved=unknown)
