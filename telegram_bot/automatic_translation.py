"""Cached translation of display phrases; never extraction of missing facts."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
import re
import requests

resolver = ContextVar('translation_resolver', default=None)
VERSION = 'azure-standard-v3-1'
SCHEMA = '''CREATE TABLE IF NOT EXISTS serbia_jobs.translation_cache (
 kind TEXT NOT NULL, source_hash TEXT NOT NULL, source_text TEXT NOT NULL,
 version TEXT NOT NULL, sr TEXT NOT NULL, ru TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(kind,source_hash,version))'''


class TranslationUnavailable(ValueError):
    pass


class TranslationNeedsReview(TranslationUnavailable):
    """Only this phrase failed; the service can still translate other phrases."""
    pass


def validate(source, pair):
    if set(pair) != {'sr','ru'}:
        raise TranslationUnavailable('Incomplete translation')
    for value in pair.values():
        if not isinstance(value,str) or not value.strip() or len(value)>4000 or '<' in value or '>' in value:
            raise TranslationUnavailable('Invalid translation')
        # Preserve numeric qualifications; semantic accuracy still depends on the service.
        if sorted(re.findall(r'\d+',source)) != sorted(re.findall(r'\d+',value)):
            raise TranslationUnavailable('Numeric information changed')
    return pair


def azure_translate(text):
    key=os.environ.get('AZURE_TRANSLATOR_KEY','').strip()
    if os.environ.get('AZURE_TRANSLATOR_TIER')!='F0' or not key:
        raise TranslationUnavailable('Configure an Azure Translator F0 resource')
    headers={'Ocp-Apim-Subscription-Key':key}
    region=os.environ.get('AZURE_TRANSLATOR_REGION','').strip()
    if region:
        headers['Ocp-Apim-Subscription-Region']=region
    try:
        response=requests.post('https://api.cognitive.microsofttranslator.com/translate',
            params=[('api-version','3.0'),('to','sr-Latn'),('to','ru'),('textType','plain')],
            headers=headers,json=[{'Text':text}],timeout=(10,25),allow_redirects=False)
        if response.status_code!=200:
            raise TranslationUnavailable('Translator unavailable or quota exhausted')
        data=response.json()
        if not isinstance(data,list) or len(data)!=1:
            raise TranslationUnavailable('Invalid response')
        entries=data[0]['translations']
        if len(entries)!=2:
            raise TranslationUnavailable('Incomplete response')
        pair={ {'sr-Latn':'sr','ru':'ru'}[item['to']]:item['text'] for item in entries }
        return validate(text,pair)
    except (requests.RequestException,KeyError,TypeError,ValueError):
        # No response bodies, credentials, or raw network exceptions in logs.
        raise TranslationUnavailable('Translation failed; vacancy remains pending') from None


class Translator:
    def __init__(self, conn, allow_network):
        self.conn=conn
        self.allow_network=allow_network
        self.failed=set()
        self.calls=0
        self.characters=0
        self.provider=os.environ.get('TRANSLATION_PROVIDER','azure')
        self.version=VERSION
        if self.provider=='local':
            from telegram_bot.local_translation import VERSION as local_version
            self.version=local_version
        elif self.provider=='google':
            from telegram_bot.google_translation import VERSION as google_version
            self.version=google_version
        elif self.provider=='mymemory':
            from telegram_bot.mymemory_translation import VERSION as mymemory_version
            self.version=mymemory_version

    def __call__(self,kind,text,lang):
        digest=hashlib.sha256(text.encode()).hexdigest()
        key=(kind,digest)
        with self.conn.cursor() as cur:
            # Explicit row factory works with both preview and publisher connections.
            from psycopg.rows import tuple_row
            cur.row_factory=tuple_row
            row=cur.execute('''SELECT sr,ru FROM serbia_jobs.translation_cache
                WHERE kind=%s AND source_hash=%s AND version=%s AND source_text=%s''',
                (kind,digest,self.version,text)).fetchone()
        if row:
            return row[0 if lang=='sr' else 1]
        if (not self.allow_network or key in self.failed or self.calls>=30
                or not text.strip() or len(text)>1500 or self.characters+2*len(text)>12000):
            raise TranslationUnavailable('No cached translation')
        self.calls+=1
        self.characters+=2*len(text)
        try:
            if self.provider=='local':
                from telegram_bot.local_translation import local_translate
                pair=local_translate(text)
            elif self.provider=='azure':
                pair=azure_translate(text)
            elif self.provider=='google':
                from telegram_bot.google_translation import google_translate
                pair=google_translate(text)
            elif self.provider=='mymemory':
                from telegram_bot.mymemory_translation import mymemory_translate
                pair=mymemory_translate(text,self.conn.info.dsn)
            else:
                raise TranslationUnavailable('Unknown translation provider')
        except TranslationUnavailable as exc:
            self.failed.add(key)
            phrase_only=isinstance(exc,TranslationNeedsReview)
            if self.provider!='local' and not phrase_only:
                self.allow_network=False  # Stop requests on external-service failures.
            if self.provider=='google':
                print('Google Translate: '+str(exc)+'. Новые запросы остановлены до следующей проверки.',flush=True)
            elif self.provider=='mymemory':
                message=(' Остальные фразы продолжают переводиться.' if phrase_only else
                         ' Новые запросы остановлены до следующей проверки.')
                print(str(exc)+'.'+message,flush=True)
            raise
        self.conn.execute('''INSERT INTO serbia_jobs.translation_cache
            (kind,source_hash,source_text,version,sr,ru) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING''',(kind,digest,text,self.version,pair['sr'],pair['ru']))
        return pair[lang]


@contextmanager
def translation_context(conn, allow_network=False):
    if allow_network:
        conn.execute(SCHEMA)
    else:
        from psycopg.rows import tuple_row
        with conn.cursor(row_factory=tuple_row) as cur:
            exists=cur.execute("SELECT to_regclass('serbia_jobs.translation_cache')").fetchone()[0]
        if not exists:
            yield
            return
    token=resolver.set(Translator(conn,allow_network))
    try:
        yield
    finally:
        resolver.reset(token)
