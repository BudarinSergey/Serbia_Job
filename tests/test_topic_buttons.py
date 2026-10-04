import unittest
from unittest.mock import MagicMock, patch

from telegram_bot import postgres_publisher as publisher


class TopicButtonTests(unittest.TestCase):
    @patch.object(publisher.time,'sleep')
    @patch('database.jooble_schedule.reserve_publication',return_value=True)
    @patch.object(publisher,'api')
    @patch.object(publisher,'_prepare_posts')
    @patch.object(publisher,'publisher_connection')
    def test_each_topic_and_source_gets_button_in_original_send(self, connection, prepare, api, reserve, sleep):
        rows=[(index,thread,'Original body '+str(thread),source,str(index))
              for index,(thread,source) in enumerate([(3,'infostud'),(4,'jooble'),(5,'infostud'),(6,'jooble')],1)]
        conn=MagicMock()
        connection.return_value.__enter__.return_value=conn
        def execute(sql,params=None):
            result=MagicMock();result.rowcount=1
            if 'SELECT o.id,o.thread_id' in sql: result.fetchall.return_value=rows
            elif 'SELECT count(*) FILTER' in sql: result.fetchone.return_value=(0,0)
            elif 'SELECT max(retry_at)' in sql: result.fetchone.return_value=(None,)
            elif 'SELECT count(*)' in sql: result.fetchone.return_value=(0,)
            return result
        conn.execute.side_effect=execute
        api.side_effect=[{'id':22}]+[{'message_id':100+i} for i in range(4)]
        self.assertEqual(publisher.publish('fake',config={'chat_id':11,'bot_id':22}),4)
        sends=[call for call in api.call_args_list if call.args==('sendMessage',)]
        self.assertEqual([call.kwargs['message_thread_id'] for call in sends],[3,4,5,6])
        for call in sends:
            button=call.kwargs['reply_markup']['inline_keyboard'][0][0]
            self.assertEqual(button['text'],'🔎 Искать вакансии / Pronađi posao')
            self.assertEqual(button['url'],'https://t.me/SerbiaJob_bot?start=search')
            self.assertEqual(call.kwargs['text'],'Original body '+str(call.kwargs['message_thread_id']))
        self.assertEqual([call.args[0] for call in api.call_args_list],['getMe']+['sendMessage']*4)


if __name__=='__main__': unittest.main()
