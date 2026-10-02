"""Explicit, bounded detail import. No Telegram calls."""
import sys
import time


def enrich(limit=10):
    try:
        import psycopg
        from database.postgres import connection_dsn
        from database.details import pending_jobs, save_detail
        from sources.infostud_details import DetailClient, DetailError
        dsn = connection_dsn()
        jobs = pending_jobs(dsn, limit)
    except (ImportError, ValueError, OSError):
        print('Проверьте зависимости и настройки PostgreSQL.', file=sys.stderr)
        return 1
    except psycopg.Error:
        print('Не удалось подготовить PostgreSQL для описаний.', file=sys.stderr)
        return 1
    if not jobs:
        print('Нет вакансий без описания. Сначала загрузите RSS: --save-postgres.')
        return 0
    saved = failed = 0
    try:
        with DetailClient() as client:
            for index, (source_id, url) in enumerate(jobs):
                if index:
                    time.sleep(max(2, client.robots.crawl_delay('SerbiaJobMVP/0.1') or 0))
                try:
                    detail = client.fetch(source_id, url)
                    save_detail(detail, dsn)
                    saved += 1
                    print(f"{source_id}: {detail.status}, {len(detail.description or '')} символов; компания: {detail.fields['company'] or 'UNKNOWN'}", flush=True)
                except DetailError as exc:
                    failed += 1
                    print(f'{source_id}: {exc}', file=sys.stderr)
                    if str(exc) in ('HTTP 403', 'HTTP 429'):
                        break
                except psycopg.Error:
                    print('Ошибка сохранения PostgreSQL; текущая запись отменена.', file=sys.stderr)
                    return 1
    except DetailError as exc:
        print(f'Источник недоступен: {exc}', file=sys.stderr)
        return 1
    print(f'Страницы вакансий: сохранено {saved}, ошибок {failed}, не обработано {len(jobs)-saved-failed}.')
    return 1 if failed else 0
