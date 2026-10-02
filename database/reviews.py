"""Audited decisions, invalidated when reviewed content changes."""
import hashlib
import json
import psycopg

SCHEMA='''CREATE TABLE IF NOT EXISTS serbia_jobs.jooble_reviews (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, source_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('READY','DUPLICATE','NEEDS_INFO')),
 reason TEXT NOT NULL, evidence TEXT NOT NULL, reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now())'''

def fingerprint(post):
    keys=('source_id','body','issues','duplicate_candidates','four_fields','content_sha256')
    return hashlib.sha256(json.dumps({k:post.get(k) for k in keys},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def apply_decision(post, review):
    if not review or review['fingerprint']!=fingerprint(post):
        return post
    post=dict(post,review_decision=review['decision'],review_reason=review['reason'])
    if review['decision']=='READY':
        if not post['issues'] and post['body']:
            post['review_status']='DRAFT'
    else:
        post['review_status']=review['decision']
    return post

def decide(dsn, source_id, decision, reason, evidence):
    from telegram_bot.jooble_preview import build_from_connection
    if decision not in ('READY','DUPLICATE','NEEDS_INFO') or not reason.strip() or not evidence.strip():
        raise ValueError('Decision, reason and evidence required')
    with psycopg.connect(dsn) as conn:
        conn.execute(SCHEMA)
        post=next((p for p in build_from_connection(conn) if p['source_id']==source_id),None)
        if post is None or (decision=='READY' and (post['issues'] or not post['body'])):
            raise ValueError('Unknown vacancy or unresolved data/translation issues')
        sig=fingerprint(post)
        last=conn.execute('SELECT fingerprint,decision,reason,evidence FROM serbia_jobs.jooble_reviews WHERE source_id=%s ORDER BY id DESC LIMIT 1',(source_id,)).fetchone()
        if last!=(sig,decision,reason,evidence):
            conn.execute('INSERT INTO serbia_jobs.jooble_reviews (source_id,fingerprint,decision,reason,evidence) VALUES (%s,%s,%s,%s,%s)',(source_id,sig,decision,reason,evidence))
