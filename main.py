"""Run in PyCharm or with venv/Scripts/python.exe main.py."""
import argparse
from datetime import datetime, timedelta
import time
import sys
import sqlite3
from telegram_bot.publisher import publish
from telegram_bot.client import TelegramError
from database.storage import DEFAULT_DB_PATH, save_vacancies
from sources.infostud import InfostudError, fetch_vacancies, fetch_feed
from postgres_pipeline import run_cycle


CHECK_INTERVAL_SECONDS = 60 * 60


def preview(limit: int = 10, postgres: bool = False) -> int:
    """Inspect source data without SQLite writes or Telegram publication."""
    dsn = None
    if postgres:
        try:
            import psycopg
            from database.postgres import connection_dsn
            dsn = connection_dsn()
        except ImportError:
            print("Установите requirements-postgres.txt для PostgreSQL.", file=sys.stderr)
            return 1
        except ValueError:
            print("Для PostgreSQL задайте DATABASE_URL или PGHOST, PGPORT, PGUSER, PGPASSWORD в .env.", file=sys.stderr)
            return 1
    try:
        batch = fetch_feed()
    except InfostudError as exc:
        print(f"Ошибка загрузки: {exc}", file=sys.stderr)
        return 1
    print(f"Infostud: получено {len(batch.jobs)} вакансий; показано {min(limit, len(batch.jobs))}.")
    for index, job in enumerate(batch.jobs[:limit], 1):
        print(f"\n{index}. {job.title} [ID: {job.id}]\n   {job.summary}\n   {job.url}")
        print(f"   Дата: {job.published_at.isoformat() if job.published_at else 'не указана'}")
        print("   Зарплата / языки / условия: UNKNOWN (нет отдельных полей в RSS)")
    if postgres:
        from database.postgres import save_batch
        try:
            count = save_batch(batch, dsn)
        except (psycopg.Error, OSError, ValueError):
            # Connection errors can contain credentials; do not print the DSN.
            print("Ошибка PostgreSQL: проверьте подключение, доступ и схему. Пакет не сохранён.", file=sys.stderr)
            return 1
        print(f"PostgreSQL: сохранён исходный RSS и {count} вакансий.")
    return 0


def check_once() -> int:
    return run_cycle()


def run_hourly() -> None:
    while True:
        check_once()
        next_check = datetime.now().astimezone() + timedelta(seconds=CHECK_INTERVAL_SECONDS)
        print(f"Следующая проверка примерно: {next_check:%Y-%m-%d %H:%M:%S %z}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


def main(argv=None) -> int:
    # Windows redirected consoles can otherwise fail on Serbian characters.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Получение вакансий Infostud каждый час")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--search-bot', action='store_true', help='Личный поиск вакансий в Telegram без запуска сборщика')
    modes.add_argument('--jooble-classify', metavar='ID', help='Назначить категорию по названию и/или место Jooble')
    from jooble_classification import CATEGORIES
    parser.add_argument('--category', choices=list(CATEGORIES))
    parser.add_argument('--cities', help='Города через точку с запятой; пустая строка для только удалённой работы')
    parser.add_argument('--remote', choices=['yes','no'])
    modes.add_argument('--jooble-review', metavar='ID', help='Сохранить решение по вакансии Jooble')
    parser.add_argument('--decision', choices=['READY','DUPLICATE','NEEDS_INFO'])
    parser.add_argument('--reason', default='')
    parser.add_argument('--evidence', default='')
    modes.add_argument('--jooble-posts', action='store_true', help='Проверить дубли и подготовить двуязычные черновики из PostgreSQL без API и отправки')
    parser.add_argument('--output-dir', default='jooble-review', help='Папка для черновиков --jooble-posts')
    modes.add_argument('--jooble-preview', action='store_true', help='Предпросмотр сохранённых Jooble без API-запроса')
    modes.add_argument('--jooble-save', action='store_true', help='Ежедневный запрос Jooble до 50 вакансий с сохранением, без публикации')
    parser.add_argument('--keywords', default='', help='Поисковая фраза для Jooble')
    parser.add_argument('--location', default='Srbija', help='Место поиска Jooble')
    modes.add_argument("--once", action="store_true", help="Проверить, сохранить в PostgreSQL и опубликовать один раз")
    modes.add_argument("--migrate-telegram", action="store_true", help="Перенести SQLite-историю в PostgreSQL без отправки")
    modes.add_argument("--prepare-telegram", action="store_true", help="Обновить ожидающие посты PostgreSQL без отправки")
    modes.add_argument("--preview", action="store_true", help="Только показать вакансии без публикации и сохранения")
    modes.add_argument("--save-postgres", action="store_true", help="Показать вакансии и сохранить всю ленту в PostgreSQL без публикации")
    modes.add_argument("--fetch-details", action="store_true", help="Сохранить полные описания вакансий из PostgreSQL без публикации")
    modes.add_argument("--normalize", action="store_true", help="Извлечь языки, образование, формат работы и зарплату из сохранённых оригиналов")
    modes.add_argument("--telegram-preview", action="store_true", help="Показать посты PostgreSQL без отправки и изменения очереди")
    parser.add_argument("--limit", type=int, choices=range(5, 11), default=10, help="Число вакансий для предпросмотра: 5–10")
    args = parser.parse_args(argv)
    try:
        if args.search_bot:
            from telegram_bot.search_bot import serve
            serve()
            return 0
        if args.jooble_classify:
            from database.jooble_classification import assign
            from database.postgres import connection_dsn
            import psycopg
            try:
                assign(connection_dsn(),args.jooble_classify,args.category,
                       args.cities.split(';') if args.cities is not None else None,
                       args.remote=='yes' if args.remote is not None else None,args.reason)
            except ValueError as exc:
                print(str(exc))
                return 1
            except psycopg.Error:
                print('Назначение не сохранено: проверьте PostgreSQL.')
                return 1
            print('Назначение сохранено. Следующие совпадающие названия используют ручную категорию. Отправки не было.')
            return 0
        if args.jooble_review:
            from database.reviews import decide
            from database.postgres import connection_dsn
            import psycopg
            try:
                decide(connection_dsn(),args.jooble_review,args.decision,args.reason,args.evidence)
            except (ValueError,psycopg.Error):
                print('Решение не сохранено: проверьте ID, причину, подтверждение и данные вакансии.')
                return 1
            print('Решение сохранено. Для обновления очереди: --prepare-telegram. Сообщения не отправлялись.')
            return 0
        if args.jooble_posts:
            from database.postgres import connection_dsn
            from telegram_bot.jooble_preview import build, write_report
            import psycopg
            try:
                posts=build(connection_dsn())
                write_report(posts,args.output_dir)
            except (psycopg.Error,OSError,ValueError):
                print('Не удалось подготовить Jooble: проверьте PostgreSQL и папку вывода.',file=sys.stderr)
                return 1
            print(f'Jooble: черновиков {len(posts)}, требуют проверки {sum(p["review_status"]=="REVIEW" for p in posts)}. Telegram: ничего не отправлено.')
            return 0
        if args.jooble_preview or args.jooble_save:
            from jooble_pipeline import run
            return run(args.keywords, args.location, args.limit, save=args.jooble_save)
        if args.migrate_telegram:
            from database.publication_migration import run
            return run()
        if args.prepare_telegram:
            from telegram_bot.postgres_publisher import run_prepare
            return run_prepare()
        if args.telegram_preview:
            from telegram_bot.preview import run
            return run(args.limit)
        if args.normalize:
            from database.normalization import run
            return run()
        if args.fetch_details:
            from details_pipeline import enrich
            return enrich(args.limit)
        if args.preview or args.save_postgres:
            return preview(args.limit, postgres=args.save_postgres)
        if args.once:
            return check_once()
        print("Проверка сразу при запуске, затем через час после каждой проверки. Остановка: Ctrl+C или Stop.", flush=True)
        import threading
        from telegram_bot.search_bot import serve as run_search
        threading.Thread(target=run_search, name="telegram-search", daemon=True).start()
        run_hourly()
    except KeyboardInterrupt:
        print("\nПроверка вакансий остановлена.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
