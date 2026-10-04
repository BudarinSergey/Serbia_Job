"""Private-chat search menu. Vacancy storage is always read-only."""
import json
import logging
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from telegram_bot.client import api, TelegramError
from telegram_bot import search_data as data
from telegram_bot.search_groups import GROUPS, city_options, grouped_cities, migrate_categories
from telegram_bot.search_i18n import tr, locale, group_label, city_label, card
from telegram_bot import subscriptions

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
SALARIES = [None, 80000, 100000, 120000, 150000, 200000]


class PacedClient:
    """Space private-chat cards; retry only explicit rate-limit rejections."""
    def __init__(self):
        self.last_send = 0.0

    def __call__(self, method, **params):
        if method=='sendMessage':
            time.sleep(max(0.0, 1.1-(time.monotonic()-self.last_send)))
        for attempt in range(3):
            try:
                result=api(method, **params)
                if method=='sendMessage': self.last_send=time.monotonic()
                return result
            except TelegramError as exc:
                if exc.error_code!=429 or attempt==2 or not exc.retry_after or exc.retry_after>60:
                    raise
                time.sleep(exc.retry_after)


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute('CREATE TABLE IF NOT EXISTS sessions (user_id INTEGER PRIMARY KEY, body TEXT NOT NULL, touched REAL NOT NULL)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), offset INTEGER NOT NULL)')
        self.conn.execute("CREATE TABLE IF NOT EXISTS preferences (user_id INTEGER PRIMARY KEY, locale TEXT NOT NULL CHECK(locale IN ('ru','sr')))")
        self.conn.execute('DELETE FROM sessions WHERE touched < ?', (time.time()-30*86400,))
        self.conn.commit()
        subscriptions.prepare(self.conn)

    def get(self, user_id):
        row = self.conn.execute('SELECT body FROM sessions WHERE user_id=?', (user_id,)).fetchone()
        if row:
            return json.loads(row[0])
        preference=self.conn.execute('SELECT locale FROM preferences WHERE user_id=?',(user_id,)).fetchone()
        return dict(cities=[],categories=[],minimum=None,include_unknown=True,locale=preference[0]) if preference else None

    def save(self, user_id, session):
        self.conn.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?)',
                          (user_id, json.dumps(session, ensure_ascii=False), time.time()))
        if session.get('locale') in ('ru','sr'):
            self.conn.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',(user_id,session['locale']))
        self.conn.commit()

    def offset(self):
        row = self.conn.execute('SELECT offset FROM checkpoint WHERE id=1').fetchone()
        return row[0] if row else 0

    def advance(self, offset):
        self.conn.execute('INSERT OR REPLACE INTO checkpoint VALUES (1,?)', (offset,))
        self.conn.commit()



class SearchMenu:
    def __init__(self, store, loader, send=api):
        self.store, self.loader, self.api = store, loader, send

    def show(self, uid, session, text, buttons):
        session['rev'] = secrets.token_hex(4)
        markup = {'inline_keyboard': [[{'text':label, 'callback_data':'s:'+session['rev']+':'+action}
                                      for label,action in row] for row in buttons]}
        self.api('sendMessage', chat_id=uid, text=text, reply_markup=markup)
        self.store.save(uid, session)

    def language(self, uid, session=None):
        session=session or self.store.get(uid) or {'cities':[], 'categories':[], 'minimum':None, 'include_unknown':True}
        session['step']='language'
        self.show(uid,session,'Выберите язык / Izaberite jezik',
                  [[('🇷🇺 Русский','lang:ru'),('🇷🇸 Srpski','lang:sr')]])

    def home(self, uid):
        session=self.store.get(uid) or {'cities':[], 'categories':[], 'minimum':None, 'include_unknown':True}
        if session.get('locale') not in ('ru','sr'):
            self.language(uid,session);return
        session['step']='home'
        lang=locale(session)
        self.show(uid,session,tr(lang,'home'),
                  [[(tr(lang,'find'),'start')],[(tr(lang,'my_subscription'),'sub:open')],[(tr(lang,'language'),'language')]])

    def subscription(self, uid, s=None, saved=False):
        s=s or self.store.get(uid)
        if not s or s.get('locale') not in ('ru','sr'):
            self.language(uid,s);return
        lang=locale(s);sub=subscriptions.get(self.store,uid)
        s['step']='subscription'
        if not sub:
            self.show(uid,s,tr(lang,'sub_none'),[[(tr(lang,'find'),'start')],[(tr(lang,'menu'),'home')]])
            return
        filters=sub['filters']
        cities=', '.join(city_label(c,lang) for c in filters['cities']) or tr(lang,'all_cities')
        categories=', '.join(group_label(c,lang) for c in filters['categories']) or tr(lang,'all_categories')
        pay=tr(lang,'any_salary') if filters['minimum'] is None else tr(lang,'salary_min',amount=filters['minimum']//1000)
        text='\n'.join(([tr(lang,'sub_saved')] if saved else [])+[
            tr(lang,'sub_'+sub['status']),tr(lang,'cities')+': '+cities,
            tr(lang,'categories')+': '+categories,tr(lang,'salary')+': '+pay,
            tr(lang,'sub_unknown_yes' if filters['include_unknown'] else 'sub_unknown_no'),
            '',tr(lang,'sub_note')])
        rows=[[(tr(lang,'sub_edit'),'sub:edit')]]
        rows.append([(tr(lang,'sub_pause'),'sub:pause')] if sub['status']=='active' else [(tr(lang,'sub_resume'),'sub:resume')])
        if sub['status']!='off': rows.append([(tr(lang,'sub_disable'),'sub:disable')])
        rows.append([(tr(lang,'menu'),'home')])
        self.show(uid,s,text,rows)

    def begin_search(self, uid, s):
        jobs=data.select(self.loader(),{})
        # Include saved places even if their vacancies have temporarily expired.
        s['cities_options']=city_options([c for j in jobs for c in j['cities']]+[
            c for c in s.get('cities',[]) if c!=data.REMOTE_KEY],data.REMOTE_KEY)
        s['categories_options']=[[key,label] for key,label in GROUPS.items()]
        s['cities']=grouped_cities(s.get('cities',[]))
        s['categories']=migrate_categories(s.get('categories',[]))
        self.choices(uid,s,'cities')

    def choices(self, uid, s, kind, page=0):
        s['step']=kind
        lang=locale(s)
        choices=[[key,city_label(key,lang) if kind=='cities' else group_label(key,lang)] for key,_ in s[kind+'_options']]
        page=max(0,min(page,max(0,(len(choices)-1)//8)))
        s['choice_page']=page
        selected=s[kind]
        title=tr(lang,kind)
        all_label=tr(lang,'all_'+kind)
        rows=[[(('✅ ' if not selected else '')+all_label,'all')]]
        for index in range(page*8,min(len(choices),(page+1)*8)):
            key,label=choices[index]
            rows.append([(('✅ ' if key in selected else '')+label,'pick:'+str(index))])
        nav=[]
        if page: nav.append(('←','page:'+str(page-1)))
        if (page+1)*8<len(choices): nav.append(('→','page:'+str(page+1)))
        if nav: rows.append(nav)
        rows.append([(tr(lang,'back'),'back'),(tr(lang,'next'),'next')])
        labels=dict(choices)
        summary=', '.join(labels.get(k,k) for k in selected) or all_label
        hint='\n'+tr(lang,kind+'_hint')
        self.show(uid,s,title+hint+'\n'+tr(lang,'selected')+summary[:1500],rows)

    def salary(self, uid, s):
        lang=locale(s)
        s['step']='salary'
        rows=[]
        for index, amount in enumerate(SALARIES):
            label=tr(lang,'any_salary') if amount is None else tr(lang,'salary_min',amount=amount//1000)
            rows.append([(('✅ ' if s['minimum']==amount else '')+label,'salary:'+str(index))])
        rows.append([(('✅ ' if s['include_unknown'] else '☐ ')+tr(lang,'unknown_salary'),'unknown')])
        rows.append([(tr(lang,'back'),'back'),(tr(lang,'show'),'results')])
        self.show(uid,s,tr(lang,'salary_hint'),rows)

    def results(self, uid, s, fresh=False):
        lang=locale(s)
        jobs=self.loader()
        now=datetime.now(timezone.utc)
        matched=data.select(jobs,s,now)
        indexed={(j['source'],j['source_id']):j for j in matched}
        if fresh:
            s['result_ids']=[[j['source'],j['source_id']] for j in matched]
            s['position']=0
        ids=s.get('result_ids',[])
        page=[]
        while s['position']<len(ids) and len(page)<5:
            key=tuple(ids[s['position']]);s['position']+=1
            if key in indexed: page.append(indexed[key])
        # Five separate cards keep the full conditions and stay below Telegram's limit.
        s['rev']=secrets.token_hex(4)
        self.store.save(uid,s)
        for job in page:
            self.api('sendMessage',chat_id=uid,text=card(job,lang),parse_mode='HTML',
                     link_preview_options={'is_disabled':True})
        body=tr(lang,'shown',count=len(page)) if page else tr(lang,'empty')
        s['step']='results';s['rev']=secrets.token_hex(4)
        rows=[]
        if any(tuple(key) in indexed for key in ids[s['position']:]):
            rows.append([{'text':tr(lang,'more'),'callback_data':'s:'+s['rev']+':more'}])
        rows.append([{'text':tr(lang,'filters'),'callback_data':'s:'+s['rev']+':start'}])
        label='update_subscription' if subscriptions.get(self.store,uid) else 'subscribe'
        rows.append([{'text':tr(lang,label),'callback_data':'s:'+s['rev']+':subscribe'}])
        rows.append([{'text':tr(lang,'language'),'callback_data':'s:'+s['rev']+':language'}])
        self.api('sendMessage',chat_id=uid,text=body,
                 link_preview_options={'is_disabled':True},reply_markup={'inline_keyboard':rows})
        self.store.save(uid,s)

    def handle(self, update):
        callback=update.get('callback_query')
        message=(callback or {}).get('message') or update.get('message') or {}
        chat=message.get('chat') or {}
        if chat.get('type')!='private': return
        uid=chat['id']
        if callback:
            if callback.get('from',{}).get('id')!=uid: return
            s=self.store.get(uid)
            if callback.get('data')=='subscription:open':
                self.api('answerCallbackQuery',callback_query_id=callback['id'])
                self.subscription(uid,s);return
            parts=callback.get('data','').split(':',2)
            valid=bool(s and len(parts)==3 and parts[0]=='s' and parts[1]==s.get('rev'))
            self.api('answerCallbackQuery',callback_query_id=callback['id'],
                     text='' if valid else tr(locale(s),'stale'))
            if not valid: return
            action=parts[2]
            if action=='language':
                self.language(uid,s);return
            if action.startswith('lang:') and s.get('step')=='language':
                chosen=action.split(':',1)[1]
                if chosen not in ('ru','sr'): return
                s['locale']=chosen
                self.store.save(uid,s)
                self.home(uid);return
            if s.get('locale') not in ('ru','sr'):
                self.language(uid,s);return
            if action=='home': self.home(uid);return
            if action=='sub:open': self.subscription(uid,s);return
            if action=='subscribe' and s.get('step')=='results':
                subscriptions.activate(self.store,uid,s)
                self.subscription(uid,s,saved=True);return
            if action.startswith('sub:') and s.get('step')=='subscription':
                sub=subscriptions.get(self.store,uid)
                if not sub: self.subscription(uid,s);return
                if action=='sub:edit':
                    s.update(sub['filters'])
                    self.begin_search(uid,s);return
                if action=='sub:pause' and sub['status']=='active': subscriptions.set_status(self.store,uid,'paused')
                elif action=='sub:resume' and sub['status']!='active': subscriptions.set_status(self.store,uid,'active')
                elif action=='sub:disable': subscriptions.set_status(self.store,uid,'off')
                self.subscription(uid,s);return
            if action=='start':
                self.begin_search(uid,s);return
            step=s.get('step')
            if step in ('cities','categories'):
                page=s.get('choice_page',0)
                if action=='all': s[step]=[]
                elif action.startswith('pick:'):
                    index=int(action.split(':')[1])
                    if not 0<=index<len(s[step+'_options']): return
                    key=s[step+'_options'][index][0]
                    if key in s[step]: s[step].remove(key)
                    else: s[step].append(key)
                elif action.startswith('page:'): page=int(action.split(':')[1])
                elif action=='next':
                    if step=='cities': self.choices(uid,s,'categories')
                    else: self.salary(uid,s)
                    return
                elif action=='back':
                    if step=='cities': self.home(uid)
                    else: self.choices(uid,s,'cities')
                    return
                else: return
                self.choices(uid,s,step,page)
            elif step=='salary':
                if action=='back': self.choices(uid,s,'categories');return
                if action=='results': self.results(uid,s,True);return
                if action=='unknown': s['include_unknown']=not s['include_unknown']
                elif action.startswith('salary:'):
                    index=int(action.split(':')[1])
                    if not 0<=index<len(SALARIES): return
                    s['minimum']=SALARIES[index]
                else: return
                self.salary(uid,s)
            elif step=='results' and action=='more': self.results(uid,s)
        elif message.get('text','').split('@')[0].split(' ')[0]=='/language':
            self.language(uid)
        elif message.get('text','').split('@')[0].split(' ')[0]=='/subscription':
            self.subscription(uid)
        elif message.get('text','').split('@')[0].split(' ')[0] in ('/start','/search','/help'):
            self.home(uid)


def run():
    """One poller per database; safe to run alongside the vacancy publisher."""
    import psycopg
    from database.postgres import connection_dsn
    dsn=connection_dsn()
    with psycopg.connect(dsn,autocommit=True,options='-c default_transaction_read_only=on') as lock:
        if not lock.execute('SELECT pg_try_advisory_lock(735192, 1001)').fetchone()[0]:
            print('Поиск уже запущен другим процессом.',flush=True);return
        if api('getWebhookInfo').get('url'):
            print('Поиск не запущен: у бота настроен webhook. Его настройки не менялись.',flush=True);return
        store=Store(ROOT/'data'/'search-menu.sqlite3')
        menu=SearchMenu(store,lambda:data.load(dsn),PacedClient())
        notifier=subscriptions.Notifier(store,lambda:data.load(dsn),menu.api)
        print('Меню поиска запущено. Откройте личный чат с ботом и отправьте /start.',flush=True)
        try:
            while True:
                try:
                    # Do not continue polling if the connection holding the singleton lock died.
                    lock.execute('SELECT 1')
                    updates=api('getUpdates',offset=store.offset(),timeout=20,allowed_updates=['message','callback_query'])
                    for update in updates:
                        # Claim before delivery: an uncertain send must not be replayed after restart.
                        store.advance(update['update_id']+1)
                        try:
                            menu.handle(update)
                        except (TelegramError,psycopg.Error,ValueError,KeyError,TypeError):
                            LOG.warning('Не удалось обработать запрос поиска; повторите /start.')
                            msg=(update.get('callback_query') or {}).get('message') or update.get('message') or {}
                            chat=msg.get('chat') or {}
                            if chat.get('type')=='private':
                                try:
                                    api('sendMessage',chat_id=chat['id'],text=tr(locale(store.get(chat['id'])),'error'))
                                except TelegramError:
                                    pass
                    try:
                        notifier.tick()
                    except (psycopg.Error,ValueError,KeyError,TypeError):
                        LOG.warning('Проверка подписок временно недоступна; повторим позже.')
                except TelegramError as exc:
                    if exc.error_code in (401,409):
                        print('Поиск остановлен: проверьте токен и отсутствие другого обработчика бота.',flush=True);return
                    time.sleep(min(max(exc.retry_after or 5,1),60))
        finally:
            store.conn.close()


def serve():
    import psycopg
    while True:
        try:
            run()
            return
        except (psycopg.Error, TelegramError, sqlite3.Error, OSError, ValueError):
            LOG.warning('Поиск временно недоступен. Повтор подключения через 30 секунд.')
            time.sleep(30)


if __name__=='__main__':
    serve()
