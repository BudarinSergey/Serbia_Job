"""Google web translation via deep-translator; bounded subprocess, no API key."""
import json
from pathlib import Path
import subprocess
import sys
import time

VERSION='google-deep-translator-1.11.4-v1'

def google_translate(text):
    from telegram_bot.automatic_translation import TranslationUnavailable,validate
    try:
        result=subprocess.run([sys.executable,'-X','utf8','-m','telegram_bot.google_translation'],
            input=json.dumps({'text':text}),text=True,encoding='utf-8',capture_output=True,
            cwd=Path(__file__).resolve().parents[1],timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            if result.stdout.strip()=='RATE_LIMIT':
                raise TranslationUnavailable('Google temporarily limits requests (HTTP 429)')
            raise TranslationUnavailable('Google translation unavailable')
        return validate(text,json.loads(result.stdout))
    except TranslationUnavailable:
        raise
    except (subprocess.TimeoutExpired,OSError,ValueError,TypeError):
        raise TranslationUnavailable('Google translation unavailable; vacancy remains pending') from None

def worker():
    from deep_translator import GoogleTranslator
    from deep_translator.exceptions import TooManyRequests
    from telegram_bot.local_translation import TABLE
    try:
        text=json.loads(sys.stdin.read())['text']
        pair={}
        for target in ('sr','ru'):
            pair[target]=GoogleTranslator(source='auto',target=target).translate(text)
            time.sleep(0.5)
        pair['sr']=pair['sr'].translate(TABLE)
        print(json.dumps(pair,ensure_ascii=False))
        return 0
    except TooManyRequests:
        print('RATE_LIMIT')
        return 1
    except Exception:
        return 1

if __name__=='__main__':
    raise SystemExit(worker())
