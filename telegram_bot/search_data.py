"""Read-only search projection. Never normalizes or updates stored vacancies."""
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from jooble_classification import ALIASES, CATEGORIES, REMOTE, category_for, location_for, title_key
from normalization import extract_four, salary
from telegram_bot.search_groups import GROUPS, category_group, city_group, grouped_cities

TZ = ZoneInfo('Europe/Belgrade')
REMOTE_KEY = '__remote__'
MISSING = {'', 'unknown', 'not_specified', 'not specified', 'none', 'null', 'n/a', 'не указано'}


def clean(value):
    return value.strip() if isinstance(value, str) and value.strip().casefold() not in MISSING else None


def instant(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=TZ)
    if isinstance(value, str):
        try:
            return instant(datetime.fromisoformat(value.replace('Z', '+00:00')))
        except ValueError:
            pass
    return None


def active(job, now):
    if job.get('closed'):
        return False
    deadline = job.get('deadline')
    if isinstance(deadline, str) and re.fullmatch(r'\d{2}\.\d{2}\.\d{4}\.?', deadline):
        try:
            return now.astimezone(TZ).date() <= datetime.strptime(deadline.rstrip('.'), '%d.%m.%Y').date()
        except ValueError:
            pass
    if isinstance(deadline, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', deadline):
        try:
            return now.astimezone(TZ).date() <= datetime.fromisoformat(deadline).date()
        except ValueError:
            pass
    expiry = instant(deadline)
    if expiry:
        return now <= expiry
    first = instant(job.get('first_seen_at'))
    return first is not None and first <= now <= first + timedelta(days=30)


def salary_match(job, minimum, include_unknown=True):
    """Compare monthly NET RSD only; incompatible units remain incomparable."""
    if minimum is None:
        return True
    pay = job.get('pay') or {}
    low, high = pay.get('min'), pay.get('max')
    comparable = (pay.get('currency') == 'RSD' and pay.get('period') == 'MONTH'
                  and pay.get('basis') == 'NET' and (low is not None or high is not None))
    if not comparable:
        return include_unknown
    if high is not None:
        return Decimal(str(high)) >= Decimal(str(minimum))
    # A lower bound below the target does not establish an upper bound.
    return Decimal(str(low)) >= Decimal(str(minimum)) or include_unknown


def matches(job, filters, now):
    if not active(job, now):
        return False
    places = set(filters.get('cities') or [])
    if places:
        if job.get('remote'):
            if REMOTE_KEY not in places:
                return False
        elif not places.intersection(job.get('cities') or []):
            return False
    categories = filters.get('categories') or []
    if categories and job.get('search_category') not in categories:
        return False
    return salary_match(job, filters.get('minimum'), filters.get('include_unknown', True))


def select(jobs, filters, now=None):
    now = now or datetime.now(timezone.utc)
    return sorted((j for j in jobs if matches(j, filters, now)),
                  key=lambda j: (instant(j.get('published_at')) or instant(j.get('first_seen_at'))
                                 or datetime.min.replace(tzinfo=timezone.utc),
                                 j['source'], j['source_id']), reverse=True)


def load(dsn):
    """One consistent read-only snapshot, including existing Jooble corrections."""
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10,
                         options='-c default_transaction_read_only=on -c statement_timeout=15000') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        jobs = conn.execute('''SELECT v.*, d.original_payload AS detail_payload
            FROM serbia_jobs.vacancies v LEFT JOIN serbia_jobs.detail_snapshots d
            ON d.id=v.detail_snapshot_id''').fetchall()
        snapshots = conn.execute('''SELECT DISTINCT s.id,s.raw_content
            FROM serbia_jobs.source_snapshots s JOIN serbia_jobs.vacancies v ON v.snapshot_id=s.id
            WHERE v.source='jooble' ''').fetchall()
        originals = {r['id']: {str(j['id']):j for j in json.loads(bytes(r['raw_content']))['jobs']}
                     for r in snapshots}
        def optional(table):
            if conn.execute('SELECT to_regclass(%s) AS name', ('serbia_jobs.'+table,)).fetchone()['name']:
                return conn.execute('SELECT * FROM serbia_jobs.'+table).fetchall()
            return []
        mappings = {r['title_key']:r for r in optional('jooble_title_categories')}
        decisions = {r['source_id']:r for r in optional('jooble_location_decisions')}
        excluded = {r['source_id'] for r in optional('jooble_exclusions')}
        translations = {}
        if conn.execute("SELECT to_regclass('serbia_jobs.translation_cache') AS name").fetchone()['name']:
            from telegram_bot.automatic_translation import Translator
            version = Translator(conn, allow_network=False).version
            translations = {r['source_text']:r for r in conn.execute(
                "SELECT source_text,sr,ru FROM serbia_jobs.translation_cache WHERE kind='title' AND version=%s",
                (version,)).fetchall()}
    output = []
    for job in jobs:
        if job['source']=='jooble' and job['source_id'] in excluded:
            continue
        payload = job.get('detail_payload') or {}
        fields = job.get('four_fields') or {}
        if job.get('four_fields_snapshot_id') != job.get('detail_snapshot_id'):
            fields = {}
        cities = [ALIASES.get(title_key(x), x.strip()) for x in job.get('locations') or [] if clean(x)]
        remote = any(title_key(x) in REMOTE for x in cities)
        cities = [x for x in cities if title_key(x) not in REMOTE]
        cat = clean(job.get('category'))
        manual = mappings.get(title_key(job['title'])) if job['source']=='jooble' else None
        group = category_group(cat, job['title'], manual)
        translated = translations.get(job['title'], {})
        title_ru = clean((manual or {}).get('title_ru')) or clean(translated.get('ru'))
        if job['source']=='jooble':
            original = originals.get(job['snapshot_id'], {}).get(job['source_id'], {})
            from sources.infostud_details import plain_description
            snippet = plain_description(original.get('snippet') or '')
            fields = extract_four(snippet, {})
            fields['salary'] = salary('', {'salary': original.get('salary') or ''})
            decision = decisions.get(job['source_id'])
            if decision and decision['content_sha256'] != job['content_sha256']:
                decision = None
            loc = location_for(original.get('location') or ', '.join(cities), snippet, decision,
                               fields.get('work_mode', {}).get('value')=='REMOTE')
            cities, remote = loc['cities'], loc['remote']
            # Keep explicitly named suburbs even when the older Jooble alias list lacks them.
            for place in loc.get('unresolved', []):
                if city_group(place) != place and place not in cities:
                    cities.append(place)
            payload = original
        mode = fields.get('work_mode') or {}
        remote = remote or (mode.get('status')=='KNOWN' and mode.get('value')=='REMOTE')
        pay_field = fields.get('salary') or {}
        pay = pay_field.get('value') if pay_field.get('status')=='KNOWN' else None
        if not pay_field and (job.get('salary_min') is not None or job.get('salary_max') is not None):
            pay = {k:job.get('salary_'+k) for k in ('min','max','currency','period','basis')}
        langs = (fields.get('languages') or {})
        languages = langs.get('value') if langs.get('status')=='KNOWN' else None
        if not langs:
            languages = job.get('language_requirements')
        # Application/CV language alone is not a language skill requirement.
        languages = [x for x in languages or [] if clean(x.get('language')) and not re.search(
            r'\bCV\b|Prijave slati|radne biografije', (x.get('evidence') or {}).get('quote',''), re.I)]
        output.append(dict(job, cities=grouped_cities(cities), display_cities=cities, remote=remote, search_category=group,
                           title_ru=title_ru, title_sr=clean(translated.get('sr')),
                           category_label=GROUPS[group], original_category=cat, pay=pay, languages=languages,
                           deadline=payload.get('expirationDate') or payload.get('validThrough'),
                           closed=payload.get('active') is False or payload.get('applicationForbidden') is True))
    return output
