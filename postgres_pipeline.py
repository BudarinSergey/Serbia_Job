"""The active hourly workflow after publication migration."""
import sys
import sqlite3
from datetime import datetime


def run_cycle():
    import psycopg
    from database.postgres import connection_dsn, save_batch
    from database.publication_migration import require_migration
    from database.normalization import normalize_saved
    from sources.infostud import fetch_feed, InfostudError
    from details_pipeline import enrich
    from telegram_bot.postgres_publisher import publish
    from telegram_bot.client import TelegramError
    print(f'[{datetime.now().astimezone():%Y-%m-%d %H:%M:%S %z}] Проверка Infostud → PostgreSQL',flush=True)
    try:
        dsn=connection_dsn()
        # Fail closed before any source work if the migration is incomplete.
        with psycopg.connect(dsn,connect_timeout=10) as conn:
            require_migration(conn)
        source_ids=[]
        failed=False
        try:
            batch=fetch_feed()
            save_batch(batch,dsn)
            source_ids=[j.id for j in batch.jobs]
            failed=bool(enrich(limit=20))
            normalize_saved(dsn)
        except InfostudError:
            print('Infostud временно недоступен; обрабатывается уже подготовленная очередь.',file=sys.stderr)
            failed=True
        from database.jooble_schedule import run_daily
        failed=bool(run_daily(dsn)) or failed
        sent=publish(dsn,source_ids)
        print(f'Telegram: отправлено {sent}. История и очередь — PostgreSQL.',flush=True)
        return 1 if failed else 0
    except (psycopg.Error,sqlite3.Error,OSError,ValueError,KeyError,TelegramError):
        print('Проверка не завершена: проверьте PostgreSQL, миграцию, настройки и состояние очереди. Неопределённые отправки не повторяются.',file=sys.stderr)
        return 1
