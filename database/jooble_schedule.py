"""Durable daily request reservations. A timeout also consumes the day's attempt."""
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import psycopg
from sources.jooble import fetch_jobs,JoobleError
from database.jooble import save_batch

SCHEMA='''CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_daily_runs (
 day DATE PRIMARY KEY, status TEXT NOT NULL, requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 keywords TEXT NOT NULL, location TEXT NOT NULL, saved INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_daily_publications (
 chat_id BIGINT NOT NULL, source_id TEXT NOT NULL, day DATE NOT NULL,
 PRIMARY KEY(chat_id,source_id,day));'''

def today():
    return datetime.now(ZoneInfo('Europe/Belgrade')).date()

def run_daily(dsn,keywords=None,location=None,day=None):
    key=os.environ.get('JOOBLE_API_KEY','').strip()
    if not key:
        print('Jooble: ключ не настроен; ежедневный сбор пропущен.',flush=True)
        return 0
    day=day or today()
    keywords=keywords or os.environ.get('JOOBLE_KEYWORDS','posao')
    location=location or os.environ.get('JOOBLE_LOCATION','Srbija')
    with psycopg.connect(dsn,connect_timeout=10) as conn:
        conn.execute(SCHEMA)
        conn.execute('SELECT pg_advisory_xact_lock(749312802)')
        # Historical snapshots are the only known requests before this ledger existed.
        conn.execute('''CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_request_baseline (
            id INTEGER PRIMARY KEY CHECK(id=1), requests INTEGER NOT NULL)''')
        conn.execute('''INSERT INTO serbia_jobs.jooble_request_baseline
            SELECT 1,count(*) FROM serbia_jobs.source_snapshots WHERE source='jooble'
            ON CONFLICT DO NOTHING''')
        used=conn.execute('''SELECT (SELECT requests FROM serbia_jobs.jooble_request_baseline WHERE id=1)
            +(SELECT count(*) FROM serbia_jobs.jooble_daily_runs)''').fetchone()[0]
        if used>=500:
            print('Jooble: достигнут локальный предел 500 учтённых запросов.',flush=True)
            return 0
        row=conn.execute('''INSERT INTO serbia_jobs.jooble_daily_runs(day,status,keywords,location)
            VALUES (%s,'reserved',%s,%s) ON CONFLICT DO NOTHING RETURNING day''',
            (day,keywords,location)).fetchone()
        if not row:
            print('Jooble: запрос за сегодня уже учтён; повторного обращения нет.',flush=True)
            return 0
    # Commit reservation BEFORE HTTP; restarts must not repeat uncertain requests.
    try:
        batch=fetch_jobs(key,keywords,location,50)
        count=save_batch(batch,dsn,max_jobs=50)
    except (JoobleError,psycopg.Error,OSError,ValueError):
        with psycopg.connect(dsn,connect_timeout=10) as conn:
            conn.execute("UPDATE serbia_jobs.jooble_daily_runs SET status='failed',error='Ошибка получения или сохранения; повтор в этот день отключён' WHERE day=%s",(day,))
        print('Jooble: ошибка ежедневного сбора; повтор сегодня отключён для сохранения квоты.',flush=True)
        return 1
    with psycopg.connect(dsn,connect_timeout=10) as conn:
        conn.execute("UPDATE serbia_jobs.jooble_daily_runs SET status='saved',saved=%s WHERE day=%s",(count,day))
    print(f'Jooble: один запрос за сутки, сохранено {count} объявлений (максимум 50). Учтено запросов: {used+1}/500.',flush=True)
    return 0

def reserve_publication(conn,chat,source_id,day=None):
    day=day or today()
    # Caller already holds the Telegram group advisory lock.
    conn.execute(SCHEMA)
    if conn.execute('SELECT 1 FROM serbia_jobs.jooble_daily_publications WHERE chat_id=%s AND source_id=%s AND day=%s',(chat,source_id,day)).fetchone():
        return True
    count=conn.execute('SELECT count(*) FROM serbia_jobs.jooble_daily_publications WHERE chat_id=%s AND day=%s',(chat,day)).fetchone()[0]
    if count>=50:return False
    conn.execute('INSERT INTO serbia_jobs.jooble_daily_publications VALUES (%s,%s,%s)',(chat,source_id,day))
    return True
