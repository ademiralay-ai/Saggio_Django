"""Telegram bot studio HTML page + JSON endpoints + webhook receiver.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import (
	SapProcess,
	TelegramBot,
	TelegramBotButton,
	TelegramBotMenu,
)
from ..utils.parsing import _normalize_allowed_user_ids
from ..services.telegram_service import (
	_telegram_api_call,
	process_telegram_update,
)


def telegram_bot_studio(request):
    """Bot menü yönetimi + sohbet simülatörü ana sayfası."""
    bots_qs = TelegramBot.objects.filter(is_active=True).order_by('name')
    bots = []
    for b in bots_qs:
        bots.append({
            'id': b.pk,
            'name': b.name,
            'bot_username': b.bot_username,
            'allowed_user_ids': b.allowed_user_ids or '',
            'webhook_secret': b.webhook_secret or '',
            'webhook_registered_url': b.webhook_registered_url or '',
        })
    sap_processes = list(SapProcess.objects.order_by('name').values('id', 'name'))
    return render(request, 'core/telegram_bot_studio.html', {
        'page_title': 'Telegram Bot Stüdyo',
        'page_subtitle': 'Bot menüleri oluşturun, buton-süreç bağlantısı kurun ve sohbet simülatörüyle test edin.',
        'bots_json': json.dumps(bots, ensure_ascii=False),
        'sap_processes_json': json.dumps(sap_processes, ensure_ascii=False),
    })


@require_POST
def telegram_bot_studio_menu_save(request):
    """Bir bot menüsünü (ve butonlarını) kaydeder ya da günceller."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

    bot_id       = body.get('bot_id')
    menu_id      = body.get('menu_id')
    name         = str(body.get('name', '')).strip()
    trigger      = str(body.get('trigger_command', '/start')).strip() or '/start'
    welcome      = str(body.get('welcome_message', '')).strip()
    buttons_raw  = body.get('buttons', [])

    if not bot_id or not name:
        return JsonResponse({'ok': False, 'error': 'bot_id ve name zorunludur.'}, status=400)

    bot = TelegramBot.objects.filter(pk=bot_id).first()
    if not bot:
        return JsonResponse({'ok': False, 'error': 'Bot bulunamadı.'}, status=404)

    if menu_id:
        menu = TelegramBotMenu.objects.filter(pk=menu_id, bot=bot).first()
        if not menu:
            return JsonResponse({'ok': False, 'error': 'Menü bulunamadı.'}, status=404)
        menu.name = name
        menu.trigger_command = trigger
        menu.welcome_message = welcome
        menu.save()
    else:
        menu = TelegramBotMenu.objects.create(
            bot=bot, name=name, trigger_command=trigger, welcome_message=welcome
        )

    # Mevcut butonları sil ve yeniden oluştur
    menu.buttons.all().delete()
    for btn in (buttons_raw if isinstance(buttons_raw, list) else []):
        label      = str(btn.get('label', '')).strip()
        row        = int(btn.get('row', 0))
        col        = int(btn.get('col', 0))
        process_id = btn.get('sap_process_id')
        if not label:
            continue
        proc = SapProcess.objects.filter(pk=process_id).first() if process_id else None
        TelegramBotButton.objects.create(menu=menu, label=label, sap_process=proc, row=row, col=col)

    return JsonResponse({'ok': True, 'menu_id': menu.pk})


def telegram_bot_studio_menus(request):
    """Bir bota ait menü listesini JSON olarak döner."""
    bot_id = request.GET.get('bot_id')
    if not bot_id:
        return JsonResponse({'ok': False, 'error': 'bot_id gerekli.'}, status=400)
    menus = TelegramBotMenu.objects.filter(bot_id=bot_id).prefetch_related('buttons__sap_process')
    result = []
    for m in menus:
        btns = []
        for b in m.buttons.all():
            btns.append({
                'id': b.pk,
                'label': b.label,
                'row': b.row,
                'col': b.col,
                'sap_process_id': b.sap_process_id,
                'sap_process_name': b.sap_process.name if b.sap_process else None,
            })
        result.append({
            'id': m.pk,
            'name': m.name,
            'trigger_command': m.trigger_command,
            'welcome_message': m.welcome_message,
            'is_active': m.is_active,
            'buttons': btns,
        })
    return JsonResponse({'ok': True, 'menus': result})


@require_POST
def telegram_bot_studio_menu_delete(request):
    """Bir menüyü siler."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
    menu_id = body.get('menu_id')
    deleted, _ = TelegramBotMenu.objects.filter(pk=menu_id).delete()
    if not deleted:
        return JsonResponse({'ok': False, 'error': 'Menü bulunamadı.'}, status=404)
    return JsonResponse({'ok': True})


@require_POST
def telegram_bot_studio_simulate(request):
    """
    Sohbet simülatörü için mesaj/buton basımını işler.
    - type='command' : komuta göre menü döner (örn. /start)
    - type='button'  : butona bağlı sürecin adını döner
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

    action_type = body.get('type')
    bot_id      = body.get('bot_id')

    if not bot_id:
        return JsonResponse({'ok': False, 'error': 'bot_id gerekli.'}, status=400)

    if action_type == 'command':
        command = str(body.get('command', '/start')).strip()
        menu = TelegramBotMenu.objects.filter(bot_id=bot_id, trigger_command=command, is_active=True).prefetch_related('buttons__sap_process').first()
        if not menu:
            return JsonResponse({'ok': True, 'response': {'type': 'text', 'text': f'Bu komut için kayıtlı bir menü bulunamadı: {command}'}})
        btns_by_row = {}
        for b in menu.buttons.all():
            btns_by_row.setdefault(b.row, []).append({'id': b.pk, 'label': b.label, 'sap_process_id': b.sap_process_id, 'sap_process_name': b.sap_process.name if b.sap_process else None})
        keyboard = [btns_by_row[r] for r in sorted(btns_by_row)]
        return JsonResponse({'ok': True, 'response': {'type': 'menu', 'text': menu.welcome_message, 'keyboard': keyboard, 'menu_id': menu.pk}})

    elif action_type == 'button':
        button_id = body.get('button_id')
        btn = TelegramBotButton.objects.select_related('sap_process').filter(pk=button_id, menu__bot_id=bot_id).first()
        if not btn:
            return JsonResponse({'ok': False, 'error': 'Buton bulunamadı.'}, status=404)
        if btn.sap_process:
            return JsonResponse({'ok': True, 'response': {
                'type': 'process_trigger',
                'text': f'✅ Süreç başlatılıyor: <b>{btn.sap_process.name}</b>',
                'process_id': btn.sap_process.pk,
                'process_name': btn.sap_process.name,
            }})
        else:
            return JsonResponse({'ok': True, 'response': {'type': 'text', 'text': '⚠️ Bu butona henüz bir süreç bağlanmamış.'}})

    return JsonResponse({'ok': False, 'error': 'Geçersiz type parametresi.'}, status=400)


# ─── Telegram Webhook + Yetkilendirme ─────────────────────────────────────────


@csrf_exempt
@require_POST
def telegram_bot_webhook(request, bot_id, secret):
    """Telegram'ın gönderdiği update'leri işler. URL: /tg/webhook/<bot_id>/<secret>/"""
    bot = TelegramBot.objects.filter(pk=bot_id, is_active=True).first()
    if not bot:
        return JsonResponse({'ok': False}, status=404)
    if not bot.webhook_secret or secret != bot.webhook_secret:
        return JsonResponse({'ok': False}, status=403)

    try:
        update = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False}, status=400)

    process_telegram_update(bot, update)
    return JsonResponse({'ok': True})



@require_POST
def telegram_bot_studio_bot_save(request):
    """Bot bazlı erişim ayarları (allowed_user_ids) kaydeder."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
    bot_id = body.get('bot_id')
    bot = TelegramBot.objects.filter(pk=bot_id).first()
    if not bot:
        return JsonResponse({'ok': False, 'error': 'Bot bulunamadı.'}, status=404)

    raw = str(body.get('allowed_user_ids', '') or '')
    parsed = sorted(_normalize_allowed_user_ids(raw))
    bot.allowed_user_ids = '\n'.join(str(x) for x in parsed)
    bot.save()
    return JsonResponse({'ok': True, 'allowed_user_ids': bot.allowed_user_ids, 'count': len(parsed)})


@require_POST
def telegram_bot_studio_set_webhook(request):
    """Bu bot için Telegram'a setWebhook çağrısı yapar.
    Body: { bot_id, base_url } - base_url örn 'https://example.com' (sondaki / olmadan).
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
    bot_id = body.get('bot_id')
    base_url = str(body.get('base_url') or '').strip().rstrip('/')
    if not base_url:
        return JsonResponse({'ok': False, 'error': 'base_url gerekli (örn https://alanim.com).'}, status=400)
    if not (base_url.startswith('https://') or base_url.startswith('http://')):
        return JsonResponse({'ok': False, 'error': 'base_url http(s):// ile başlamalı.'}, status=400)

    bot = TelegramBot.objects.filter(pk=bot_id).first()
    if not bot:
        return JsonResponse({'ok': False, 'error': 'Bot bulunamadı.'}, status=404)
    if not bot.webhook_secret:
        import secrets as _sec
        bot.webhook_secret = _sec.token_urlsafe(32)
        bot.save()

    webhook_url = f"{base_url}/tg/webhook/{bot.pk}/{bot.webhook_secret}/"
    token = bot.get_bot_token()
    ok, data = _telegram_api_call(token, 'setWebhook', {
        'url': webhook_url,
        'allowed_updates': ['message', 'edited_message', 'callback_query'],
        'drop_pending_updates': True,
    })
    if ok:
        bot.webhook_registered_url = webhook_url
        bot.save()
        return JsonResponse({'ok': True, 'webhook_url': webhook_url, 'telegram': data})
    return JsonResponse({'ok': False, 'error': data.get('description') or 'telegram_api_error', 'telegram': data}, status=502)


def telegram_bot_studio_webhook_info(request):
    """Telegram'dan getWebhookInfo döner (durum kontrolü)."""
    bot_id = request.GET.get('bot_id')
    bot = TelegramBot.objects.filter(pk=bot_id).first()
    if not bot:
        return JsonResponse({'ok': False, 'error': 'Bot bulunamadı.'}, status=404)
    token = bot.get_bot_token()
    ok, data = _telegram_api_call(token, 'getWebhookInfo', {})
    if ok:
        return JsonResponse({'ok': True, 'info': data.get('result') or {}, 'expected_url': bot.webhook_registered_url})
    return JsonResponse({'ok': False, 'error': data.get('description') or 'telegram_api_error'}, status=502)


@require_POST
def telegram_bot_studio_delete_webhook(request):
    """Telegram'da deleteWebhook çağrısı yapar."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
    bot = TelegramBot.objects.filter(pk=body.get('bot_id')).first()
    if not bot:
        return JsonResponse({'ok': False, 'error': 'Bot bulunamadı.'}, status=404)
    token = bot.get_bot_token()
    ok, data = _telegram_api_call(token, 'deleteWebhook', {'drop_pending_updates': True})
    if ok:
        bot.webhook_registered_url = ''
        bot.save()
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': data.get('description') or 'telegram_api_error'}, status=502)



