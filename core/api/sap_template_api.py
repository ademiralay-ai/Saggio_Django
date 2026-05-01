"""SAP scan page view + template/apply/run JSON endpoints.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..firebase_service import SAPTemplateService
from ..models import MailAccount, TelegramBot, TelegramGroup
from ..sap_service import SAPScanService
from ..services.notification_service import _notify_sap_event


def sap_scan(request):
	service = SAPScanService()
	sys_options = service.get_system_list()

	form_data = {
		'sys_id': request.POST.get('sys_id', (sys_options[0] if sys_options else '02-QA')),
		'client': request.POST.get('client', '300'),
		'lang': request.POST.get('lang', 'TR'),
		'user': request.POST.get('user', ''),
		'pwd': request.POST.get('pwd', ''),
		't_code': request.POST.get('t_code', 'ZFI0501N'),
		'root_id': request.POST.get('root_id', 'wnd[0]'),
		'extra_wait': request.POST.get('extra_wait', '0'),
		'loop_values': request.POST.get('loop_values', ''),
	}

	results = []
	error = ''
	total_count = 0
	with_id_count = 0
	editable_count = 0

	if request.method == 'POST':
		missing = [k for k in ('sys_id', 'client', 'user', 'pwd') if not form_data.get(k)]
		if missing:
			error = 'Sistem ID, Client, Kullanıcı ve Şifre alanları zorunludur.'
		else:
			try:
				extra_wait = float(form_data.get('extra_wait') or 0)
				extra_wait = max(0.0, min(5.0, extra_wait))
			except (TypeError, ValueError):
				extra_wait = 0.0

			ok, payload = service.scan_screen(
				sys_id=form_data['sys_id'],
				client=form_data['client'],
				lang=form_data['lang'],
				user=form_data['user'],
				pwd=form_data['pwd'],
				t_code=form_data['t_code'],
				root_id=form_data['root_id'],
				extra_wait=extra_wait,
			)

			if ok:
				results = payload
				for row in results:
					row['entries_json'] = json.dumps(row.get('entries', []), ensure_ascii=False)
				results.sort(key=lambda x: (x.get('level', 0), x.get('type', ''), x.get('id', '')))
				total_count = len(results)
				with_id_count = sum(1 for x in results if x.get('id'))
				editable_count = sum(1 for x in results if x.get('changeable'))
			else:
				error = payload

	return render(
		request,
		'core/sap_scan.html',
		{
			'page_title': 'SAP Derin Tarama',
			'page_subtitle': 'Baglanti bilgileri ile ekrani ac ve teknik ID listesi al',
			'form_data': form_data,
			'results': results,
			'error': error,
			'total_count': total_count,
			'with_id_count': with_id_count,
			'editable_count': editable_count,
			'sys_options': sys_options,
			'telegram_bots': TelegramBot.objects.filter(is_active=True).order_by('name'),
			'telegram_groups': TelegramGroup.objects.filter(is_active=True).order_by('name'),
			'mail_accounts': MailAccount.objects.filter(is_active=True).order_by('name'),
		},
	)

@require_POST
def sap_apply(request):
	"""Secili satirlari SAP ekranina uygula."""
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({"ok": False, "error": "Geçersiz istek verisi."}, status=400)

	conn    = body.get("connection", {})
	actions = body.get("actions", [])
	notification = body.get('notification', {})

	if not actions:
		return JsonResponse({"ok": False, "error": "Uygulanacak aksiyon yok."})

	service = SAPScanService()
	notify_start = _notify_sap_event(notification, 'start')
	ok, payload = service.apply_to_screen(
		sys_id=conn.get("sys_id", ""),
		client=conn.get("client", ""),
		user=conn.get("user", ""),
		pwd=conn.get("pwd", ""),
		lang=conn.get("lang", "TR"),
		t_code=conn.get("t_code", ""),
		root_id=conn.get("root_id", "wnd[0]"),
		extra_wait=conn.get("extra_wait", 0),
		actions=actions,
	)
	notify_end = _notify_sap_event(notification, 'end', payload if ok else [])

	if ok:
		return JsonResponse({"ok": True, "results": payload, 'notifications': {'start': notify_start, 'end': notify_end}})
	return JsonResponse({"ok": False, "error": payload})


@require_POST
def sap_run(request):
	"""Seçili satırları SAP ekranına uygula ve F8 ile çalıştır."""
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({"ok": False, "error": "Geçersiz istek verisi."}, status=400)

	conn = body.get("connection", {})
	actions = body.get("actions", [])
	notification = body.get('notification', {})

	service = SAPScanService()
	notify_start = _notify_sap_event(notification, 'start')
	ok, payload = service.apply_to_screen(
		sys_id=conn.get("sys_id", ""),
		client=conn.get("client", ""),
		user=conn.get("user", ""),
		pwd=conn.get("pwd", ""),
		lang=conn.get("lang", "TR"),
		t_code=conn.get("t_code", ""),
		root_id=conn.get("root_id", "wnd[0]"),
		extra_wait=conn.get("extra_wait", 0),
		actions=actions,
		execute_f8=True,
	)
	notify_end = _notify_sap_event(notification, 'end', payload if ok else [])

	if ok:
		return JsonResponse({"ok": True, "results": payload, 'notifications': {'start': notify_start, 'end': notify_end}})
	return JsonResponse({"ok": False, "error": payload})


def sap_template_list(request):
	"""Firebase'deki SAP şablon adlarını döndür."""
	names = SAPTemplateService.list_template_names()
	return JsonResponse({"ok": True, "names": names})


def sap_template_get(request):
	"""Seçili şablonu Firebase'den getir."""
	name = str(request.GET.get("name", "") or "").strip()
	if not name:
		return JsonResponse({"ok": False, "error": "Şablon adı gerekli."}, status=400)

	tpl = SAPTemplateService.get_template(name)
	if not tpl:
		return JsonResponse({"ok": False, "error": "Şablon bulunamadı."}, status=404)

	state = tpl.get("state", {}) if isinstance(tpl, dict) else {}
	return JsonResponse({"ok": True, "name": name, "state": state})


@require_POST
def sap_template_save(request):
	"""SAP şablonunu Firebase'e kaydet/güncelle."""
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({"ok": False, "error": "Geçersiz istek verisi."}, status=400)

	name = str(body.get("name", "") or "").strip()
	state = body.get("state", {})

	if not name:
		return JsonResponse({"ok": False, "error": "Şablon adı gerekli."}, status=400)

	result = SAPTemplateService.save_template(name, state)
	if not result.get('ok'):
		return JsonResponse({"ok": False, "error": result.get('error', 'Şablon kaydetme hatası.')}, status=500)

	return JsonResponse({
		"ok": True,
		"name": name,
		"storage": result.get('storage', 'unknown'),
		"reason": result.get('reason', ''),
	})


@require_POST
def sap_template_delete(request):
	"""SAP ÅŸablonunu Firebase/yerel depodan sil."""
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({"ok": False, "error": "Geçersiz istek verisi."}, status=400)

	name = str(body.get("name", "") or "").strip()
	if not name:
		return JsonResponse({"ok": False, "error": "Şablon adı gerekli."}, status=400)

	result = SAPTemplateService.delete_template(name)
	if not result.get('ok'):
		return JsonResponse({"ok": False, "error": result.get('error', 'Şablon silme hatası.')}, status=500)

	return JsonResponse({"ok": True, "name": name, "storage": result.get('storage', 'unknown'), "reason": result.get('reason', '')})


# ---------------------------------------------------------------------------
# SAP Süreç Builder
# ---------------------------------------------------------------------------
