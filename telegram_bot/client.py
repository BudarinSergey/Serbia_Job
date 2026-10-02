"""Small Telegram client; errors never include token-bearing request URLs."""
from pathlib import Path
from dotenv import dotenv_values
import requests

ROOT = Path(__file__).resolve().parents[1]

class TelegramError(RuntimeError):
    def __init__(self, message, uncertain=False, error_code=None, retry_after=None, message_specific=False):
        super().__init__(message)
        self.uncertain = uncertain
        self.error_code = error_code
        self.retry_after = retry_after
        self.message_specific = message_specific


def api(method, **params):
    token = dotenv_values(ROOT / '.env').get('TELEGRAM_BOT_TOKEN', '') or ''
    token = token.strip()
    if not token:
        raise TelegramError('TELEGRAM_BOT_TOKEN is missing in .env')
    try:
        response = requests.post(f'https://api.telegram.org/bot{token}/{method}', json=params, timeout=(10, 30))
        data = response.json()
    except (requests.RequestException, ValueError):
        raise TelegramError(f'{method}: network/response error; outcome may be unknown. No automatic retry.', uncertain=True) from None
    if not data.get('ok'):
        description = str(data.get('description', 'API error')).replace(token, '[REDACTED]')
        code = data.get('error_code', response.status_code)
        retry_after = (data.get('parameters') or {}).get('retry_after')
        if not isinstance(retry_after, int) or isinstance(retry_after, bool) or retry_after < 0:
            retry_after = None
        # Only known content failures are local to a message. Chat/topic/permission
        # errors and unknown rejections must stop the cycle, not quarantine jobs.
        local_error = method == 'sendMessage' and code == 400 and any(
            marker in description.casefold() for marker in (
                "can't parse entities", "can't find end of", "unsupported start tag",
                "message is too long", "message text is empty", "text must be non-empty",
                "wrong http url", "button_url_invalid"))
        raise TelegramError(f'{method}: {description}', error_code=code,
                            retry_after=retry_after, message_specific=local_error)
    return data['result']
