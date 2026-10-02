"""Transactional SQLite storage, shared by runs regardless of working directory."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

from sources.infostud import Vacancy

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "vacancies.sqlite3"


@dataclass(frozen=True)
class SaveResult:
    new_jobs: list[Vacancy]
    total: int


def save_vacancies(jobs: Iterable[Vacancy], db_path: Path = DEFAULT_DB_PATH) -> SaveResult:
    """Commit the entire batch or roll it back; return only newly inserted jobs."""
    with closing(sqlite3.connect(db_path, timeout=10)) as connection:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS vacancies (
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    PRIMARY KEY (source, source_id)
                )
            """)
            new_jobs = []
            seen_at = datetime.now(timezone.utc).isoformat()
            for job in jobs:
                cursor = connection.execute("""
                    INSERT INTO vacancies
                        (source, source_id, title, summary, url, published_at, first_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, source_id) DO NOTHING
                """, (job.source, job.id, job.title, job.summary, job.url,
                      job.published_at.isoformat() if job.published_at else None, seen_at))
                if cursor.rowcount == 1:
                    new_jobs.append(job)
            total = connection.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        return SaveResult(new_jobs, total)
