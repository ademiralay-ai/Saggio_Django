# -*- coding: utf-8 -*-
"""
Tüm aktif Telegram botlarını long-poll (getUpdates) modunda çalıştırır.

Kullanım:
    python manage.py run_telegram_bots
    python manage.py run_telegram_bots --bot-id 3
    python manage.py run_telegram_bots --interval 2

Webhook gerektirmez. Public HTTPS olmadan da çalışır. Veritabanındaki
allowed_user_ids ve menü/buton tanımlarını her döngüde tazeler — paneldeki
değişiklikler anında uygulanır.
"""
import json
import time
import threading
import signal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand

from core.models import TelegramBot
from core.views import process_telegram_update


def _get_updates(token, offset, timeout=25):
    payload = {
        'timeout': timeout,
        'allowed_updates': ['message', 'edited_message', 'callback_query'],
    }
    if offset is not None:
        payload['offset'] = offset
    try:
        req = Request(
            f'https://api.telegram.org/bot{token}/getUpdates',
            data=json.dumps(payload).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json'},
        )
        with urlopen(req, timeout=timeout + 10) as resp:
            return json.loads(resp.read().decode('utf-8') or '{}')
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode('utf-8') or '{}')
        except Exception:
            body = {'description': str(e)}
        return {'ok': False, 'error_code': e.code, 'description': body.get('description', '')}
    except URLError as e:
        return {'ok': False, 'description': f'baglanti_hatasi: {e.reason}'}
    except Exception as e:
        return {'ok': False, 'description': str(e)}


def _delete_webhook(token):
    """Polling moduna geçince webhook varsa kaldırılmalı (Telegram 409 vermesin)."""
    try:
        req = Request(
            f'https://api.telegram.org/bot{token}/deleteWebhook',
            data=b'',
            method='POST',
        )
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8') or '{}')
    except Exception:
        return {}


def _bot_loop(bot_id, stop_event, log):
    """Tek bir bot için long-poll döngüsü. Yorgun düşmesin diye DB nesnesini her turda yenile."""
    bot = TelegramBot.objects.filter(pk=bot_id).first()
    if not bot:
        log(f'[{bot_id}] Bot bulunamadı.')
        return
    token = bot.get_bot_token()
    if not token:
        log(f'[{bot.name}] Token çözülemedi, atlanıyor.')
        return

    # Polling kullanıyorsak webhook kayıtlı olmamalı.
    _delete_webhook(token)
    log(f'[{bot.name}] Polling başlatıldı.')

    offset = None
    backoff = 1
    while not stop_event.is_set():
        try:
            data = _get_updates(token, offset, timeout=25)
        except Exception as e:
            log(f'[{bot.name}] getUpdates beklenmedik hata: {e}')
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)
            continue

        if not data.get('ok'):
            desc = data.get('description', '')
            log(f'[{bot.name}] getUpdates hata: {desc}')
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)
            continue

        backoff = 1
        for upd in data.get('result', []):
            offset = upd.get('update_id', 0) + 1
            try:
                # Her update'te bot'u tazele (allowed_user_ids panelden değişebilir)
                fresh = TelegramBot.objects.filter(pk=bot_id, is_active=True).first()
                if not fresh:
                    log(f'[{bot.name}] Bot deaktive edildi, döngü kapanıyor.')
                    return
                process_telegram_update(fresh, upd)
            except Exception as e:
                log(f'[{bot.name}] update işleme hatası: {e}')

    log(f'[{bot.name}] Polling durduruldu.')


class Command(BaseCommand):
    help = 'Aktif Telegram botlarını long-poll modunda çalıştırır (webhook gerektirmez).'

    def add_arguments(self, parser):
        parser.add_argument('--bot-id', type=int, default=None,
                            help='Sadece belirli bir botu çalıştır.')
        parser.add_argument('--quiet', action='store_true',
                            help='Sadece hataları yaz.')

    def handle(self, *args, **opts):
        bot_id = opts.get('bot_id')
        quiet = opts.get('quiet')

        qs = TelegramBot.objects.filter(is_active=True)
        if bot_id:
            qs = qs.filter(pk=bot_id)
        bots = list(qs)
        if not bots:
            self.stdout.write(self.style.WARNING('Çalıştırılacak aktif bot bulunamadı.'))
            return

        def log(msg):
            if quiet and 'hata' not in msg.lower():
                return
            self.stdout.write(f'{time.strftime("%H:%M:%S")} {msg}')

        stop_event = threading.Event()

        def _on_signal(signum, frame):
            log('Kapatma sinyali alındı, döngüler sonlandırılıyor…')
            stop_event.set()

        try:
            signal.signal(signal.SIGINT, _on_signal)
            signal.signal(signal.SIGTERM, _on_signal)
        except (ValueError, AttributeError):
            pass  # main thread değilse veya platform desteklemiyorsa atla

        threads = []
        for b in bots:
            t = threading.Thread(target=_bot_loop, args=(b.pk, stop_event, log),
                                 name=f'tg-poll-{b.pk}', daemon=True)
            t.start()
            threads.append(t)

        log(f'{len(threads)} bot polling başladı. Durdurmak için Ctrl+C.')
        try:
            while not stop_event.is_set() and any(t.is_alive() for t in threads):
                time.sleep(1)
        except KeyboardInterrupt:
            stop_event.set()

        for t in threads:
            t.join(timeout=5)
        log('Tüm botlar durdu.')
