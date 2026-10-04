import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram_bot import search_data as data
from telegram_bot.search_bot import SearchMenu, Store, card, PacedClient
from telegram_bot.client import TelegramError
from telegram_bot.search_groups import GROUPS, category_group, city_group, city_options, grouped_cities, migrate_categories

NOW = datetime(2026,10,3,12,tzinfo=timezone.utc)


def job(index=1, **values):
    result=dict(source='infostud',source_id=str(index),title='Accountant <Senior>',
                company='A & B', cities=['Beograd'],remote=False,search_category='finance',
                category_label='Финансы',pay=None,languages=[],deadline=None,closed=False,
                first_seen_at=NOW-timedelta(days=2),published_at=NOW-timedelta(minutes=index),
                source_url='https://poslovi.infostud.com/posao/accountant/'+str(index))
    result.update(values)
    return result


class MatchingTests(unittest.TestCase):
    def test_city_order_and_suburbs(self):
        options=city_options(['Zemun','Kać','Kac','Sremska Kamenica','Niš','Beograd','Čačak'], data.REMOTE_KEY)
        self.assertEqual(options[:3],[[data.REMOTE_KEY,'Удалённая работа'],['Beograd','Белград'],['Novi Sad','Нови-Сад']])
        self.assertEqual([x[0] for x in options[3:]],['Čačak','Niš'])
        self.assertEqual(grouped_cities(['Zemun','Beograd','Novi Beograd']),['Beograd'])
        self.assertEqual(grouped_cities(['Kać','Kac','Sremska Kamenica','Novi Sad']),['Novi Sad'])
        self.assertEqual(city_group('Pančevo'),'Pančevo')

    def test_shared_categories_and_manual_precedence(self):
        self.assertEqual(len(GROUPS),10)
        self.assertEqual(category_group('računovodstvo, knjigovodstvo','Accountant'), 'office')
        self.assertEqual(category_group('magacin'), 'logistics')
        self.assertEqual(category_group(None,'Account Manager'), 'sales')
        self.assertEqual(category_group(None,'Accountant at a hotel'), 'office')
        self.assertEqual(category_group(None,'Unknown occupation'), 'other')
        self.assertEqual(category_group('magacin','Warehouse',{'origin':'MANUAL','category':'finance'}), 'office')
        self.assertEqual(migrate_categories(['source:magacin','group:logistics','group:finance']),['logistics','office'])

    @patch('telegram_bot.search_bot.time.sleep')
    @patch('telegram_bot.search_bot.api')
    def test_rate_limit_retry_but_never_uncertain_delivery(self, api, sleep):
        api.side_effect=[TelegramError('rate limit',error_code=429,retry_after=2),{}]
        PacedClient()('sendMessage',chat_id=1,text='test')
        self.assertEqual(api.call_count,2)
        api.reset_mock();api.side_effect=TelegramError('network',uncertain=True)
        with self.assertRaises(TelegramError):
            PacedClient()('sendMessage',chat_id=1,text='test')
        self.assertEqual(api.call_count,1)

    @patch('telegram_bot.search_bot.serve')
    @patch('main.run_hourly')
    def test_search_only_does_not_start_collection(self, hourly, serve):
        import main
        self.assertEqual(main.main(['--search-bot']),0)
        serve.assert_called_once()
        hourly.assert_not_called()

    def test_range_overlap_and_unknown(self):
        pay=dict(min=100000,max=150000,currency='RSD',period='MONTH',basis='NET')
        self.assertTrue(data.salary_match(job(pay=pay),120000,False))
        self.assertFalse(data.salary_match(job(pay=pay),160000,True))
        self.assertTrue(data.salary_match(job(),120000,True))
        self.assertFalse(data.salary_match(job(),120000,False))
        for change in ({'currency':'EUR'},{'period':'DAY'},{'basis':'GROSS'},{'period':None}):
            self.assertTrue(data.salary_match(job(pay=dict(pay,**change)),120000,True))
            self.assertFalse(data.salary_match(job(pay=dict(pay,**change)),120000,False))

    def test_one_sided_salary(self):
        p=dict(min=None,max=120000,currency='RSD',period='MONTH',basis='NET')
        self.assertTrue(data.salary_match(job(pay=p),120000,False))
        self.assertFalse(data.salary_match(job(pay=p),150000,True))
        p.update(min=100000,max=None)
        self.assertTrue(data.salary_match(job(pay=p),120000,True))
        self.assertFalse(data.salary_match(job(pay=p),120000,False))

    def test_remote_is_explicit_alternative(self):
        remote=job(remote=True)
        self.assertFalse(data.matches(remote,{'cities':['Beograd']},NOW))
        self.assertTrue(data.matches(remote,{'cities':['Beograd',data.REMOTE_KEY]},NOW))
        self.assertTrue(data.matches(remote,{},NOW))
        self.assertFalse(data.matches(job(),{'cities':[data.REMOTE_KEY]},NOW))
        self.assertTrue(data.matches(job(),{'cities':['Novi Sad','Beograd']},NOW))

    def test_deadlines_and_30_days(self):
        self.assertTrue(data.active(job(deadline='03.10.2026.'),NOW))
        self.assertFalse(data.active(job(deadline='02.10.2026.'),NOW))
        self.assertTrue(data.active(job(first_seen_at=NOW-timedelta(days=40),deadline='05.10.2026.'),NOW))
        self.assertTrue(data.active(job(deadline='2026-10-03'),NOW))
        self.assertFalse(data.active(job(deadline='2026-10-02'),NOW))
        self.assertFalse(data.active(job(deadline='2026-10-03T11:00:00Z'),NOW))
        self.assertFalse(data.active(job(first_seen_at=NOW-timedelta(days=31)),NOW))
        self.assertTrue(data.active(job(first_seen_at=NOW-timedelta(days=31),deadline='2026-10-05'),NOW))
        self.assertFalse(data.active(job(closed=True,deadline='2026-10-05'),NOW))

    def test_category_language_and_sort(self):
        jobs=[job(3),job(1,languages=[{'language':'sr','requirement':'REQUIRED'}]),job(2)]
        self.assertEqual([j['source_id'] for j in data.select(jobs,{},NOW)],['1','2','3'])
        self.assertEqual(len(data.select(jobs,{'categories':['it']},NOW)),0)
        self.assertEqual(len(data.select(jobs,{'categories':['it','finance']},NOW)),3)

    def test_card_escapes_and_has_no_format_row(self):
        text=card(job(remote=True))
        self.assertIn('&lt;Senior&gt;',text)
        self.assertIn('Удалённая работа',text)
        self.assertIn('Языковые требования не указаны',text)
        self.assertNotIn('Формат работы',text)
        self.assertNotIn('href=',card(job(source_url='javascript:alert(1)')))


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'state.sqlite')
        self.calls=[]
        now=datetime.now(timezone.utc)
        self.jobs=[job(i,first_seen_at=now-timedelta(days=1),published_at=now-timedelta(minutes=i)) for i in range(1,13)]
        self.menu=SearchMenu(self.store,lambda:self.jobs,lambda method,**kw:self.calls.append((method,kw)))
        self.store.save(7,dict(cities=[],categories=[],minimum=None,include_unknown=True,locale='ru'))

    def tearDown(self):
        self.store.conn.close();self.temp.cleanup()

    def click(self,action,uid=7,rev=None):
        rev=rev or self.store.get(uid)['rev']
        self.menu.handle({'callback_query':{'id':'cb','from':{'id':uid},
                         'message':{'chat':{'id':uid,'type':'private'}},'data':'s:'+rev+':'+action}})

    def test_full_flow_five_then_five_and_stale_button(self):
        self.menu.handle({'message':{'chat':{'id':7,'type':'private'},'text':'/start'}})
        self.click('start');self.click('next');self.click('next')
        self.assertTrue(self.store.get(7)['include_unknown'])
        self.click('salary:3')
        self.assertEqual(self.store.get(7)['minimum'],120000)
        before=len(self.calls);self.click('results')
        cards=[kw for method,kw in self.calls[before:] if kw.get('parse_mode')=='HTML']
        self.assertEqual(len(cards),5)
        stale=self.store.get(7)['rev'];before=len(self.calls);self.click('more')
        self.assertEqual(len([kw for _,kw in self.calls[before:] if kw.get('parse_mode')=='HTML']),5)
        before=len(self.calls);self.click('more',rev=stale)
        self.assertEqual(len(self.calls)-before,1)
        self.assertEqual(self.store.get(7)['position'],10)

    def test_multi_select_and_isolation(self):
        self.menu.home(7);self.click('start');self.click('pick:0');self.click('pick:1')
        self.assertEqual(set(self.store.get(7)['cities']),{data.REMOTE_KEY,'Beograd'})
        self.menu.home(8)
        self.assertEqual(self.store.get(8)['cities'],[])
        self.click('all');self.assertEqual(self.store.get(7)['cities'],[])

    def test_menu_pins_cities_and_replaces_old_categories(self):
        self.menu.home(7)
        session=self.store.get(7)
        session.update(cities=['Zemun'],categories=['source:magacin'])
        self.store.save(7,session)
        self.click('start')
        labels=[row[0]['text'].replace('✅ ','') for row in self.calls[-1][1]['reply_markup']['inline_keyboard']]
        self.assertEqual(labels[:4],['Вся Сербия','Удалённая работа','Белград','Нови-Сад'])
        session=self.store.get(7)
        self.assertEqual(session['cities'],['Beograd'])
        self.assertEqual(session['categories'],['logistics'])
        self.assertEqual(len(session['categories_options']),10)

    def test_ignore_group_and_restart_state(self):
        self.menu.handle({'message':{'chat':{'id':-1,'type':'supergroup'},'text':'/start'}})
        self.assertEqual(self.calls,[])
        self.menu.home(7);self.store.advance(55)
        other=Store(Path(self.temp.name)/'state.sqlite')
        self.assertEqual(other.offset(),55)
        self.assertEqual(other.get(7)['cities'],[])
        other.conn.close()

    def test_first_start_language_selection_and_persistence(self):
        self.menu.home(9)
        self.assertEqual(self.store.get(9)['step'],'language')
        self.assertIn('Izaberite jezik',self.calls[-1][1]['text'])
        self.click('lang:sr',uid=9)
        self.assertEqual(self.store.get(9)['locale'],'sr')
        self.assertIn('Pretraga poslova',self.calls[-1][1]['text'])
        other=Store(Path(self.temp.name)/'state.sqlite')
        self.assertEqual(other.get(9)['locale'],'sr')
        other.conn.close()
        self.menu.home(9)
        self.assertEqual(self.store.get(9)['step'],'home')
        self.store.conn.execute('DELETE FROM sessions WHERE user_id=9')
        self.store.conn.commit()
        self.assertEqual(self.store.get(9)['locale'],'sr')

    def test_serbian_flow_and_switch_keeps_filters(self):
        self.menu.home(9);self.click('lang:sr',uid=9);self.click('start',uid=9)
        labels=[row[0]['text'] for row in self.calls[-1][1]['reply_markup']['inline_keyboard']]
        self.assertEqual(labels[:4],['✅ Cela Srbija','Rad na daljinu','Beograd','Novi Sad'])
        self.click('pick:1',uid=9);self.click('next',uid=9)
        self.assertIn('Prodaja',self.calls[-1][1]['reply_markup']['inline_keyboard'][1][0]['text'])
        self.click('next',uid=9)
        self.assertIn('Zarada',self.calls[-1][1]['text'])
        self.click('results',uid=9)
        self.assertIn('Prikazano poslova',self.calls[-1][1]['text'])
        self.click('language',uid=9);self.click('lang:ru',uid=9)
        self.assertEqual(self.store.get(9)['cities'],['Beograd'])
        self.assertIn('Поиск работы',self.calls[-1][1]['text'])

    def test_cards_localized_without_source_category(self):
        entry=job(title='Untranslated role',search_category='office',original_category='računovodstvo')
        russian=card(entry,'ru');serbian=card(entry,'sr')
        self.assertIn('Untranslated role',russian)
        self.assertNotIn('Категория источника',russian)
        self.assertNotIn('računovodstvo',serbian)
        self.assertIn('Administracija, finansije i upravljanje',serbian)
        self.assertIn('Jezički zahtevi nisu navedeni',serbian)
        self.assertNotRegex(serbian,r'[А-Яа-яЁё]')
        entry.update(title_ru='Переведённая должность',title_sr='Preveden naziv')
        self.assertIn('Переведённая должность',card(entry,'ru'))
        self.assertIn('Preveden naziv',card(entry,'sr'))

    def test_old_session_prompts_without_losing_filters(self):
        self.store.save(10,dict(cities=['Beograd'],categories=['office'],minimum=120000,include_unknown=True))
        self.menu.home(10)
        self.assertEqual(self.store.get(10)['step'],'language')
        self.click('lang:sr',uid=10)
        self.assertEqual(self.store.get(10)['minimum'],120000)


if __name__=='__main__': unittest.main()
