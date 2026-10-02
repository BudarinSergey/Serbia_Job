"""Create agreed topics once and persist IDs after every successful API call."""
import json
from telegram_bot.client import ROOT, api, TelegramError

CONFIG = ROOT / 'telegram_bot' / 'topics.json'
TOPICS = {'belgrade': 'Белград', 'novi_sad': 'Нови-Сад',
          'other_cities': 'Другие города', 'remote': 'Удаленная работа'}


def save(config):
    temporary = CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(CONFIG)


def setup(chat_id):
    me = api('getMe')
    chat = api('getChat', chat_id=chat_id)
    member = api('getChatMember', chat_id=chat_id, user_id=me['id'])
    if chat.get('title') != 'Serbia_Job' or not chat.get('is_forum'):
        raise TelegramError('Expected Serbia_Job forum group.')
    if member.get('status') != 'administrator' or not member.get('can_manage_topics'):
        raise TelegramError('Bot needs administrator permission to manage topics.')
    config = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {
        'chat_id': chat_id, 'bot_id': me['id'], 'topics': {}}
    if config['chat_id'] != chat_id or config['bot_id'] != me['id']:
        raise TelegramError('Stored group/bot differs; check configuration.')
    if config.get('pending'):
        raise TelegramError('Previous creation outcome uncertain; inspect group before retrying.')
    save(config)
    for key, name in TOPICS.items():
        if key in config['topics']:
            print('Already configured:', name)
            continue
        config['pending'] = key
        save(config)
        topic = api('createForumTopic', chat_id=chat_id, name=name)
        config['topics'][key] = {'name': topic['name'], 'message_thread_id': topic['message_thread_id']}
        del config['pending']
        save(config)
        print('Created:', topic['name'], 'ID:', topic['message_thread_id'])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--chat-id', required=True, type=int)
    args = parser.parse_args()
    try:
        setup(args.chat_id)
    except TelegramError as exc:
        print(str(exc))
        raise SystemExit(1)
