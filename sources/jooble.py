"""Serbian Jooble REST API. One explicit request; no quota-consuming retries."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from urllib.parse import quote, urlsplit

import requests

API_URL = 'https://rs.jooble.org/api'


class JoobleError(ValueError):
    pass


@dataclass(frozen=True)
class JoobleBatch:
    raw_content: bytes
    fetched_at: datetime
    query: dict


def parse_response(raw: bytes) -> list[dict]:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise JoobleError('Jooble: некорректный JSON.') from None
    if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
        raise JoobleError('Jooble: отсутствует список вакансий.')
    jobs, seen = [], set()
    for item in payload['jobs']:
        if not isinstance(item, dict):
            raise JoobleError('Jooble: некорректная вакансия.')
        identity = item.get('id')
        if isinstance(identity, bool) or not isinstance(identity, (str, int)) or not str(identity).strip():
            raise JoobleError('Jooble: отсутствует ID вакансии.')
        for field in ('title', 'link', 'snippet', 'company', 'location', 'salary', 'type', 'source', 'updated'):
            if item.get(field) is not None and not isinstance(item[field], str):
                raise JoobleError('Jooble: некорректный формат полей.')
        try:
            url = urlsplit(item.get('link') or '')
            valid = url.scheme == 'https' and url.netloc == 'rs.jooble.org' and url.path.startswith('/jdp/')
        except ValueError:
            valid = False
        if not (item.get('title') or '').strip() or not valid:
            raise JoobleError('Jooble: отсутствует название или корректная ссылка на вакансию.')
        if str(identity) not in seen:
            jobs.append(item)
            seen.add(str(identity))
    return jobs


def fetch_jobs(key: str, keywords: str, location: str = 'Srbija', limit: int = 10) -> JoobleBatch:
    if not key.strip():
        raise JoobleError('Добавьте сербский ключ JOOBLE_API_KEY в .env.')
    if not keywords.strip() or not location.strip() or not 1 <= limit <= 50:
        raise JoobleError('Укажите поисковую фразу, место и лимит 1–50.')
    query = dict(keywords=keywords.strip(), location=location.strip(), page=1, ResultOnPage=limit)
    try:
        response = requests.post(API_URL + '/' + quote(key.strip(), safe=''),
                                 json=query, timeout=(10, 30), allow_redirects=False)
    except requests.RequestException:
        # Exception URLs contain the secret key: never expose the original exception.
        raise JoobleError('Jooble: ошибка соединения. Автоматического повтора нет.') from None
    if response.status_code != 200:
        raise JoobleError(f'Jooble: HTTP {response.status_code}. Проверьте ключ для Сербии и квоту.')
    parse_response(response.content)
    return JoobleBatch(response.content, datetime.now(timezone.utc), query)
