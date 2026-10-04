"""Review saved Jooble results without requests, publication or queue changes."""
from decimal import Decimal
from html import escape, unescape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

from normalization import extract_four, fold, result, salary
from telegram_bot.localization import TranslationRequired
from telegram_bot.preview import render_post, TOPICS


def text(value):
    value = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', value or '', flags=re.I|re.S)
    value = re.sub(r'<(?:br\s*/?|/?p|/?div)\b[^>]*>', '\n', value, flags=re.I)
    return unescape(re.sub(r'<[^>]*>', '', value))


def signature(value):
    return ' '.join(re.findall(r'\w+', fold(text(value or ''))))


def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip('/'), '', ''))


def duplicate_candidates(job, all_jobs):
    """Same URL, or matching normalized title followed by employer and city."""
    found=[]
    for other in all_jobs:
        if (job['source'],job['source_id']) == (other['source'],other['source_id']):
            continue
        same_url = canonical(job['source_url']) == canonical(other['source_url'])
        employer = signature(job.get('company'))
        city = {signature(x) for x in job.get('locations') or []}
        overlap = city & {signature(x) for x in other.get('locations') or []}
        title=signature(job.get('title'))
        same_title=bool(title) and title==signature(other.get('title'))
        if same_url or (same_title and employer and employer == signature(other.get('company')) and overlap):
            found.append({'source':other['source'], 'id':other['source_id'],
                          'title':other['title'], 'url':other['source_url'],
                          'content_sha256':other.get('content_sha256'),
                          'reason':'same_url' if same_url else 'same_title_employer_and_location'})
    return found


def prepare(job, original, all_jobs, mappings=None, location_decisions=None):
    snippet=text(original.get('snippet'))
    fields=extract_four(snippet, {})
    # Jooble salary field is authoritative; do not infer any pay terms from prose.
    fields['salary']=salary('', {'salary':original.get('salary') or ''})
    for entry in fields.values():
        for proof in entry['evidence']:
            proof['source_path'] = ('jooble.snippet' if proof['source_path']=='description_original'
                                    else 'jooble.salary')
    from jooble_classification import category_for, location_for, CATEGORIES, title_key
    category=category_for(job['title'],mappings)
    decision=(location_decisions or {}).get(job['source_id'])
    if decision and decision['content_sha256'] != job.get('content_sha256'):
        decision=None
    raw_location=original.get('location')
    if raw_location is None:
        raw_location=', '.join(job.get('locations') or [])
    mode=fields['work_mode']
    location=location_for(raw_location,snippet,decision,
        explicit_remote=mode['status']=='KNOWN' and mode['value']=='REMOTE')
    issues=[]
    if category['status']!='KNOWN':
        issues.append('Категория не определена однозначно: назначьте её по названию')
    if location['status']!='KNOWN':
        issues.append('Место работы требует проверки: '+(', '.join(location['unresolved']) or 'не указано'))

    pay=fields['salary']
    raw_salary=original.get('salary') or ''
    if pay['status']=='KNOWN':
        value=pay['value']
        if re.search(r'\bdnevnica\b',fold(raw_salary)):
            value['period']='DAY'
        # A review heuristic, not a corrected amount or a minimum-wage claim.
        amounts=[Decimal(value[k]) for k in ('min','max') if value.get(k) is not None]
        if value.get('currency')=='RSD' and amounts and min(amounts)<100 and not value.get('period'):
            fields['salary']=result(None,pay['evidence'],'REVIEW')
            issues.append('Низкая сумма RSD без периода: '+raw_salary)
    if raw_salary and fields['salary']['status']=='UNKNOWN':
        fields['salary']=result(None,[{'source_path':'jooble.salary','quote':raw_salary}],'REVIEW')
    if fields['salary']['status']=='REVIEW' and not issues:
        issues.append('Зарплата требует проверки по оригиналу')
    duplicates=duplicate_candidates(job,all_jobs)
    # Tie derived data to the actual source snapshot, never to an Infostud detail.
    prepared=dict(job,four_fields=fields,classification_topics=location['topics'],
                  reviewed_title_ru=((mappings or {}).get(title_key(job['title'])) or {}).get('title_ru'),
                  category_tag=CATEGORIES[category['key']][1] if category['key'] else '#другие_сферы',
                  locations=location['cities'] + (['Rad na daljinu'] if location['remote'] else []),
                  detail_snapshot_id=job['snapshot_id'],
                  four_fields_snapshot_id=job['snapshot_id'])
    try:
        body,topics=render_post(prepared)
    except TranslationRequired as exc:
        body,topics='',[]
        issues.append(str(exc))
    return {'source_id':job['source_id'],'title':job['title'],'body':body,
            'topics':[TOPICS[k] for k in topics], 'topic_keys':topics, 'four_fields':fields,
            'category':category,'location':location,
            'snapshot_id':job['snapshot_id'],'issues':issues,'duplicate_candidates':duplicates,
            'content_sha256':job.get('content_sha256'),
            'review_status':'REVIEW' if issues or duplicates else 'DRAFT',
            'salary_original':raw_salary, 'source_url':job['source_url']}


def build(dsn):
    with psycopg.connect(dsn,row_factory=dict_row,connect_timeout=10) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        return build_from_connection(conn)


def build_from_connection(conn):
    from telegram_bot.automatic_translation import translation_context,resolver
    if resolver.get() is None:
        with translation_context(conn):
            return _build_from_connection(conn)
    return _build_from_connection(conn)


def _build_from_connection(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        jobs=cur.execute('''SELECT source,source_id,source_url,title,company,locations,
            snapshot_id,summary_original,content_sha256 FROM serbia_jobs.vacancies ORDER BY source,source_id''').fetchall()
        snapshots=cur.execute('''SELECT DISTINCT s.id,s.raw_content
            FROM serbia_jobs.source_snapshots s JOIN serbia_jobs.vacancies v ON v.snapshot_id=s.id
            WHERE v.source='jooble' ''').fetchall()
    originals={row['id']:{str(j['id']):j for j in json.loads(bytes(row['raw_content']))['jobs']}
               for row in snapshots}
    from database.jooble_classification import load_decisions
    mappings,location_decisions=load_decisions(conn)
    posts=[prepare(job,originals[job['snapshot_id']][job['source_id']],jobs,mappings,location_decisions)
            for job in jobs if job['source']=='jooble']
    with conn.cursor(row_factory=dict_row) as cur:
        exists=cur.execute("SELECT to_regclass('serbia_jobs.jooble_reviews') AS name").fetchone()['name']
        reviews=cur.execute('SELECT DISTINCT ON (source_id) * FROM serbia_jobs.jooble_reviews ORDER BY source_id,id DESC').fetchall() if exists else []
    from database.reviews import apply_decision
    by_id={r['source_id']:r for r in reviews}
    with conn.cursor(row_factory=dict_row) as cur:
        exists=cur.execute("SELECT to_regclass('serbia_jobs.jooble_exclusions') AS name").fetchone()['name']
        excluded={r['source_id']:r['reason'] for r in cur.execute('SELECT source_id,reason FROM serbia_jobs.jooble_exclusions').fetchall()} if exists else {}
    return [dict(p,review_status='EXCLUDED',review_reason=excluded[p['source_id']])
            if p['source_id'] in excluded else apply_decision(p,by_id.get(p['source_id'])) for p in posts]


def write_report(posts, directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'jooble-review.json').write_text(json.dumps(posts,ensure_ascii=False,indent=2),encoding='utf-8')
    cards=[]
    for post in posts:
        if post['review_status']=='EXCLUDED':
            continue
        notes=[f"ID: {post['source_id']} · {post['title']}",
               'Категория: '+str(post['category']['key'] or 'не определена')+' · '+post['category']['origin'],
               'Место в оригинале: '+post['location']['original'],
               'Города: '+(', '.join(post['location']['cities']) or 'не определены')]
        notes+=([post['review_reason']] if post.get('review_reason') else []) + post['issues'] + [f"Возможный повтор: {x['source']} · {x['title']} · ID {x['id']}"
                                 for x in post['duplicate_candidates']]
        cards.append('<article><aside>'+escape(post['review_status']+' · '+', '.join(post['topics']))+
                     '</aside><div class="post">'+post['body'].replace('\n','<br>')+'</div><footer>'+
                     '<br>'.join(escape(x) for x in notes)+'</footer></article>')
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jooble — проверка постов</title><style>body{font:16px/1.5 system-ui;background:#e7efea;color:#152a24;margin:0;padding:24px}main{max-width:850px;margin:auto}article{background:white;border-radius:16px;padding:22px;margin:20px 0}aside{color:#52665c;font-size:14px;margin-bottom:16px}footer{color:#85450d;background:#fff7e9;padding:12px;margin-top:18px}footer:empty{display:none}a{color:#087daf}h1{font-size:28px}</style><main><h1>Jooble — двуязычные черновики</h1><p>Ничего не отправлено в Telegram. Возможные повторы не удалены: совпадение работодателя и города не доказывает, что это одна вакансия. Сведения извлечены из кратких описаний.</p>'''
    (directory/'jooble-review.html').write_text(page+''.join(cards)+'</main></html>',encoding='utf-8')
