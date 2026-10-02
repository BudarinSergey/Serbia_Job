"""Saved preview and quota-controlled daily import; no Telegram calls."""
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg



def run(keywords: str, location: str, limit: int, save: bool = False) -> int:
    load_dotenv(Path(__file__).resolve().parent / '.env')
    # All manual imports share the same daily quota as the hourly workflow.
    from database.postgres import connection_dsn
    if save:
        from database.jooble_schedule import run_daily
        try:
            return run_daily(connection_dsn(),keywords or None,location)
        except (psycopg.Error,OSError,ValueError):
            print('Jooble: проверьте PostgreSQL и настройки ежедневного сбора.')
            return 1
    try:
        with psycopg.connect(connection_dsn(),connect_timeout=10) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            rows=conn.execute('''SELECT title,company,locations,source_url FROM serbia_jobs.vacancies
                WHERE source='jooble' ORDER BY first_seen_at DESC,source_id LIMIT %s''',(limit,)).fetchall()
        for title,company,locations,url in rows:
            print(f'{title}\n{company or "не указано"} | {locations or "не указано"}\n{url}')
        print('Jooble: предпросмотр сохранённых объявлений, API-запросов нет.')
        return 0
    except (psycopg.Error,OSError,ValueError):
        print('Jooble: не удалось прочитать сохранённые объявления.')
        return 1

