"""Read original textAd from public Infostud pages, never the SEO/AI summary."""
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from sources.infostud import InfostudError

AGENT = 'SerbiaJobMVP/0.1'


class DetailError(InfostudError):
    pass


class _PageData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = dict(attrs).get('id') == '__NEXT_DATA__'

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False

    def handle_data(self, value):
        if self.active:
            self.parts.append(value)


class _Description(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.images = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r'\s+', '', attrs.get('style', '').lower())
        hidden = (bool(self.stack and self.stack[-1][1]) or tag in ('script', 'style')
                  or 'hidden' in attrs or 'display:none' in style or 'visibility:hidden' in style)
        if tag == 'img' and not hidden:
            self.images += 1
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append((tag, hidden))
        if not hidden and tag in ('p', 'li', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        hidden = bool(self.stack and self.stack[-1][1])
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if not hidden and tag in ('p', 'li', 'div', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self.parts.append('\n')

    def handle_data(self, value):
        if not (self.stack and self.stack[-1][1]):
            self.parts.append(value)


def plain_description(value):
    parser = _Description()
    parser.feed(value)
    return '\n'.join(line for raw in ''.join(parser.parts).splitlines()
                     if (line := ' '.join(raw.split())))


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class JobDetail:
    source_id: str
    source_url: str
    fetched_at: datetime
    raw_content: bytes
    payload: dict
    description: str | None
    fields: dict
    status: str


def parse_detail(content: bytes, source_id: str, url: str) -> JobDetail:
    parser = _PageData()
    try:
        parser.feed(content.decode('utf-8-sig'))
        job = json.loads(''.join(parser.parts))['props']['pageProps']['job']
        if not isinstance(job, dict) or str(job.get('id')) != str(source_id):
            raise DetailError('Job ID mismatch')
        original = job.get('textAd')
        if not isinstance(original, str) or not original.strip():
            raise DetailError('Original textAd is absent; no SEO summary fallback')
        description = plain_description(original)
        visible = _Description()
        visible.feed(original)
        if not description and not visible.images:
            raise DetailError('Original description contains no text')
        status = ('TEXT_WITH_IMAGES' if description else 'IMAGE_ONLY') if visible.images else 'TEXT'
    except (UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise DetailError('Unrecognized Infostud page structure') from exc
    from normalization import salary
    pay = salary(description, job)['value'] or {}
    cities = job.get('cities')
    locations = [_text(c.get('name')) for c in cities if isinstance(c, dict)] if isinstance(cities, list) else []
    category = job.get('primaryCategory') or {}
    employment = job.get('employmentType') or {}
    fields = {
        'company': _text(job.get('companyDisplayName')) or _text(job.get('companyName')),
        'locations': list(dict.fromkeys(c for c in locations if c)) or None,
        'category': _text(category.get('name')) if isinstance(category, dict) else None,
        'employment_type': _text(employment.get('nameSr')) if isinstance(employment, dict) else None,
        'salary_min': pay.get('min'), 'salary_max': pay.get('max'),
        'salary_currency': pay.get('currency'),
    }
    return JobDetail(str(source_id), url, datetime.now(timezone.utc), content, job, description or None, fields, status)


def checked_url(url, source_id):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'poslovi.infostud.com'
            or not re.fullmatch(r'/posao/.+/' + re.escape(str(source_id)) + r'/?', parts.path)):
        raise DetailError('Unexpected job URL or redirect')
    return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


class DetailClient:
    def __enter__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': AGENT, 'Accept': 'text/html'})
        try:
            response = self.session.get('https://poslovi.infostud.com/robots.txt', timeout=(10, 25), allow_redirects=False)
            if response.status_code != 200:
                raise DetailError('Cannot verify robots.txt')
            self.robots = RobotFileParser()
            self.robots.parse(response.text.splitlines())
        except (requests.RequestException, DetailError) as exc:
            self.session.close()
            raise DetailError('Cannot verify source access rules') from exc
        return self

    def __exit__(self, *args):
        self.session.close()

    def fetch(self, source_id, url):
        url = checked_url(url, source_id)
        try:
            for _ in range(4):
                if not self.robots.can_fetch(AGENT, url):
                    raise DetailError('Page disallowed by robots.txt')
                response = self.session.get(url, timeout=(10, 25), allow_redirects=False)
                if response.status_code in (301, 302, 303, 307, 308):
                    url = checked_url(urljoin(url, response.headers.get('Location', '')), source_id)
                    continue
                if response.status_code != 200:
                    raise DetailError(f'HTTP {response.status_code}')
                if 'text/html' not in response.headers.get('Content-Type', ''):
                    raise DetailError('Unexpected content type')
                return parse_detail(response.content, source_id, url)
            raise DetailError('Too many redirects')
        except requests.RequestException as exc:
            raise DetailError('Page download failed') from exc
