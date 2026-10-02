"""Persistent outbox: confirmed messages are not sent twice."""
from contextlib import closing
import json
import sqlite3
import time
from database.storage import DEFAULT_DB_PATH
from telegram_bot.client import ROOT, api, TelegramError
from telegram_bot.formatting import render, route


def publish(jobs, db_path=DEFAULT_DB_PATH, config=None):
    if config is None:
        config = json.loads((ROOT / 'telegram_bot/topics.json').read_text(encoding='utf-8'))
    chat_id = config['chat_id']
    with closing(sqlite3.connect(db_path, timeout=10)) as db:
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS telegram_outbox (
                chat_id INTEGER NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL,
                thread_id INTEGER NOT NULL, body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', message_id INTEGER,
                PRIMARY KEY(chat_id, source, source_id, thread_id))''')
            for job in jobs:
                for key in route(job):
                    db.execute('''INSERT INTO telegram_outbox
                        (chat_id, source, source_id, thread_id, body) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING''',
                        (chat_id, job.source, job.id, config['topics'][key]['message_thread_id'], render(job)))
        rows = db.execute("SELECT rowid, thread_id, body FROM telegram_outbox WHERE chat_id=? AND status='pending' ORDER BY rowid", (chat_id,)).fetchall()
        sent = 0
        if rows:
            me = api('getMe')
            if me['id'] != config['bot_id']:
                raise TelegramError('Bot does not match topics configuration.')
        for row_id, thread_id, body in rows:
            # Commit before sending; concurrent processes can claim each row only once.
            with db:
                claimed = db.execute("UPDATE telegram_outbox SET status='sending' WHERE rowid=? AND status='pending'", (row_id,)).rowcount
            if not claimed:
                continue
            try:
                result = api('sendMessage', chat_id=chat_id, message_thread_id=thread_id,
                             text=body, parse_mode='HTML', link_preview_options={'is_disabled': True},
                             disable_notification=True)
            except TelegramError as exc:
                with db:
                    db.execute('UPDATE telegram_outbox SET status=? WHERE rowid=?',
                               ('uncertain' if exc.uncertain else 'pending', row_id))
                raise
            with db:
                db.execute("UPDATE telegram_outbox SET status='sent', message_id=? WHERE rowid=?", (result['message_id'], row_id))
            sent += 1
            print(f'Telegram: опубликовано в теме {thread_id}, сообщение {result["message_id"]}', flush=True)
            time.sleep(3.2)
        uncertain = db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE chat_id=? AND status IN ('sending','uncertain')", (chat_id,)).fetchone()[0]
        if uncertain:
            print(f'Telegram: {uncertain} отправок требуют ручной сверки после обрыва связи; автоматически не повторяются.', flush=True)
        return sent
