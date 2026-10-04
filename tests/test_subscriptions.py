import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram_bot.search_bot import Store, SearchMenu
from telegram_bot import subscriptions as sub
from telegram_bot.client import TelegramError

BASE=datetime(2026,10,3,12,tzinfo=timezone.utc)
FILTERS=dict(cities=['Beograd'],categories=['office'],minimum=120000,include_unknown=True)


def job(index=1, **changes):
    value=dict(source='infostud',source_id=str(index),source_url='https://poslovi.infostud.com/posao/accountant/'+str(index),
               title='Accountant',company='Company',cities=['Beograd'],remote=False,search_category='office',
               pay=None,languages=[],deadline=None,closed=False,first_seen_at=BASE+timedelta(seconds=index),
               published_at=BASE+timedelta(seconds=index),four_fields={'salary':{'status':'UNKNOWN'}},
               detail_snapshot_id=index,four_fields_snapshot_id=index)
    value.update(changes);return value


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state.sqlite'
        self.store=Store(self.path);self.clock=BASE+timedelta(minutes=1)
        self.jobs=[];self.calls=[]
        self.store.save(7,dict(FILTERS,locale='ru'))
        sub.activate(self.store,7,FILTERS,BASE)
        self.worker=sub.Notifier(self.store,lambda:self.jobs,self.send,lambda:self.clock)

    def tearDown(self):
        self.store.conn.close();self.temp.cleanup()

    def send(self,method,**params):
        self.calls.append(params);return {'message_id':len(self.calls)}

    def next_tick(self):
        self.clock+=timedelta(seconds=31)
        return self.worker.tick()

    def test_new_only_matching_prepared_and_no_repeats_after_restart(self):
        self.jobs=[job(1),job(2,first_seen_at=BASE-timedelta(days=1)),job(3,cities=['Niš']),
                   job(4,detail_snapshot_id=None,four_fields=None),job(5,deadline='01.10.2026.')]
        self.assertEqual(self.worker.tick(),1)
        self.assertIn('Новая вакансия',self.calls[0]['text'])
        self.assertEqual(self.next_tick(),0)
        self.store.conn.close();self.store=Store(self.path)
        self.worker=sub.Notifier(self.store,lambda:self.jobs,self.send,lambda:self.clock)
        self.assertEqual(self.worker.tick(),0)
        self.jobs[3]=job(4)
        self.assertEqual(self.next_tick(),1)

    def test_pause_resume_skips_backlog_and_disabled_stays_quiet(self):
        sub.set_status(self.store,7,'paused',BASE)
        self.jobs=[job(1)]
        self.assertEqual(self.worker.tick(),0)
        sub.set_status(self.store,7,'active',self.clock)
        self.assertEqual(self.next_tick(),0)
        self.jobs.append(job(2,first_seen_at=self.clock+timedelta(seconds=1)))
        self.assertEqual(self.next_tick(),1)
        sub.set_status(self.store,7,'off',self.clock)
        self.jobs.append(job(3,first_seen_at=self.clock+timedelta(seconds=1)))
        self.assertEqual(self.next_tick(),0)

    def test_changed_filters_and_language_are_respected(self):
        self.jobs=[job(1)]
        changed=dict(FILTERS,cities=['Novi Sad'])
        sub.activate(self.store,7,changed,self.clock)
        self.store.save(7,dict(changed,locale='sr'))
        self.jobs.append(job(2,cities=['Novi Sad'],first_seen_at=self.clock+timedelta(seconds=1)))
        self.assertEqual(self.next_tick(),1)
        self.assertIn('Novi posao',self.calls[0]['text'])
        self.assertNotIn('Новая вакансия',self.calls[0]['text'])

    def test_uncertain_send_is_never_retried(self):
        self.jobs=[job(1)]
        def fail(*args,**kwargs):
            self.calls.append(kwargs);raise TelegramError('network',uncertain=True)
        self.worker.send=fail
        self.assertEqual(self.worker.tick(),1)
        self.assertEqual(self.next_tick(),0)
        self.assertEqual(self.store.conn.execute('SELECT state FROM subscription_deliveries').fetchone()[0],'uncertain')

    def test_crash_claim_is_not_replayed(self):
        self.store.conn.execute("INSERT INTO subscription_deliveries VALUES (7,'infostud','1','sending',?,0,NULL)",(BASE.isoformat(),))
        self.store.conn.commit()
        self.store.conn.close();self.store=Store(self.path)
        self.jobs=[job(1)]
        worker=sub.Notifier(self.store,lambda:self.jobs,self.send,lambda:self.clock)
        self.assertEqual(worker.tick(),0)

    def test_rate_limit_retry_after_and_no_other_sends_in_batch(self):
        self.jobs=[job(1),job(2)]
        def limited(*args,**kwargs):
            self.calls.append(kwargs);raise TelegramError('rate limit',error_code=429,retry_after=120)
        self.worker.send=limited
        self.assertEqual(self.worker.tick(),1)
        self.assertEqual(self.next_tick(),0)
        self.worker.send=self.send;self.clock+=timedelta(seconds=121)
        self.assertEqual(self.worker.tick(),2)

    def test_blocked_user_does_not_stop_other_subscribers(self):
        self.jobs=[job(1),job(2)]
        self.store.save(8,dict(FILTERS,locale='sr'));sub.activate(self.store,8,FILTERS,BASE)
        def sender(method,**kwargs):
            if kwargs['chat_id']==7: raise TelegramError('blocked',error_code=403)
            return self.send(method,**kwargs)
        self.worker.send=sender
        self.worker.tick()
        self.assertEqual(sub.get(self.store,7)['status'],'blocked')
        self.assertEqual(len(self.calls),2)
        self.assertEqual({x['chat_id'] for x in self.calls},{8})

    def test_round_robin_and_batch_limit(self):
        self.jobs=[job(i) for i in range(1,8)]
        self.store.save(8,dict(FILTERS,locale='ru'));sub.activate(self.store,8,FILTERS,BASE)
        self.assertEqual(self.worker.tick(limit=3),3)
        self.assertEqual([x['chat_id'] for x in self.calls],[7,8,7])
        self.next_tick()
        self.assertEqual(self.calls[3]['chat_id'],8)

    def test_search_changes_do_not_change_subscription(self):
        self.store.save(7,dict(FILTERS,cities=['Niš'],locale='sr'))
        self.assertEqual(sub.get(self.store,7)['filters']['cities'],['Beograd'])
        self.jobs=[job(1)];self.worker.tick()
        self.assertEqual(len(self.calls),1)
        self.assertIn('Novi posao',self.calls[0]['text'])

    def test_salary_remote_category_and_expiry_match_search_rules(self):
        pay=dict(min=100000,max=150000,currency='RSD',period='MONTH',basis='NET')
        self.jobs=[job(1,pay=pay),job(2,pay=dict(pay,max=110000)),job(3,remote=True),
                   job(4,search_category='it'),job(5,closed=True),job(6)]
        self.assertEqual(self.worker.tick(),2)
        self.assertEqual([row[0] for row in self.store.conn.execute("SELECT source_id FROM subscription_deliveries ORDER BY source_id")],['1','6'])

    def test_offline_backlog_is_sent_once_and_auth_failure_can_retry(self):
        self.jobs=[job(1)]
        self.clock+=timedelta(days=1)
        def unauthorized(*args,**kwargs):
            raise TelegramError('unauthorized',error_code=401)
        self.worker.send=unauthorized
        with self.assertRaises(TelegramError): self.worker.tick()
        self.worker.send=self.send;self.clock+=timedelta(seconds=61)
        self.assertEqual(self.worker.tick(),1)
        self.assertEqual(self.next_tick(),0)


class SubscriptionMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'state.sqlite')
        self.calls=[]
        self.menu=SearchMenu(self.store,lambda:[],lambda method,**kw:self.calls.append((method,kw)))
        self.store.save(7,dict(FILTERS,locale='sr',step='results',rev='test'))

    def tearDown(self):
        self.store.conn.close();self.temp.cleanup()

    def click(self,action):
        self.menu.handle({'callback_query':{'id':'cb','from':{'id':7},'message':{'chat':{'id':7,'type':'private'}},
            'data':'s:'+self.store.get(7)['rev']+':'+action}})

    def test_subscribe_pause_resume_disable_and_edit(self):
        self.click('subscribe')
        self.assertEqual(sub.get(self.store,7)['filters'],FILTERS)
        self.assertIn('Praćenje je uključeno',self.calls[-1][1]['text'])
        self.click('sub:pause');self.assertEqual(sub.get(self.store,7)['status'],'paused')
        self.click('sub:resume');self.assertEqual(sub.get(self.store,7)['status'],'active')
        self.click('sub:disable');self.assertEqual(sub.get(self.store,7)['status'],'off')
        self.click('sub:edit')
        self.assertEqual(self.store.get(7)['step'],'cities')
        self.assertEqual(self.store.get(7)['cities'],['Beograd'])
        self.assertEqual(sub.get(self.store,7)['status'],'off')

    def test_notification_button_opens_without_stale_nonce(self):
        self.menu.handle({'callback_query':{'id':'cb','from':{'id':7},'message':{'chat':{'id':7,'type':'private'}},
                                          'data':'subscription:open'}})
        self.assertIn('Praćenje još nije podešeno',self.calls[-1][1]['text'])


if __name__=='__main__': unittest.main()
