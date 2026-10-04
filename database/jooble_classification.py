"""Persistent title dictionary and auditable per-vacancy location corrections."""
import json
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from jooble_classification import CATEGORIES, ALIASES, title_key, category_for

SCHEMA = '''
CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_title_categories (
 title_key TEXT PRIMARY KEY, original_title TEXT NOT NULL, category TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('RULE','MANUAL')), reason TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
ALTER TABLE serbia_jobs.jooble_title_categories ADD COLUMN IF NOT EXISTS title_ru TEXT;
CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_exclusions (source_id TEXT PRIMARY KEY, reason TEXT NOT NULL, excluded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_location_decisions (
 source_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, cities JSONB NOT NULL,
 remote BOOLEAN NOT NULL, reason TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_classification_history (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, source_id TEXT NOT NULL,
 decision JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
'''

def learn_rules(conn):
    conn.execute(SCHEMA)
    with conn.cursor(row_factory=dict_row) as cur:
        jobs = cur.execute("SELECT title FROM serbia_jobs.vacancies WHERE source='jooble'").fetchall()
        for job in jobs:
            classification = category_for(job['title'])
            if classification['key']:
                cur.execute('''INSERT INTO serbia_jobs.jooble_title_categories
                    (title_key,original_title,category,origin,reason) VALUES (%s,%s,%s,'RULE','Правило по названию')
                    ON CONFLICT (title_key) DO UPDATE SET category=EXCLUDED.category,updated_at=now()
                    WHERE jooble_title_categories.origin='RULE' ''',
                    (title_key(job['title']), job['title'], classification['key']))

def load_decisions(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        exists = cur.execute("SELECT to_regclass('serbia_jobs.jooble_title_categories') AS name").fetchone()['name']
        if not exists:
            return {}, {}
        titles = cur.execute('SELECT * FROM serbia_jobs.jooble_title_categories').fetchall()
        locations = cur.execute('SELECT * FROM serbia_jobs.jooble_location_decisions').fetchall()
    return {r['title_key']: r for r in titles}, {r['source_id']: r for r in locations}

def assign(dsn, source_id, category=None, cities=None, remote=None, reason=''):
    if category is not None and category not in CATEGORIES:
        raise ValueError('Неизвестная категория')
    if not reason.strip() or (category is None and cities is None and remote is None):
        raise ValueError('Укажите назначение и причину')
    location_change = cities is not None or remote is not None
    if location_change and (cities is None or remote is None):
        raise ValueError('Для места укажите и города, и удалённую работу (yes/no)')
    if location_change:
        cities = list(dict.fromkeys(ALIASES.get(title_key(c), c.strip()) for c in cities if c.strip()))
        if (not cities and not remote) or any(len(c)>100 or any(x in c for x in '<>\r\n') for c in cities):
            raise ValueError('Укажите города либо удалённую работу')
    with psycopg.connect(dsn) as conn:
        conn.execute(SCHEMA)
        with conn.cursor(row_factory=dict_row) as cur:
            job = cur.execute("SELECT title,content_sha256 FROM serbia_jobs.vacancies WHERE source='jooble' AND source_id=%s FOR UPDATE",(source_id,)).fetchone()
        if not job:
            raise ValueError('Вакансия Jooble не найдена')
        if category:
            conn.execute('''INSERT INTO serbia_jobs.jooble_title_categories
                (title_key,original_title,category,origin,reason) VALUES (%s,%s,%s,'MANUAL',%s)
                ON CONFLICT (title_key) DO UPDATE SET category=EXCLUDED.category,origin='MANUAL',
                reason=EXCLUDED.reason,updated_at=now()''',
                (title_key(job['title']),job['title'],category,reason.strip()))
        if location_change:
            conn.execute('''INSERT INTO serbia_jobs.jooble_location_decisions
                (source_id,content_sha256,cities,remote,reason) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (source_id) DO UPDATE SET content_sha256=EXCLUDED.content_sha256,
                cities=EXCLUDED.cities,remote=EXCLUDED.remote,reason=EXCLUDED.reason,updated_at=now()''',
                (source_id,job['content_sha256'],Jsonb(cities),remote,reason.strip()))
        conn.execute('INSERT INTO serbia_jobs.jooble_classification_history (source_id,decision) VALUES (%s,%s)',
            (source_id,Jsonb(dict(title=job['title'],title_key=title_key(job['title']),category=category,
                                 cities=cities,remote=remote,reason=reason.strip(),content_sha256=job['content_sha256']))))

def backfill(dsn):
    with psycopg.connect(dsn) as conn:
        learn_rules(conn)
