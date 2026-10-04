"""Opt-in subscriptions and durable, at-most-once notification attempts."""
import json
import logging
from datetime import datetime, timezone

from telegram_bot import search_data as data
from telegram_bot.search_i18n import card, locale, tr
from telegram_bot.client import TelegramError

LOG=logging.getLogger(__name__)
FILTER_KEYS=('cities','categories','minimum','include_unknown')


def utcnow():
    return datetime.now(timezone.utc)


def prepare(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS subscriptions (
          user_id INTEGER PRIMARY KEY, filters TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('active','paused','off','blocked')),
          since TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS subscription_deliveries (
          user_id INTEGER NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('sending','sent','uncertain','failed','retry')),
          attempted_at TEXT NOT NULL, retry_at REAL NOT NULL DEFAULT 0, message_id INTEGER,
          PRIMARY KEY(user_id,source,source_id));
    ''')
    # The process may have died after Telegram accepted a message but before saving its ID.
    conn.execute("UPDATE subscription_deliveries SET state='uncertain' WHERE state='sending'")
    conn.commit()


def get(store, uid):
    row=store.conn.execute('SELECT filters,status,since FROM subscriptions WHERE user_id=?',(uid,)).fetchone()
    return dict(filters=json.loads(row[0]),status=row[1],since=row[2]) if row else None


def activate(store, uid, filters, now=None):
    now=now or utcnow()
    selected={key:filters[key] for key in FILTER_KEYS}
    stamp=now.isoformat()
    store.conn.execute('''INSERT INTO subscriptions VALUES (?,?,'active',?,?)
        ON CONFLICT(user_id) DO UPDATE SET filters=excluded.filters,status='active',
        since=excluded.since,updated_at=excluded.updated_at''',
        (uid,json.dumps(selected,ensure_ascii=False),stamp,stamp))
    store.conn.commit()


def set_status(store, uid, status, now=None):
    if status not in ('active','paused','off','blocked'):
        raise ValueError('Invalid subscription status')
    stamp=(now or utcnow()).isoformat()
    if status=='active':
        store.conn.execute("UPDATE subscriptions SET status=?,since=?,updated_at=? WHERE user_id=?",(status,stamp,stamp,uid))
    else:
        store.conn.execute('UPDATE subscriptions SET status=?,updated_at=? WHERE user_id=?',(status,stamp,uid))
    store.conn.commit()


def ready(job):
    # Wait for Infostud detail extraction, including legitimate UNKNOWN values.
    if job['source']=='infostud':
        return bool(job.get('four_fields') and job.get('detail_snapshot_id') is not None
                    and job.get('four_fields_snapshot_id')==job.get('detail_snapshot_id'))
    return True


class Notifier:
    def __init__(self, store, loader, send, now=utcnow):
        self.store,self.loader,self.send,self.now=store,loader,send,now
        self.last_user=None
        self.next_poll=0.0

    def tick(self, limit=5):
        now=self.now();stamp=now.timestamp()
        if stamp<self.next_poll: return 0
        self.next_poll=stamp+30
        subs=self.store.conn.execute("SELECT user_id,filters,since FROM subscriptions WHERE status='active' ORDER BY user_id").fetchall()
        if not subs: return 0
        jobs=self.loader()
        queues=[]
        for uid,filters,since in subs:
            cutoff=data.instant(since)
            eligible=[j for j in data.select(jobs,json.loads(filters),now)
                      if ready(j) and data.instant(j.get('first_seen_at')) is not None
                      and cutoff<data.instant(j['first_seen_at'])<=now]
            states={(source,source_id):(state,retry_at) for source,source_id,state,retry_at in
                    self.store.conn.execute('SELECT source,source_id,state,retry_at FROM subscription_deliveries WHERE user_id=?',(uid,))}
            eligible=[j for j in reversed(eligible) if (j['source'],j['source_id']) not in states
                      or (states[(j['source'],j['source_id'])][0]=='retry'
                          and states[(j['source'],j['source_id'])][1]<=stamp)]
            if eligible: queues.append((uid,eligible))
        if self.last_user is not None:
            queues.sort(key=lambda item:(item[0]<=self.last_user,item[0]))
        attempted=0
        while queues and attempted<limit:
            remaining=[]
            for uid,candidates in queues:
                if attempted>=limit: break
                job=candidates.pop(0)
                # Render before recording an attempt: formatting errors have no delivery risk.
                lang=locale(self.store.get(uid))
                try:
                    body=tr(lang,'new_job')+'\n\n'+card(job,lang)
                except (ValueError,KeyError,TypeError):
                    LOG.warning('Не удалось подготовить уведомление о вакансии.')
                    continue
                key=(uid,job['source'],job['source_id'])
                cursor=self.store.conn.execute('''INSERT INTO subscription_deliveries
                    (user_id,source,source_id,state,attempted_at,retry_at)
                    VALUES (?,?,?,'sending',?,0) ON CONFLICT(user_id,source,source_id)
                    DO UPDATE SET state='sending',attempted_at=excluded.attempted_at,retry_at=0
                    WHERE subscription_deliveries.state='retry' AND subscription_deliveries.retry_at<=?''',
                    (*key,now.isoformat(),stamp))
                self.store.conn.commit()
                if cursor.rowcount!=1: continue
                attempted+=1;self.last_user=uid
                try:
                    result=self.send('sendMessage',chat_id=uid,text=body,parse_mode='HTML',
                        link_preview_options={'is_disabled':True},
                        reply_markup={'inline_keyboard':[[{'text':tr(lang,'my_subscription'),
                                                          'callback_data':'subscription:open'}]]})
                except TelegramError as exc:
                    state='uncertain' if exc.uncertain or (exc.error_code or 0)>=500 else 'failed'
                    retry_at=0
                    if exc.error_code in (401,429):
                        state='retry';retry_at=stamp+max(exc.retry_after or 60,1)
                    self.store.conn.execute('UPDATE subscription_deliveries SET state=?,retry_at=? WHERE user_id=? AND source=? AND source_id=?',
                                            (state,retry_at,*key));self.store.conn.commit()
                    if exc.error_code==403:
                        set_status(self.store,uid,'blocked',now)
                        candidates=[]
                    if exc.error_code in (401,429):
                        # A rate limit is global enough to stop this batch, not skip other users.
                        self.next_poll=max(self.next_poll,retry_at)
                        if exc.error_code==401: raise
                        return attempted
                else:
                    self.store.conn.execute("UPDATE subscription_deliveries SET state='sent',message_id=? WHERE user_id=? AND source=? AND source_id=?",
                                            ((result or {}).get('message_id'),*key))
                    self.store.conn.commit()
                if candidates: remaining.append((uid,candidates))
            queues=remaining
        return attempted
