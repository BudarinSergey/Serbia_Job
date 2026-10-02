"""Read the official latest-20 jobs RSS; no job-page scraping."""
from dataclasses import dataclass
from datetime import datetime, timezone
from calendar import timegm
from html.parser import HTMLParser
import re
import logging
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RSS_URL = "https://rss.infostud.com/poslovi/"


class InfostudError(RuntimeError):
    """The source could not be downloaded or parsed safely."""


@dataclass(frozen=True)
class Vacancy:
    id: str
    title: str
    url: str
    summary: str
    published_at: datetime | None
    source: str = "infostud"


@dataclass(frozen=True)
class FeedBatch:
    """Exact response bytes and the vacancies parsed from that response."""
    raw_content: bytes
    fetched_at: datetime
    jobs: list[Vacancy]
    source_url: str = RSS_URL


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value):
    parser = _Text()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


def parse_feed(content: bytes) -> list[Vacancy]:
    feed = feedparser.parse(content)
    if feed.get("bozo") or not feed.get("version"):
        raise InfostudError("Infostud returned invalid RSS/XML.")
    jobs = []
    seen = set()
    for index, entry in enumerate(feed.entries, 1):
        try:
            title = _plain(entry.get("title", ""))
            parts = urlsplit(entry.get("link", ""))
            match = re.fullmatch(r"/posao/.+/(\d+)/?", parts.path)
            if (not title or parts.scheme not in ("http", "https")
                    or parts.netloc != "poslovi.infostud.com" or not match):
                raise InfostudError("RSS job is missing a valid title or Infostud job URL.")
            job_id = match.group(1)
            if job_id in seen:
                continue
            published = entry.get("published_parsed")
            jobs.append(Vacancy(
                id=job_id, title=title,
                url=urlunsplit(("https", parts.netloc, parts.path, parts.query, "")),
                summary=_plain(entry.get("summary", "")),
                published_at=datetime.fromtimestamp(timegm(published), timezone.utc) if published else None,
            ))
            seen.add(job_id)
        except (InfostudError, ValueError, TypeError, OverflowError, OSError) as exc:
            logging.getLogger(__name__).warning("Skipping RSS entry %s: %s", index, type(exc).__name__)
    if not jobs:
        raise InfostudError("Infostud RSS contains no vacancies; check the source.")
    return jobs


def fetch_feed() -> FeedBatch:
    retry = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}), backoff_max=30, retry_after_max=60)
    try:
        with requests.Session() as session:
            session.headers.update({"User-Agent": "SerbiaJobMVP/0.1 (personal RSS reader)",
                                    "Accept": "application/rss+xml, application/xml, text/xml"})
            session.mount("https://", HTTPAdapter(max_retries=retry))
            response = session.get(RSS_URL, timeout=(10, 30))
            response.raise_for_status()
            content = response.content
            return FeedBatch(content, datetime.now(timezone.utc), parse_feed(content))
    except requests.RequestException as exc:
        raise InfostudError(f"Cannot download Infostud RSS: {exc}") from exc


def fetch_vacancies() -> list[Vacancy]:
    """Compatibility API for the existing SQLite/Telegram pipeline."""
    return fetch_feed().jobs
