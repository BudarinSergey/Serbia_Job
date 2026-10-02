"""Fence SQLite writers, copy history, activate PostgreSQL only after both commits.

If interrupted between commits, the new publisher refuses to send until rerun.
No Telegram API calls. Old outbox rows remain unchanged and readable.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from database.storage import DEFAULT_DB_PATH
from database.postgres import SCHEMA_PATH


def prepare(conn):
    conn.execute('CREATE SCHEMA IF NOT EXISTS serbia_jobs')
    conn.execute(Path(__file__).with_name('publication_schema.sql').read_text(encoding='utf-8'))


def sqlite_token(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_control'").fetchone()
        if not exists:
            return None
        row=db.execute('SELECT migration_token FROM publication_control WHERE id=1').fetchone()
        return row[0] if row else None


def require_migration(conn, path=DEFAULT_DB_PATH):
    token=sqlite_token(path)
    if not token:
        raise ValueError('SQLite publication has not been fenced; run --migrate-telegram')
    row=conn.execute('''SELECT migration_token FROM serbia_jobs.publication_migrations
        WHERE source_path=%s AND migration_token=%s''',(str(Path(path).resolve()),token)).fetchone()
    if not row:
        raise ValueError('PostgreSQL/SQLite migration markers do not match')
    return token


def migrate(dsn, path=DEFAULT_DB_PATH, backup_dir=None):
    import psycopg
    path=Path(path).resolve()
    if not path.is_file():
        raise ValueError('Existing SQLite database is required')
    # Fast idempotent path: never overwrite statuses changed by the new publisher.
    with psycopg.connect(dsn,connect_timeout=10) as conn:
        prepare(conn)
        if sqlite_token(path):
            token=require_migration(conn,path)
            return {'already_migrated':True,'token':token}
    backup_dir=Path(backup_dir) if backup_dir else path.parent/'backups'
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup=backup_dir/('before-postgres-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.sqlite3')
    # SQLite backup API gives a consistent backup even if a legacy process is open.
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    with closing(sqlite3.connect(path,timeout=15)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            marker=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_control'").fetchone()
            if marker and db.execute('SELECT 1 FROM publication_control WHERE id=1').fetchone():
                with psycopg.connect(dsn,connect_timeout=10) as conn:
                    token=require_migration(conn,path)
                db.rollback()
                return {'already_migrated':True,'token':token}
            vacancies=db.execute('''SELECT source,source_id,title,summary,url,published_at,first_seen_at
                FROM vacancies ORDER BY source,source_id''').fetchall()
            queue=db.execute('''SELECT chat_id,source,source_id,thread_id,body,status,message_id
                FROM telegram_outbox ORDER BY chat_id,source,source_id,thread_id''').fetchall()
            if any(row[5] not in ('pending','sending','sent','uncertain') for row in queue):
                raise ValueError('Unknown legacy publication status')
            # An in-flight legacy send is copied as sending and is never auto-retried.
            with psycopg.connect(dsn,connect_timeout=10) as conn:
                conn.execute(SCHEMA_PATH.read_text(encoding='utf-8'))
                prepare(conn)
                previous=conn.execute('SELECT migration_token FROM serbia_jobs.publication_migrations WHERE source_path=%s', (str(path),)).fetchone()
                token=previous[0] if previous else str(uuid.uuid4())
                archive=json.dumps({'vacancies':vacancies,'telegram_outbox':queue},ensure_ascii=False).encode('utf-8')
                snapshot=conn.execute('''INSERT INTO serbia_jobs.source_snapshots
                    (source,source_url,fetched_at,content_sha256,raw_content)
                    VALUES ('legacy_sqlite',%s,%s,%s,%s) RETURNING id''',
                    (str(path),datetime.now(timezone.utc),hashlib.sha256(archive).hexdigest(),archive)).fetchone()[0]
                for source,ident,title,summary,url,published,seen in vacancies:
                    first=datetime.fromisoformat(seen)
                    date=datetime.fromisoformat(published) if published else None
                    if first.tzinfo is None: first=first.replace(tzinfo=timezone.utc)
                    digest=hashlib.sha256(json.dumps([title,summary,url,published],ensure_ascii=False).encode()).hexdigest()
                    conn.execute('''INSERT INTO serbia_jobs.vacancies
                        (source,source_id,title,summary_original,source_url,published_at,
                         first_seen_at,last_seen_at,snapshot_id,content_sha256)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source,source_id) DO NOTHING''',
                        (source,ident,title,summary,url,date,first,first,snapshot,digest))
                for chat,source,ident,thread,body,status,message in queue:
                    conn.execute('''INSERT INTO serbia_jobs.telegram_outbox
                        (chat_id,source,source_id,thread_id,body,legacy_body,status,message_id,origin)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'sqlite')
                        ON CONFLICT (chat_id,source,source_id,thread_id) DO UPDATE SET
                            body=EXCLUDED.body,legacy_body=EXCLUDED.legacy_body,status=EXCLUDED.status,
                            message_id=EXCLUDED.message_id
                        WHERE serbia_jobs.telegram_outbox.origin='sqlite' ''',
                        (chat,source,ident,thread,body,body,status,message))
                for original in queue:
                    chat,source,ident,thread,body,status,message=original
                    saved=conn.execute('''SELECT body,status,message_id FROM serbia_jobs.telegram_outbox
                        WHERE chat_id=%s AND source=%s AND source_id=%s AND thread_id=%s''', (chat,source,ident,thread)).fetchone()
                    if saved != (body,status,message):
                        raise ValueError('History verification failed')
                conn.execute('''INSERT INTO serbia_jobs.publication_migrations
                    (migration_token,source_path,backup_path,vacancy_count,outbox_count)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT (source_path) DO UPDATE SET
                        backup_path=EXCLUDED.backup_path,vacancy_count=EXCLUDED.vacancy_count,
                        outbox_count=EXCLUDED.outbox_count''', (token,str(path),str(backup),len(vacancies),len(queue)))
                db.execute('CREATE TABLE IF NOT EXISTS publication_control (id INTEGER PRIMARY KEY CHECK(id=1), migration_token TEXT NOT NULL)')
                db.execute('INSERT OR REPLACE INTO publication_control VALUES (1,?)',(token,))
                for action in ('INSERT','UPDATE','DELETE'):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS freeze_telegram_{action.lower()}
                        BEFORE {action} ON telegram_outbox BEGIN
                        SELECT RAISE(ABORT,'Telegram queue migrated to PostgreSQL; restart with updated main.py'); END''')
            # PG has committed, while the SQLite write lock still prevents legacy claims.
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return {'already_migrated':False,'token':token,'vacancies':len(vacancies),
            'queue_rows':len(queue),'backup':str(backup)}


def run():
    import sys
    import psycopg
    from database.postgres import connection_dsn
    try:
        result=migrate(connection_dsn())
    except (psycopg.Error,sqlite3.Error,OSError,ValueError):
        print('Перенос не завершён. Публикация PostgreSQL заблокирована до проверки маркеров.',file=sys.stderr)
        return 1
    print('Перенос истории:',result)
    return 0
