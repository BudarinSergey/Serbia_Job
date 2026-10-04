"""MyMemory without credentials/email; conservative persistent usage accounting."""
from datetime import datetime,timezone,timedelta
from html import unescape
import requests
import psycopg

from telegram_bot.automatic_translation import TranslationUnavailable,TranslationNeedsReview,validate
from telegram_bot.local_translation import TABLE

VERSION='mymemory-sr-ru-v1'
SCHEMA='''CREATE TABLE IF NOT EXISTS serbia_jobs.mymemory_usage (
 day DATE PRIMARY KEY, characters INTEGER NOT NULL DEFAULT 0 CHECK(characters>=0),
 blocked_until TIMESTAMPTZ)'''


def source_language(text):
    """Configured source language: Serbian Latin, without probabilistic detection."""
    return 'sr'


def reserve(dsn,characters):
    # Separate committed transaction: rollback of publication cannot reset usage.
    with psycopg.connect(dsn,connect_timeout=10) as conn:
        conn.execute(SCHEMA)
        conn.execute('SELECT pg_advisory_xact_lock(749312801)')
        if conn.execute('SELECT 1 FROM serbia_jobs.mymemory_usage WHERE blocked_until>now() LIMIT 1').fetchone():
            raise TranslationUnavailable('MyMemory: квота исчерпана, действует пауза')
        day=datetime.now(timezone.utc).date()
        row=conn.execute('''INSERT INTO serbia_jobs.mymemory_usage (day,characters)
            VALUES (%s,%s) ON CONFLICT(day) DO UPDATE
            SET characters=serbia_jobs.mymemory_usage.characters+EXCLUDED.characters
            WHERE serbia_jobs.mymemory_usage.characters+EXCLUDED.characters<=5000
            RETURNING characters''',(day,characters)).fetchone()
        if not row:
            raise TranslationUnavailable('MyMemory: дневной лимит 5000 символов достигнут')


def block_quota(dsn):
    with psycopg.connect(dsn,connect_timeout=10) as conn:
        conn.execute(SCHEMA)
        conn.execute('''INSERT INTO serbia_jobs.mymemory_usage (day,blocked_until)
            VALUES (%s,%s) ON CONFLICT(day) DO UPDATE SET blocked_until=EXCLUDED.blocked_until''',
            (datetime.now(timezone.utc).date(),datetime.now(timezone.utc)+timedelta(hours=24)))


def request_translation(text,source,target,dsn):
    if not text.strip() or len(text.encode('utf-8'))>500:
        raise TranslationNeedsReview('MyMemory: фраза превышает 500 байт; нужна проверка')
    reserve(dsn,len(text))
    try:
        response=requests.get('https://api.mymemory.translated.net/get',
            params={'q':text,'langpair':f'{source}|{target}'},timeout=(10,25),allow_redirects=False)
        if response.status_code!=200:
            if response.status_code==429:
                block_quota(dsn)
            raise TranslationUnavailable('MyMemory: HTTP '+str(response.status_code))
        data=response.json()
        if not isinstance(data,dict):
            raise TranslationUnavailable('MyMemory: некорректный ответ')
        if data.get('quotaFinished') is True or str(data.get('responseStatus'))=='429':
            block_quota(dsn)
            raise TranslationUnavailable('MyMemory: квота сервиса исчерпана; пауза 24 часа')
        if str(data.get('responseStatus'))!='200':
            raise TranslationUnavailable('MyMemory: сервис не выполнил перевод')
        value=data.get('responseData',{}).get('translatedText')
        if not isinstance(value,str) or not value.strip():
            raise TranslationNeedsReview('MyMemory: пустой перевод')
        if any(marker in value.upper() for marker in ('MYMEMORY WARNING','QUERY LENGTH LIMIT','INVALID LANGUAGE PAIR','USED ALL AVAILABLE FREE TRANSLATIONS')):
            raise TranslationUnavailable('MyMemory: служебное сообщение вместо перевода')
        value=unescape(value).strip()
        if value.casefold()==text.strip().casefold():
            raise TranslationNeedsReview('MyMemory: перевод совпал с оригиналом, нужна проверка')
        return value
    except (requests.RequestException,TypeError,AttributeError,ValueError) as exc:
        if isinstance(exc,TranslationUnavailable):raise
        raise TranslationUnavailable('MyMemory: ошибка соединения или ответа') from None


def mymemory_translate(text,dsn):
    if len(text.encode('utf-8'))>500:
        raise TranslationNeedsReview('MyMemory: фраза превышает 500 байт; нужна проверка')
    source=source_language(text)
    pair={target:text if source==target else request_translation(text,source,target,dsn)
          for target in ('sr','ru')}
    pair['sr']=pair['sr'].translate(TABLE)
    try:
        return validate(text,pair)
    except TranslationUnavailable:
        raise TranslationNeedsReview('MyMemory: результат не прошёл проверку текста или чисел') from None
