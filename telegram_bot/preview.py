"""Read-only PostgreSQL post preview. Does not import the Telegram API client."""
from contextlib import closing
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from urllib.parse import urlsplit

from database.storage import DEFAULT_DB_PATH
from telegram_bot.formatting import route, sector

ROOT = Path(__file__).resolve().parents[1]
TOPICS = {'belgrade':'Белград', 'novi_sad':'Нови-Сад', 'other_cities':'Другие города', 'remote':'Удалённая работа'}
LANGUAGES = {'en':'Английский','sr':'Сербский','de':'Немецкий','ru':'Русский','fr':'Французский','it':'Итальянский','es':'Испанский'}
OBLIGATION = {'REQUIRED':'требуется','PREFERRED':'желателен','NOT_REQUIRED':'не требуется','UNKNOWN':'обязательность не уточнена'}


def known(fields, key):
    item = (fields or {}).get(key) or {}
    if item.get('status') == 'REVIEW':
        return None, 'требует уточнения'
    return (item.get('value'), None) if item.get('status')=='KNOWN' else (None, 'не указано')


def money(value):
    n = Decimal(value)
    return format(n, ',.2f').rstrip('0').rstrip('.').replace(',', '\u202f').replace('.', ',')


def salary_text(fields):
    from telegram_bot.localization import field_text
    return field_text(fields, 'salary', 'ru')


def language_text(fields):
    from telegram_bot.localization import field_text
    return field_text(fields, 'languages', 'ru')


def education_text(fields):
    from telegram_bot.localization import field_text
    return field_text(fields, 'education', 'ru')


def destinations(job):
    if job.get('source')=='jooble' and 'classification_topics' in job:
        return job['classification_topics']
    mode, _ = known(job.get('four_fields'), 'work_mode')
    if mode=='REMOTE':
        return ['remote']
    locations=job.get('locations')
    summary = 'Company - '+', '.join(locations) if locations else job.get('summary_original','')
    return route(SimpleNamespace(summary=summary))


def render_post(job):
    from telegram_bot.localization import TITLES, translate, field_text, TranslationRequired
    fields=job.get('four_fields') or {}
    # An updated page must not be paired with values from an older snapshot.
    if job.get('four_fields_snapshot_id') != job.get('detail_snapshot_id'):
        fields={}
    url=job['source_url']
    parts=urlsplit(url)
    source=job.get('source','infostud')
    allowed={'infostud':'poslovi.infostud.com','jooble':'rs.jooble.org'}
    if (parts.scheme!='https' or parts.netloc!=allowed.get(source)
            or (source=='jooble' and not parts.path.startswith('/jdp/'))):
        raise ValueError('Unexpected vacancy URL')
    company=job.get('company') or 'Poslodavac nije naveden'
    location=', '.join(job.get('locations') or []) or 'Mesto nije navedeno'
    topic_keys=destinations(dict(job,four_fields=fields))
    tags=[{'belgrade':'#Beograd','novi_sad':'#NoviSad','other_cities':'#DrugiGradovi','remote':'#Remote'}[key] for key in topic_keys]
    category=job.get('category_tag') or sector(job['title'])
    sr_category={'#логистика':'#Logistika','#IT':'#IT','#финансы':'#Finansije','#юриспруденция':'#Pravo',
                 '#медицина':'#Medicina','#общепит_и_гостиницы':'#Ugostiteljstvo','#продажи':'#Prodaja',
                 '#производство_и_сервис':'#ProizvodnjaIServis','#инженерия_и_строительство':'#InzenjerstvoIGradjevina',
                 '#другие_сферы':'#OstaleOblasti'}[category]
    tags.extend(dict.fromkeys((sr_category,category)))
    try:
        titles=([job['title'],job['reviewed_title_ru']] if job.get('reviewed_title_ru')
                else [translate(TITLES,job['title'],lang) for lang in ('sr','ru')])
    except TranslationRequired:
        # The original title is publishable; never substitute an invented translation.
        titles=[job['title']]
    titles=list(dict.fromkeys(titles))
    lines=[('💼 ' if index==0 else '')+'<b>'+escape(title)+'</b>'
           for index,title in enumerate(titles)]
    lines.extend(['', '🏢 '+escape(company[:250]), '📍 '+escape(location[:250])])
    labels={'sr':('🇷🇸','Zarada','Jezici','Obrazovanje','Način rada'),
            'ru':('🇷🇺','Зарплата','Языки','Образование','Формат работы')}
    for lang in ('sr','ru'):
        flag,pay,language,education,mode=labels[lang]
        lines.extend(['',flag,
            '💰 '+pay+': '+escape(field_text(fields,'salary',lang)),
            '🌐 '+language+': '+escape(field_text(fields,'languages',lang)),
            '🎓 '+education+': '+escape(field_text(fields,'education',lang)),
            '🏠 '+mode+': '+escape(field_text(fields,'work_mode',lang))])
    if job.get('detail_status')=='IMAGE_ONLY':
        lines.extend(['','📄 Opis je u slici — proverite original.','Описание размещено изображением — проверьте оригинал.'])
    lines += ['', f'<a href="{escape(url,quote=True)}">Detaljnije / Prijavite se · Подробнее / Откликнуться</a>', '', ' '.join(tags)]
    body='\n'.join(lines)
    # Conservative bound: raw HTML length in UTF-16 exceeds displayed text length.
    if len(body.encode('utf-16-le'))//2 > 3900:
        raise TranslationRequired('Bilingual post needs shortening without losing conditions: '+job['title'])
    return body,topic_keys


def read_history(db_path, chat_id):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('''SELECT source,source_id,thread_id,status,message_id
            FROM telegram_outbox WHERE chat_id=?''',(chat_id,)).fetchall()
    return rows


def history_label(rows, source_id):
    states={r[3] for r in rows if r[0]=='infostud' and r[1]==source_id}
    if states & {'sending','uncertain'}:
        return 'Нужна ручная сверка прежней отправки'
    if 'sent' in states:
        return 'Уже опубликована; повтор не планируется'+(' · есть запись в прежней очереди' if 'pending' in states else '')
    if 'pending' in states:
        return 'Уже в прежней очереди; новую отправку не создавать'
    return 'В истории отправок не найдена'


def build_preview(dsn, limit=10, db_path=DEFAULT_DB_PATH, config=None):
    import psycopg
    from telegram_bot.automatic_translation import translation_context
    with psycopg.connect(dsn,connect_timeout=10) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        with translation_context(conn):
            return _build_preview(dsn,limit,db_path,config)


def _build_preview(dsn, limit=10, db_path=DEFAULT_DB_PATH, config=None):
    import psycopg
    from psycopg.rows import dict_row
    config=config or json.loads((ROOT/'telegram_bot/topics.json').read_text(encoding='utf-8'))
    from database.publication_migration import sqlite_token, require_migration
    migrated=bool(sqlite_token(db_path))
    history=[] if migrated else read_history(db_path,config['chat_id'])
    with psycopg.connect(dsn,connect_timeout=10,row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        if migrated:
            require_migration(conn,db_path)
            with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
                history=cur.execute('''SELECT source,source_id,thread_id,status,message_id
                    FROM serbia_jobs.telegram_outbox WHERE chat_id=%s''',(config['chat_id'],)).fetchall()
        # Include the most informative examples first, then newest IDs.
        jobs=conn.execute('''SELECT source_id,title,source_url,company,locations,summary_original,
            four_fields,detail_status,detail_snapshot_id,four_fields_snapshot_id
            FROM serbia_jobs.vacancies WHERE source='infostud' AND four_fields IS NOT NULL
            ORDER BY (salary_min IS NOT NULL OR salary_max IS NOT NULL) DESC,
                (language_requirements IS NOT NULL) DESC, published_at DESC NULLS LAST, source_id DESC LIMIT %s''',(limit,)).fetchall()
    posts=[]
    for job in jobs:
        body,keys=render_post(job)
        if any(key not in config['topics'] for key in keys):
            raise ValueError('Missing existing Telegram topic')
        posts.append({'id':job['source_id'],'title':job['title'],'body':body,
                      'topics':[TOPICS[k] for k in keys], 'history':history_label(history,job['source_id'])})
    counts={state:sum(r[3]==state for r in history) for state in sorted({r[3] for r in history})}
    return posts,counts


def run(limit=10):
    import sys
    try:
        import psycopg
        from database.postgres import connection_dsn
        posts,counts=build_preview(connection_dsn(),limit)
    except (ImportError,ValueError,OSError,sqlite3.Error):
        print('Не удалось подготовить предпросмотр: проверьте настройки, базу и историю отправок.',file=sys.stderr)
        return 1
    except psycopg.Error:
        print('Не удалось прочитать PostgreSQL для предпросмотра.',file=sys.stderr)
        return 1
    if not posts:
        print('Нет обработанных вакансий. Сначала выполните --normalize.')
    for post in posts:
        print('\nТемы: '+', '.join(post['topics'])+' | '+post['history'])
        print(post['body'])
    print(f'Предпросмотр: {len(posts)} постов. Ничего не отправлено. История: {counts}')
    return 0
