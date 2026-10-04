"""PostgreSQL outbox with SQLite fencing, group-wide dedup, and one sender lock."""
from contextlib import contextmanager
import json
import time

from database.storage import DEFAULT_DB_PATH
from database.publication_migration import prepare, require_migration
from telegram_bot.client import api, TelegramError, ROOT
from telegram_bot.preview import render_post, destinations
from telegram_bot.localization import TranslationRequired

FORMAT_VERSION = 'four-fields-sr-ru-v1'
SEARCH_BUTTON = {'inline_keyboard': [[{
    'text': '🔎 Искать вакансии / Pronađi posao',
    'url': 'https://t.me/SerbiaJob_bot?start=search',
}]]}


def config_from_file():
    return json.loads((ROOT/'telegram_bot/topics.json').read_text(encoding='utf-8'))


@contextmanager
def publisher_connection(dsn, config, db_path):
    import psycopg
    with psycopg.connect(dsn,connect_timeout=10,autocommit=True) as conn:
        prepare(conn)
        require_migration(conn,db_path)
        key=int(config['chat_id'])
        acquired=conn.execute('SELECT pg_try_advisory_lock(%s)',(key,)).fetchone()[0]
        if not acquired:
            raise ValueError('Another PostgreSQL sender is active for this group')
        try:
            yield conn
        finally:
            if not conn.closed:
                conn.execute('SELECT pg_advisory_unlock(%s)',(key,))


def _prepare_posts(conn, config, source_ids):
    from telegram_bot.automatic_translation import translation_context
    with translation_context(conn,allow_network=True):
        return _prepare_posts_translated(conn,config,source_ids)


def _prepare_posts_translated(conn, config, source_ids):
    from psycopg.rows import dict_row
    chat=config['chat_id']
    # RSS is only a discovery window. Every prepared, never-queued saved job is eligible.
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            jobs=cur.execute('''SELECT v.* FROM serbia_jobs.vacancies v
                WHERE v.source='infostud' AND v.four_fields IS NOT NULL
                  AND v.four_fields_snapshot_id=v.detail_snapshot_id
                  AND (NOT EXISTS (
                    SELECT 1 FROM serbia_jobs.telegram_outbox o WHERE o.chat_id=%s
                    AND o.source=v.source AND o.source_id=v.source_id) OR EXISTS (
                    SELECT 1 FROM serbia_jobs.telegram_outbox o WHERE o.chat_id=%s
                    AND o.source=v.source AND o.source_id=v.source_id AND o.status='pending'))
                ORDER BY v.published_at NULLS LAST,v.source_id''',(chat,chat)).fetchall()
        for job in jobs:
            existing=conn.execute('''SELECT 1 FROM serbia_jobs.telegram_outbox
                WHERE chat_id=%s AND source=%s AND source_id=%s LIMIT 1''',
                (chat,job['source'],job['source_id'])).fetchone()
            if existing:
                pending=conn.execute('''SELECT 1 FROM serbia_jobs.telegram_outbox
                    WHERE chat_id=%s AND source=%s AND source_id=%s AND status='pending' LIMIT 1''',
                    (chat,job['source'],job['source_id'])).fetchone()
                if not pending:
                    continue
            try:
                body,topics=render_post(job)
            except TranslationRequired as exc:
                issue=str(exc)
                if existing:
                    conn.execute('''UPDATE serbia_jobs.telegram_outbox SET format_version=NULL,translation_issue=%s
                        WHERE chat_id=%s AND source=%s AND source_id=%s AND status='pending' ''',
                        (issue,chat,job['source'],job['source_id']))
                else:
                    for topic in destinations(job):
                        conn.execute('''INSERT INTO serbia_jobs.telegram_outbox
                            (chat_id,source,source_id,thread_id,body,status,translation_issue)
                            VALUES (%s,%s,%s,%s,'','pending',%s) ON CONFLICT DO NOTHING''',
                            (chat,job['source'],job['source_id'],config['topics'][topic]['message_thread_id'],issue))
                print(f"{job['source_id']}: ожидает проверки перевода — {issue}",flush=True)
                continue
            if existing:
                # Preserve destinations previously enqueued, even if today's routing differs.
                conn.execute('''UPDATE serbia_jobs.telegram_outbox SET body=%s,format_version=%s,translation_issue=NULL
                    WHERE chat_id=%s AND source=%s AND source_id=%s AND status='pending' ''',
                    (body,FORMAT_VERSION,chat,job['source'],job['source_id']))
            else:
                for topic in topics:
                    thread=config['topics'][topic]['message_thread_id']
                    conn.execute('''INSERT INTO serbia_jobs.telegram_outbox
                        (chat_id,source,source_id,thread_id,body,status,format_version)
                        VALUES (%s,%s,%s,%s,%s,'pending',%s) ON CONFLICT DO NOTHING''',
                        (chat,job['source'],job['source_id'],thread,body,FORMAT_VERSION))
        # Stale or missing extraction must never leave an old pending body eligible to send.
        conn.execute('''UPDATE serbia_jobs.telegram_outbox o SET format_version=NULL
            WHERE chat_id=%s AND source='infostud' AND status='pending' AND NOT EXISTS (
                SELECT 1 FROM serbia_jobs.vacancies v WHERE v.source=o.source AND v.source_id=o.source_id
                AND v.four_fields IS NOT NULL AND v.four_fields_snapshot_id=v.detail_snapshot_id)''',(chat,))
        _prepare_jooble(conn,config)
    return dict(conn.execute('''SELECT status,count(*) FROM serbia_jobs.telegram_outbox
        WHERE chat_id=%s GROUP BY status''',(chat,)).fetchall())


def _prepare_jooble(conn, config):
    from telegram_bot.jooble_preview import build_from_connection
    from database.jooble_classification import learn_rules
    learn_rules(conn)
    chat=config['chat_id']
    # Disable all old pending drafts before evaluating the latest saved originals.
    conn.execute('''UPDATE serbia_jobs.telegram_outbox SET format_version=NULL,
        translation_issue='Jooble: ожидает проверки исходных данных'
        WHERE chat_id=%s AND source='jooble' AND status='pending' ''',(chat,))
    held=0
    for post in build_from_connection(conn):
        ident=post['source_id']
        if post['review_status']!='DRAFT' or not post['body'] or not post['topic_keys']:
            held+=1
            continue
        history=conn.execute('''SELECT status FROM serbia_jobs.telegram_outbox
            WHERE chat_id=%s AND source='jooble' AND source_id=%s''',(chat,ident)).fetchall()
        if any(row[0] in ('sent','sending','uncertain') for row in history):
            continue
        # Only untouched pending messages may be rerouted after a manual correction.
        # Sent/sending/uncertain vacancies were excluded above.
        threads=[config['topics'][key]['message_thread_id'] for key in post['topic_keys']]
        conn.execute("DELETE FROM serbia_jobs.telegram_outbox WHERE chat_id=%s AND source='jooble' AND source_id=%s AND status='pending' AND NOT (thread_id=ANY(%s))",(chat,ident,threads))
        for thread in threads:
            conn.execute("""INSERT INTO serbia_jobs.telegram_outbox
                (chat_id,source,source_id,thread_id,body,status,format_version)
                VALUES (%s,'jooble',%s,%s,%s,'pending',%s)
                ON CONFLICT (chat_id,source,source_id,thread_id) DO UPDATE SET
                body=EXCLUDED.body,format_version=EXCLUDED.format_version,translation_issue=NULL
                WHERE telegram_outbox.status='pending' """,
                (chat,ident,thread,post['body'],FORMAT_VERSION))
    if held:
        print(f'Jooble: {held} объявлений оставлено на проверке данных или возможных дублей.',flush=True)


def prepare_queue(dsn, source_ids=None, config=None, db_path=DEFAULT_DB_PATH):
    config=config or config_from_file()
    with publisher_connection(dsn,config,db_path) as conn:
        return _prepare_posts(conn,config,source_ids)


def publish(dsn, source_ids=None, config=None, db_path=DEFAULT_DB_PATH):
    config=config or config_from_file()
    with publisher_connection(dsn,config,db_path) as conn:
        _prepare_posts(conn,config,source_ids)
        conn.execute('ALTER TABLE serbia_jobs.vacancies ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ')
        rows=conn.execute('''SELECT o.id,o.thread_id,o.body,o.source,o.source_id FROM serbia_jobs.telegram_outbox o
            LEFT JOIN serbia_jobs.vacancies v ON v.source=o.source AND v.source_id=o.source_id
            WHERE o.chat_id=%s AND o.status='pending' AND o.format_version=%s AND o.delivery_issue IS NULL
            ORDER BY COALESCE(v.source_updated_at,v.published_at) DESC NULLS LAST,o.id''',
            (config['chat_id'],FORMAT_VERSION)).fetchall()
        waiting=conn.execute('''SELECT count(*) FILTER (WHERE status='pending' AND translation_issue IS NOT NULL),
            count(*) FILTER (WHERE status IN ('sending','uncertain'))
            FROM serbia_jobs.telegram_outbox WHERE chat_id=%s''',(config['chat_id'],)).fetchone()
        print(f'Очередь Telegram: готово {len(rows)}, ожидают перевода {waiting[0]}, требуют сверки отправки {waiting[1]}.',flush=True)
        cooldown=conn.execute("SELECT max(retry_at) FROM serbia_jobs.telegram_outbox WHERE chat_id=%s AND retry_at>now()",
                              (config['chat_id'],)).fetchone()[0]
        held=conn.execute("SELECT count(*) FROM serbia_jobs.telegram_outbox WHERE chat_id=%s AND delivery_issue IS NOT NULL",
                          (config['chat_id'],)).fetchone()[0]
        if held:
            print(f'Telegram: {held} сообщений требуют проверки ошибки содержимого.',flush=True)
        if cooldown:
            print(f'Telegram: ограничение частоты, отправка отложена до {cooldown}.',flush=True)
            return 0
        if not rows:
            return 0
        if api('getMe')['id']!=config['bot_id']:
            raise TelegramError('Bot does not match topics configuration')
        sent=0
        deferred=0
        for ident,thread,body,source,source_id in rows:
            if source=='jooble':
                from database.jooble_schedule import reserve_publication
                if not reserve_publication(conn,config['chat_id'],source_id):
                    deferred+=1
                    continue
            claimed=conn.execute("UPDATE serbia_jobs.telegram_outbox SET status='sending' WHERE id=%s AND status='pending'",(ident,)).rowcount
            if not claimed:
                continue
            try:
                result=api('sendMessage',chat_id=config['chat_id'],message_thread_id=thread,
                           text=body,parse_mode='HTML',link_preview_options={'is_disabled':True},
                           disable_notification=True,reply_markup=SEARCH_BUTTON)
            except TelegramError as exc:
                if exc.message_specific and not exc.uncertain:
                    conn.execute("UPDATE serbia_jobs.telegram_outbox SET status='pending',delivery_issue=%s WHERE id=%s",
                                 (str(exc),ident))
                    print(f'Telegram: {source}/{source_id} оставлена на проверке содержимого; очередь продолжается.',flush=True)
                    time.sleep(3.2)
                    continue
                if exc.error_code == 429 and not exc.uncertain:
                    conn.execute("UPDATE serbia_jobs.telegram_outbox SET status='pending',retry_at=now()+(%s * interval '1 second') WHERE id=%s",
                                 (max(1,exc.retry_after or 3600),ident))
                    raise
                conn.execute('UPDATE serbia_jobs.telegram_outbox SET status=%s WHERE id=%s',
                             ('uncertain' if exc.uncertain else 'pending',ident))
                raise
            # A malformed success response is ambiguous; leave sending, never auto-repeat.
            if not isinstance(result.get('message_id'),int):
                raise TelegramError('sendMessage result has no valid message ID',uncertain=True)
            conn.execute("UPDATE serbia_jobs.telegram_outbox SET status='sent',message_id=%s WHERE id=%s",(result['message_id'],ident))
            sent+=1
            print(f'Telegram: опубликовано в теме {thread}, сообщение {result["message_id"]}',flush=True)
            time.sleep(3.2)
        if deferred:
            print(f'Jooble: отложено сообщений до следующих суток: {deferred}; лимит 50 вакансий.',flush=True)
        return sent


def run_prepare():
    import sys
    import psycopg
    import sqlite3
    from database.postgres import connection_dsn
    try:
        counts=prepare_queue(connection_dsn())
    except (psycopg.Error,sqlite3.Error,OSError,ValueError,KeyError):
        print('Подготовка очереди не выполнена: проверьте перенос истории и настройки.',file=sys.stderr)
        return 1
    print(f'Очередь PostgreSQL: {counts}. Сообщения не отправлялись.')
    return 0
