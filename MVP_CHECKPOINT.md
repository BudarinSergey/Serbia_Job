# Stage 1 MVP checkpoint — 2026-10-01

Accepted MVP: Infostud RSS → PostgreSQL → processing → existing Telegram forum group.
Hourly polling, persistent publication history and duplicate protection are implemented.
Bad RSS entries are skipped; confirmed Telegram content errors are held for review
without blocking subsequent messages. Telegram flood-wait deadlines persist in PostgreSQL.
106 tests passed during verification of the error-isolation change (no live sends).

Accepted limitations: latest-20 RSS discovery, keyword-based category tags, and
vacancies awaiting translation. Personal filtered notifications are not implemented.

## Restoring this checkpoint

This repository is a source-code checkpoint, not a backup of the running database.
Keep the current .env, telegram_bot/topics.json, PostgreSQL database and fenced legacy
SQLite database separately and privately. The publication history and migration markers
must be restored together to preserve protection against re-publication.
Do not run main.py against an empty or mismatched database as a restoration shortcut.
The existing group/topics must be reused; do not recreate them.

The example .env contains no secrets. Runtime settings, local models, virtual environments,
SQLite files and backups are excluded. Reinstall dependencies into a new virtual environment
when restoring on another machine. Keep PostgreSQL schema and history from a proper backup.
