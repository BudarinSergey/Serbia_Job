from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_ADMIN_DSN'),'No disposable PostgreSQL server configured')
class PostgresPublicationTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        self.pg=psycopg
        self.name='serbia_jobs_test_'+uuid.uuid4().hex
        self.admin=os.environ['TEST_POSTGRES_ADMIN_DSN']
        with psycopg.connect(self.admin,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
        self.dsn=make_conninfo(self.admin,dbname=self.name)
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'legacy.sqlite3'
        self.config={'chat_id':11,'bot_id':22,'topics':{'belgrade':{'message_thread_id':3},'novi_sad':{'message_thread_id':4},'other_cities':{'message_thread_id':5},'remote':{'message_thread_id':6}}}
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE vacancies (source,source_id,title,summary,url,published_at,first_seen_at)')
            db.execute('CREATE TABLE telegram_outbox (chat_id,source,source_id,thread_id,body,status,message_id)')
            for ident in range(1,6):
                db.execute('INSERT INTO vacancies VALUES (?,?,?,?,?,?,?)',('infostud',str(ident),'Kasir - prodavac','Company - Beograd',f'https://poslovi.infostud.com/posao/a/b/{ident}',None,'2026-09-30T12:00:00+00:00'))
            for ident,state in enumerate(('sent','pending','sending','uncertain'),1):
                db.execute('INSERT INTO telegram_outbox VALUES (?,?,?,?,?,?,?)',(11,'infostud',str(ident),3,'old body '+str(ident),state,101 if ident==1 else None))
            db.commit()

    def tearDown(self):
        from psycopg import sql
        with self.pg.connect(self.admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.name)))
        self.temp.cleanup()

    def migrate(self):
        from database.publication_migration import migrate
        return migrate(self.dsn,self.path)

    def normalized(self,ids=('1','2','3','4','5')):
        from database.details import save_detail
        from database.normalization import normalize_saved
        from sources.infostud_details import parse_detail
        from tests.test_details import page
        for ident in ids:
            detail=parse_detail(page(id=int(ident)),ident,f'https://poslovi.infostud.com/posao/a/b/{ident}')
            save_detail(detail,self.dsn)
        normalize_saved(self.dsn)

    def states(self):
        with self.pg.connect(self.dsn) as conn:
            return conn.execute('SELECT source_id,status,message_id FROM serbia_jobs.telegram_outbox ORDER BY source_id').fetchall()

    def test_history_fence_backup_and_idempotence(self):
        result=self.migrate()
        self.assertEqual(result['queue_rows'],4)
        self.assertTrue(Path(result['backup']).is_file())
        self.assertEqual(self.states(),[('1','sent',101),('2','pending',None),('3','sending',None),('4','uncertain',None)])
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE telegram_outbox SET status='sending' WHERE source_id='2'")
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.telegram_outbox SET status='sent',message_id=999 WHERE source_id='2'")
        self.assertTrue(self.migrate()['already_migrated'])
        self.assertEqual(self.states()[1],('2','sent',999))

    @patch('telegram_bot.postgres_publisher.api',side_effect=AssertionError('Unexpected real API'))
    def test_prepare_preserves_destinations_and_blocks_new_routes_for_known_jobs(self,api):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate(); self.normalized()
        prepare_queue(self.dsn,['1','2','3','4','5'],self.config,self.path)
        prepare_queue(self.dsn,['1','2','3','4','5'],self.config,self.path)
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.telegram_outbox').fetchone()[0],5)
            pending=conn.execute("SELECT thread_id,body,legacy_body FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone()
            self.assertEqual(pending[0],3)  # New structured location is Novi Sad, legacy topic stays 3.
            self.assertIn('Языки:',pending[1]); self.assertEqual(pending[2],'old body 2')
            self.assertEqual(conn.execute("SELECT body FROM serbia_jobs.telegram_outbox WHERE source_id='1'").fetchone()[0],'old body 1')
        api.assert_not_called()

    @patch('telegram_bot.postgres_publisher.time.sleep')
    @patch('telegram_bot.postgres_publisher.api')
    def test_send_and_uncertain_are_not_repeated(self,api,sleep):
        from telegram_bot.postgres_publisher import publish
        from telegram_bot.client import TelegramError
        self.migrate(); self.normalized()
        api.side_effect=[{'id':22},TelegramError('timeout',uncertain=True)]
        with self.assertRaises(TelegramError): publish(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(self.states()[1],('2','uncertain',None))
        api.reset_mock(); api.side_effect=[{'id':22},{'message_id':777}]
        self.assertEqual(publish(self.dsn,['1','2','3','4','5'],self.config,self.path),1)
        self.assertEqual(publish(self.dsn,['1','2','3','4','5'],self.config,self.path),0)
        self.assertEqual(api.call_count,2)
        self.assertEqual(self.states()[-1],('5','sent',777))

    @patch('telegram_bot.postgres_publisher.api')
    def test_incomplete_migration_refuses_to_send(self,api):
        from telegram_bot.postgres_publisher import publish
        with self.assertRaises(ValueError): publish(self.dsn,config=self.config,db_path=self.path)
        api.assert_not_called()

    def test_failed_validation_leaves_legacy_writable(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE telegram_outbox SET status='invalid' WHERE source_id='2'"); db.commit()
        with self.assertRaises(ValueError): self.migrate()
        from database.publication_migration import sqlite_token
        self.assertIsNone(sqlite_token(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE telegram_outbox SET status='pending' WHERE source_id='2'"); db.commit()

    def test_concurrent_sender_refused(self):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate(); self.normalized()
        with self.pg.connect(self.dsn,autocommit=True) as conn:
            conn.execute('SELECT pg_advisory_lock(11)')
            with self.assertRaises(ValueError): prepare_queue(self.dsn,config=self.config,db_path=self.path)

    @patch.dict(os.environ,{'JOOBLE_API_KEY':'test-only'})
    @patch('database.jooble_schedule.fetch_jobs')
    def test_daily_jooble_restart_failure_limit_and_fifty_publications(self,fetch):
        import json
        from datetime import date,datetime,timezone,timedelta
        from sources.jooble import JoobleBatch,JoobleError
        from database.jooble_schedule import run_daily,reserve_publication
        self.migrate()
        raw=json.dumps({'jobs':[dict(id=i,title='Magacioner',link=f'https://rs.jooble.org/jdp/{i}',updated=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat()) for i in range(1,53)]}).encode()
        fetch.return_value=JoobleBatch(raw,datetime.now(timezone.utc),{})
        day=date(2026,10,2)
        self.assertEqual(run_daily(self.dsn,day=day),0)
        self.assertEqual(run_daily(self.dsn,day=day),0)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(fetch.call_args.args[-1],50)
        with self.pg.connect(self.dsn) as conn:
            ids=conn.execute("SELECT source_id FROM serbia_jobs.vacancies WHERE source='jooble' ORDER BY source_id").fetchall()
            self.assertEqual(ids,sorted([(str(i),) for i in range(3,53)]))
            for i in range(50):self.assertTrue(reserve_publication(conn,11,str(i),day))
            self.assertTrue(reserve_publication(conn,11,'0',day))
            self.assertFalse(reserve_publication(conn,11,'51',day))
            self.assertTrue(reserve_publication(conn,11,'51',day+timedelta(days=1)))
        fetch.side_effect=JoobleError('unavailable')
        self.assertEqual(run_daily(self.dsn,day=day+timedelta(days=1)),1)
        self.assertEqual(run_daily(self.dsn,day=day+timedelta(days=1)),0)
        self.assertEqual(fetch.call_count,2)
        with self.pg.connect(self.dsn) as conn:
            conn.execute('UPDATE serbia_jobs.jooble_request_baseline SET requests=498')
        run_daily(self.dsn,day=day+timedelta(days=2))
        self.assertEqual(fetch.call_count,2)

    @patch.dict(os.environ,{'TRANSLATION_PROVIDER':'mymemory'})
    @patch('telegram_bot.mymemory_translation.mymemory_translate')
    def test_one_bad_phrase_does_not_stop_other_jobs(self,translate):
        from telegram_bot.postgres_publisher import prepare_queue
        from telegram_bot.automatic_translation import TranslationNeedsReview,TranslationUnavailable
        self.migrate();self.normalized()
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Untranslated phrase' WHERE source_id='2'")
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Good phrase' WHERE source_id='5'")
        translate.side_effect=[TranslationNeedsReview('same text'),{'sr':'Nova uloga','ru':'Новая должность'}]
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(translate.call_count,2)
        with self.pg.connect(self.dsn) as conn:
            self.assertIsNotNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone()[0])
            self.assertIsNotNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source_id='5'").fetchone()[0])
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Another phrase' WHERE source_id='5'")
        translate.reset_mock();translate.side_effect=TranslationUnavailable('quota exhausted')
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(translate.call_count,1)
        with self.pg.connect(self.dsn) as conn:
            self.assertIsNotNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source_id='5'").fetchone()[0])

    def test_mymemory_daily_budget_and_cooldown(self):
        from telegram_bot.mymemory_translation import reserve,block_quota
        from telegram_bot.automatic_translation import TranslationUnavailable
        self.migrate()
        reserve(self.dsn,4990)
        with self.assertRaises(TranslationUnavailable):reserve(self.dsn,11)
        reserve(self.dsn,10)
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT characters FROM serbia_jobs.mymemory_usage').fetchone()[0],5000)
            conn.execute('DELETE FROM serbia_jobs.mymemory_usage')
        block_quota(self.dsn)
        with self.assertRaises(TranslationUnavailable):reserve(self.dsn,1)

    @patch.dict(os.environ,{'TRANSLATION_PROVIDER':'mymemory'})
    @patch('telegram_bot.mymemory_translation.mymemory_translate',return_value={'sr':'Nova uloga','ru':'Новая должность'})
    def test_mymemory_reuses_saved_translation(self,translate):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate();self.normalized()
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Unseen role' WHERE source_id IN ('2','5')")
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(translate.call_count,1)
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT version FROM serbia_jobs.translation_cache').fetchone()[0],'mymemory-sr-ru-v1')

    @patch.dict(os.environ,{'TRANSLATION_PROVIDER':'google'})
    @patch('telegram_bot.google_translation.google_translate',return_value={'sr':'Nova uloga','ru':'Новая должность'})
    def test_google_cache_and_service_failure(self,translate):
        from telegram_bot.postgres_publisher import prepare_queue
        from telegram_bot.automatic_translation import TranslationUnavailable
        self.migrate(); self.normalized()
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Novel role' WHERE source_id IN ('2','5')")
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(translate.call_count,1)
        with self.pg.connect(self.dsn) as conn:
            self.assertTrue(conn.execute('SELECT version FROM serbia_jobs.translation_cache').fetchone()[0].startswith('google-'))
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Another role' WHERE source_id='2'")
        translate.side_effect=TranslationUnavailable('HTTP 429')
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        with self.pg.connect(self.dsn) as conn:
            self.assertIsNotNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone()[0])
            self.assertIsNotNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source_id='5'").fetchone()[0])

    @patch('telegram_bot.automatic_translation.azure_translate',return_value={'sr':'Nova uloga','ru':'Новая должность'})
    def test_automatic_translation_is_cached_across_preparations(self,translate):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate(); self.normalized()
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET title='New role' WHERE source_id IN ('2','5')")
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(translate.call_count,1)
        with self.pg.connect(self.dsn) as conn:
            rows=conn.execute("SELECT body,format_version FROM serbia_jobs.telegram_outbox WHERE source_id IN ('2','5')").fetchall()
            self.assertTrue(all('Новая должность' in r[0] and r[1] for r in rows))
            self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.translation_cache').fetchone()[0],1)

    @patch('telegram_bot.postgres_publisher.time.sleep')
    @patch('telegram_bot.postgres_publisher.api')
    def test_jooble_queue_rechecks_duplicates_and_sends_once(self,api,sleep):
        import json
        from datetime import datetime,timezone
        from database.jooble import save_batch
        from sources.jooble import JoobleBatch
        from telegram_bot.postgres_publisher import prepare_queue,publish
        self.migrate(); self.normalized()
        def save(items):
            save_batch(JoobleBatch(json.dumps({'jobs':items}).encode(),datetime.now(timezone.utc),{}),self.dsn)
        def job(i,company,salary=''):
            return dict(id=i,title='Magacioner',company=company,location='Ripanj',salary=salary,
                        link=f'https://rs.jooble.org/jdp/{i}',snippet='')
        save([job(100,'Unique'),job(101,'Suspicious','70 din'),job(102,'Repeated'),job(103,'Repeated')])
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        api.assert_not_called()
        with self.pg.connect(self.dsn) as conn:
            rows=conn.execute("SELECT source_id,thread_id,format_version FROM serbia_jobs.telegram_outbox WHERE source='jooble'").fetchall()
            self.assertEqual(rows,[('100',5,'four-fields-sr-ru-v1')])
        # A new cross-source candidate must disable an already queued post.
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Magacioner',company='Unique',locations='[\"Ripanj\"]'::jsonb WHERE source='infostud' AND source_id='1'")
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        with self.pg.connect(self.dsn) as conn:
            self.assertIsNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source='jooble'").fetchone()[0])
            conn.execute("UPDATE serbia_jobs.vacancies SET company='Different' WHERE source='infostud' AND source_id='1'")
            conn.execute("UPDATE serbia_jobs.telegram_outbox SET status='sent' WHERE source='infostud' AND status='pending'")
        api.side_effect=[{'id':22},{'message_id':888}]
        self.assertEqual(publish(self.dsn,config=self.config,db_path=self.path),1)
        self.assertEqual(publish(self.dsn,config=self.config,db_path=self.path),0)
        self.assertEqual(api.call_count,2)
        self.assertEqual(api.call_args.kwargs['message_thread_id'],5)
        self.assertIn('Jezici:',api.call_args.kwargs['text'])
        self.assertIn('Языки:',api.call_args.kwargs['text'])

    def test_stale_extraction_disables_pending_send(self):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate(); self.normalized()
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET four_fields=NULL WHERE source_id='2'")
        prepare_queue(self.dsn,config=self.config,db_path=self.path)
        with self.pg.connect(self.dsn) as conn:
            self.assertIsNone(conn.execute("SELECT format_version FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone()[0])

    @patch('telegram_bot.postgres_publisher.api',side_effect=AssertionError('Preparation must not send'))
    def test_prepared_job_outside_latest_rss_is_queued_once(self,api):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate(); self.normalized()
        prepare_queue(self.dsn,['1'],self.config,self.path)
        prepare_queue(self.dsn,[],self.config,self.path)
        with self.pg.connect(self.dsn) as conn:
            rows=conn.execute("SELECT status,format_version FROM serbia_jobs.telegram_outbox WHERE source_id='5'").fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0],('pending','four-fields-sr-ru-v1'))
            self.assertEqual(conn.execute("SELECT count(*) FROM serbia_jobs.telegram_outbox WHERE source_id='1'").fetchone()[0],1)
        api.assert_not_called()

    @patch('telegram_bot.postgres_publisher.api',side_effect=AssertionError('Must not send unreviewed translation'))
    def test_missing_title_translation_prepares_original_without_blocking_others(self,api):
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate(); self.normalized()
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Unseen role' WHERE source_id IN ('2','5')")
        prepare_queue(self.dsn,['5'],self.config,self.path)
        with self.pg.connect(self.dsn) as conn:
            rows=conn.execute("SELECT source_id,format_version,translation_issue,status FROM serbia_jobs.telegram_outbox WHERE source_id IN ('2','5') ORDER BY source_id").fetchall()
            self.assertEqual(len(rows),2)
            self.assertTrue(all(r[1] is not None and r[2] is None and r[3]=='pending' for r in rows))
            conn.execute("UPDATE serbia_jobs.vacancies SET title='Kasir - prodavac' WHERE source_id IN ('2','5')")
        prepare_queue(self.dsn,['5'],self.config,self.path)
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.telegram_outbox WHERE translation_issue IS NOT NULL').fetchone()[0],0)
        api.assert_not_called()

    @patch('telegram_bot.postgres_publisher.time.sleep')
    @patch('telegram_bot.postgres_publisher.api')
    def test_bad_message_is_held_and_good_message_sends_across_restarts(self,api,sleep):
        from telegram_bot.postgres_publisher import publish
        from telegram_bot.client import TelegramError
        self.migrate(); self.normalized()
        api.side_effect=[{'id':22},TelegramError("Bad Request: can't parse entities",error_code=400,message_specific=True),{'message_id':777}]
        self.assertEqual(publish(self.dsn,config=self.config,db_path=self.path),1)
        self.assertEqual(publish(self.dsn,config=self.config,db_path=self.path),0)
        self.assertEqual(api.call_count,3)
        with self.pg.connect(self.dsn) as conn:
            row=conn.execute("SELECT status,delivery_issue FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone()
            self.assertEqual(row[0],'pending');self.assertIn("can't parse entities",row[1])
        self.assertEqual(self.states()[-1],('5','sent',777))

    @patch('telegram_bot.postgres_publisher.api')
    def test_rate_limit_survives_restart_and_pauses_other_messages(self,api):
        from telegram_bot.postgres_publisher import publish
        from telegram_bot.client import TelegramError
        self.migrate();self.normalized()
        api.side_effect=[{'id':22},TelegramError('Too Many Requests',error_code=429,retry_after=7200)]
        with self.assertRaises(TelegramError):publish(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(publish(self.dsn,config=self.config,db_path=self.path),0)
        self.assertEqual(api.call_count,2)
        with self.pg.connect(self.dsn) as conn:
            row=conn.execute("SELECT status,delivery_issue,retry_at>now()+interval '1 hour' FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone()
            self.assertEqual(row,('pending',None,True))

    @patch('telegram_bot.postgres_publisher.api')
    def test_permission_failure_does_not_quarantine_vacancy(self,api):
        from telegram_bot.postgres_publisher import publish
        from telegram_bot.client import TelegramError
        self.migrate();self.normalized()
        api.side_effect=[{'id':22},TelegramError('Forbidden',error_code=403)]
        with self.assertRaises(TelegramError):publish(self.dsn,config=self.config,db_path=self.path)
        self.assertEqual(api.call_count,2)
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("SELECT status,delivery_issue FROM serbia_jobs.telegram_outbox WHERE source_id='2'").fetchone(),('pending',None))

    def test_jooble_manual_category_reuse_location_expiry_and_pending_reroute(self):
        import json
        from datetime import datetime,timezone,timedelta
        from sources.jooble import JoobleBatch
        from database.jooble import save_batch
        from database.jooble_classification import assign,learn_rules
        from telegram_bot.jooble_preview import build
        from telegram_bot.postgres_publisher import prepare_queue
        self.migrate()
        self.normalized()
        now=datetime.now(timezone.utc)
        items=[dict(id=i,title='Novel occupation',company=str(i),location='Beograd',
                    link=f'https://rs.jooble.org/jdp/{i}') for i in (100,101)]
        def save():
            save_batch(JoobleBatch(json.dumps({'jobs':items}).encode(),now,{}),self.dsn)
        save()
        self.assertTrue(all(p['category']['status']=='UNKNOWN' for p in build(self.dsn)))
        assign(self.dsn,'100',category='logistics',reason='Reviewed title')
        with self.pg.connect(self.dsn) as conn:
            learn_rules(conn)
        posts=build(self.dsn)
        self.assertTrue(all(p['category']['origin']=='MANUAL' for p in posts))
        self.assertTrue(all(p['review_status']=='DRAFT' for p in posts))
        prepare_queue(self.dsn,[],self.config,self.path)
        assign(self.dsn,'100',cities=['Novi Sad'],remote=False,reason='Confirmed workplace')
        prepare_queue(self.dsn,[],self.config,self.path)
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("SELECT thread_id FROM serbia_jobs.telegram_outbox WHERE source='jooble' AND source_id='100'").fetchall(),[(4,)])
        # A later advertisement with the same title inherits the manual category.
        items.append(dict(items[1],id=102,company='102',link='https://rs.jooble.org/jdp/102'))
        now+=timedelta(seconds=1)
        items[0]['location']='Unclear village'
        save()
        posts={p['source_id']:p for p in build(self.dsn)}
        self.assertEqual(posts['102']['category']['origin'],'MANUAL')
        self.assertEqual(posts['100']['location']['status'],'REVIEW')
        self.assertNotEqual(posts['100']['location']['origin'],'MANUAL')
        self.assertEqual(posts['100']['review_status'],'REVIEW')
        with self.pg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM serbia_jobs.jooble_classification_history').fetchone()[0],2)

    def test_jooble_exclusion_and_manual_russian_title(self):
        import json
        from datetime import datetime,timezone
        from sources.jooble import JoobleBatch
        from database.jooble import save_batch
        from telegram_bot.jooble_preview import build
        self.migrate()
        item=dict(id=900,title='Magacioner',location='Beograd',link='https://rs.jooble.org/jdp/900')
        save_batch(JoobleBatch(json.dumps({'jobs':[item]}).encode(),datetime.now(timezone.utc),{}),self.dsn)
        with self.pg.connect(self.dsn) as conn:
            conn.execute("UPDATE serbia_jobs.jooble_title_categories SET title_ru='Проверенное название' WHERE title_key='magacioner'")
            conn.execute("INSERT INTO serbia_jobs.jooble_exclusions(source_id,reason) VALUES ('900','User removed')")
        post=build(self.dsn)[0]
        self.assertIn('Проверенное название',post['body'])
        self.assertIn('Magacioner',post['body'])
        self.assertEqual(post['review_status'],'EXCLUDED')
        item['title']='Changed title'
        save_batch(JoobleBatch(json.dumps({'jobs':[item]}).encode(),datetime.now(timezone.utc),{}),self.dsn)
        self.assertEqual(build(self.dsn)[0]['review_status'],'EXCLUDED')
