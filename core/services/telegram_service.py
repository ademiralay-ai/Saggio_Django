"""Telegram Bot API helpers and update dispatcher.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import TelegramBot, TelegramBotButton, TelegramBotMenu
from ..utils.parsing import _normalize_allowed_user_ids


def _is_user_allowed_for_bot(bot, user_id):
    """Telegram user_id (int) izinli listesinde mi?"""
    if user_id is None:
        return False
    allowed = _normalize_allowed_user_ids(bot.allowed_user_ids or '')
    if not allowed:
        return False  # boş liste = kapalı bot (güvenlik öncelikli)
    try:
        return int(user_id) in allowed
    except (TypeError, ValueError):
        return False


def _telegram_api_call(token, method, payload):
    """Telegram Bot API'sini JSON POST ile çağırır."""
    if not token:
        return False, {'description': 'token_missing'}
    try:
        req = Request(
            f'https://api.telegram.org/bot{token}/{method}',
            data=json.dumps(payload).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json'},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8') or '{}')
        return bool(data.get('ok')), data
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode('utf-8') or '{}')
        except Exception:
            body = {'description': str(e)}
        return False, body
    except URLError as e:
        return False, {'description': f'baglanti_hatasi: {e.reason}'}
    except Exception as e:
        return False, {'description': str(e)}


def _telegram_send_with_keyboard(token, chat_id, text, inline_keyboard=None, parse_mode=None):
    payload = {'chat_id': chat_id, 'text': text or ''}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if inline_keyboard:
        payload['reply_markup'] = {'inline_keyboard': inline_keyboard}
    return _telegram_api_call(token, 'sendMessage', payload)


def _telegram_answer_callback(token, callback_id, text='', show_alert=False):
    payload = {'callback_query_id': callback_id, 'text': text or '', 'show_alert': bool(show_alert)}
    return _telegram_api_call(token, 'answerCallbackQuery', payload)


def _render_menu_inline_keyboard(menu):
    """TelegramBotMenu -> Telegram inline_keyboard listesi."""
    rows = {}
    for b in menu.buttons.all().order_by('row', 'col'):
        rows.setdefault(b.row, []).append({
            'text': b.label,
            'callback_data': f'btn:{b.pk}',
        })
    return [rows[r] for r in sorted(rows)]


def _trigger_sap_process_for_telegram(process_id, source_label=''):
    """
    Telegram callback'inden tetiklenen SAP süreci için arka plan başlatma.
    Mevcut runtime endpoint'ini iç HTTP isteği ile çalıştırır; CSRF/auth'tan etkilenmez
    çünkü Django test client kullanıyoruz.
    """
    import threading

    def _runner():
        try:
            from django.test import Client
            client = Client(enforce_csrf_checks=False)
            client.post(f'/sap-process/{process_id}/run/', data={}, content_type='application/json')
        except Exception:
            pass

    t = threading.Thread(target=_runner, name=f'tg-trigger-{process_id}', daemon=True)
    t.start()


def process_telegram_update(bot, update):
    """Tek bir Telegram update'ini (webhook veya polling) tutarlı şekilde işler."""
    token = bot.get_bot_token()

    # 1) Inline buton tıklaması
    cb = update.get('callback_query')
    if cb:
        from_user = (cb.get('from') or {})
        user_id = from_user.get('id')
        chat_id = (((cb.get('message') or {}).get('chat')) or {}).get('id')
        callback_id = cb.get('id')
        data = str(cb.get('data') or '')

        if not _is_user_allowed_for_bot(bot, user_id):
            _telegram_answer_callback(token, callback_id, 'Yetkiniz yok.', show_alert=True)
            return

        if data.startswith('btn:'):
            try:
                btn_pk = int(data.split(':', 1)[1])
            except (ValueError, IndexError):
                btn_pk = 0
            btn = TelegramBotButton.objects.select_related('sap_process', 'menu').filter(
                pk=btn_pk, menu__bot=bot
            ).first()
            if not btn:
                _telegram_answer_callback(token, callback_id, 'Buton bulunamadı.')
                return
            if not btn.sap_process:
                _telegram_answer_callback(token, callback_id, 'Bu butona süreç bağlanmamış.')
                return
            _telegram_answer_callback(token, callback_id, 'Süreç başlatılıyor…')
            _telegram_send_with_keyboard(
                token, chat_id,
                f'✅ Süreç başlatma talebi alındı:\n<b>{btn.sap_process.name}</b>\n\nİstek: {from_user.get("first_name") or from_user.get("username") or user_id}',
                parse_mode='HTML',
            )
            _trigger_sap_process_for_telegram(btn.sap_process.pk, source_label=str(user_id))
            return

        _telegram_answer_callback(token, callback_id, '')
        return

    # 2) Mesaj (komut)
    msg = update.get('message') or update.get('edited_message')
    if msg:
        from_user = (msg.get('from') or {})
        user_id = from_user.get('id')
        chat_id = ((msg.get('chat') or {}).get('id'))
        text = str(msg.get('text') or '').strip()

        if not _is_user_allowed_for_bot(bot, user_id):
            if chat_id:
                _telegram_send_with_keyboard(
                    token, chat_id,
                    'Bu botu kullanmaya yetkiniz yok.\nKullanıcı ID\'niz: <code>' + str(user_id) + '</code>',
                    parse_mode='HTML',
                )
            return

        if text:
            menu = TelegramBotMenu.objects.filter(
                bot=bot, trigger_command=text, is_active=True
            ).prefetch_related('buttons').first()
            if menu:
                kb = _render_menu_inline_keyboard(menu)
                _telegram_send_with_keyboard(token, chat_id, menu.welcome_message, inline_keyboard=kb)
                return
            _telegram_send_with_keyboard(
                token, chat_id,
                'Bu komut için tanımlı bir menü yok. Kullanılabilir komutları yöneticinizden öğrenin.'
            )

