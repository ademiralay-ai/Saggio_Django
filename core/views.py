from django.shortcuts import get_object_or_404, redirect, render
import json
import smtplib
import time
import ftplib
import socket
import os
import fnmatch
from email.mime.text import MIMEText
from datetime import datetime
from django.http import JsonResponse
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from django.views.decorators.http import require_POST
from .firebase_service import ContactConfigService, RobotService, ProcessService, QueueService, ReportService, ScheduleService, SAPTemplateService
from .forms import FTPAccountForm, MailAccountForm, TelegramBotForm, TelegramGroupForm
from .models import FTPAccount, MailAccount, TelegramBot, TelegramGroup, SapProcess, SapProcessStep
from .sap_service import SAPScanService

try:
	import paramiko
except Exception:
	paramiko = None

try:
	import tkinter as tk
except Exception:
	tk = None


def get_dashboard_stats():
	"""Fetch dashboard statistics from Firebase"""
	robots = RobotService.get_all_robots() or {}
	processes = ProcessService.get_all_processes() or {}
	
	total_robots = len(robots)
	online_robots = sum(1 for r in robots.values() if isinstance(r, dict) and r.get('status') == 'online')
	total_processes = len(processes)
	
	return {
		'total_robots': total_robots or 5,
		'online_robots': online_robots or 5,
		'total_processes': total_processes or 12,
		'success_rate': '98.2%',
	}


def dashboard(request):
	stats = get_dashboard_stats()
	robots_data = RobotService.get_all_robots() or {}
	processes_data = ProcessService.get_all_processes() or {}
	
	return render(
		request,
		'core/dashboard.html',
		{
			'page_title': 'Dashboard',
			'page_subtitle': 'Robot operasyon merkezi',
			'stats': stats,
			'robots': robots_data,
			'processes': processes_data,
		},
	)


def robots(request):
	robots_data = RobotService.get_all_robots() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Robotlar',
			'page_subtitle': 'Robot envanteri ve canli durum takibi',
			'section_type': 'robots',
			'data': robots_data,
		},
	)


def processes(request):
	processes_data = ProcessService.get_all_processes() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Surecler',
			'page_subtitle': 'Süreç performansı ve hata analizi',
			'section_type': 'processes',
			'data': processes_data,
		},
	)


def queues(request):
	queues_data = QueueService.get_all_queues() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Kuyruk Yonetimi',
			'page_subtitle': 'Is kuyruklari, onceliklendirme ve SLA takibi',
			'section_type': 'queues',
			'data': queues_data,
		},
	)


def scheduler(request):
	schedules_data = ScheduleService.get_all_schedules() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Scheduler',
			'page_subtitle': 'Planli gorevler ve zamanlama panosu',
			'section_type': 'scheduler',
			'data': schedules_data,
		},
	)


def reports(request):
	reports_data = ReportService.get_all_reports() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Raporlar',
			'page_subtitle': 'Operasyon raporlari ve KPI ozetleri',
			'section_type': 'reports',
			'data': reports_data,
		},
	)


def settings_page(request):
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Ayarlar',
			'page_subtitle': 'Sistem konfigrasyonlari ve entegrasyonlar',
			'section_type': 'settings',
		},
	)


def _send_telegram_group_test(group, payload=None):
	payload = payload or {}
	bot = group.default_bot
	if not bot or not bot.is_active:
		return False, 'Bu grup icin aktif varsayilan bot yok.'

	token = bot.get_bot_token()
	if not token:
		return False, 'Bot token cozulmedi veya bos.'

	custom_text = str(payload.get('test_message') or '').strip()
	text = custom_text or f"Saggio RPA test mesaji\nGrup: {group.name}\nBot: {bot.name}"
	data = {
		'chat_id': str(group.chat_id),
		'text': text,
	}
	if bot.default_parse_mode:
		data['parse_mode'] = bot.default_parse_mode

	body = urlencode(data).encode('utf-8')
	url = f'https://api.telegram.org/bot{token}/sendMessage'
	req = Request(url, data=body, method='POST')

	try:
		with urlopen(req, timeout=10) as resp:
			payload = json.loads(resp.read().decode('utf-8') or '{}')
			if payload.get('ok'):
				return True, 'Test mesaji gonderildi.'
			return False, payload.get('description', 'Telegram API hatası.')
	except HTTPError as e:
		return False, f'Telegram HTTP hatası: {e.code}'
	except URLError as e:
		return False, f'Telegram bağlantı hatası: {e.reason}'
	except Exception as e:
		return False, f'Telegram test hatası: {e}'


def _send_mail_test(account, payload=None):
	payload = payload or {}
	password = account.get_smtp_password()
	if not password:
		return False, 'SMTP şifresi çözülemedi veya boş.'

	from_display = account.from_name or account.name
	from_value = f'{from_display} <{account.email}>'
	to_value = str(payload.get('test_to') or '').strip() or account.email
	subject = str(payload.get('test_subject') or '').strip() or 'Saggio RPA - Test Maili'
	body = str(payload.get('test_body') or '').strip() or 'Bu e-posta Saggio RPA tarafindan test amacli gonderildi.'

	msg = MIMEText(body, 'plain', 'utf-8')
	msg['Subject'] = subject
	msg['From'] = from_value
	msg['To'] = to_value

	try:
		if account.use_ssl:
			server = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=15)
		else:
			server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=15)
			if account.use_tls:
				server.starttls()

		with server:
			server.login(account.smtp_username, password)
			server.sendmail(account.email, [to_value], msg.as_string())
		return True, f'Test maili gonderildi: {to_value}'
	except Exception as e:
		return False, f'SMTP test hatası: {e}'


def _send_ftp_test(account, payload=None):
	payload = payload or {}
	password = account.get_password()
	if not password:
		return False, 'FTP sifresi çözülemedi veya boş.'

	remote_path = str(payload.get('test_path') or '').strip() or account.remote_base_path or '.'
	protocol = str(account.protocol or 'sftp').lower()

	try:
		if protocol == 'sftp':
			if paramiko is None:
				return False, 'SFTP testi için paramiko kurulu değil.'
			transport = paramiko.Transport((account.host, int(account.port or 22)))
			transport.connect(username=account.username, password=password)
			sftp = paramiko.SFTPClient.from_transport(transport)
			sftp.listdir(remote_path)
			sftp.close()
			transport.close()
			return True, f'SFTP bağlantısı başarılı. Yol erişimi: {remote_path}'

		if protocol == 'ftps':
			ftp = ftplib.FTP_TLS()
			ftp.connect(account.host, int(account.port or 21), timeout=15)
			ftp.login(account.username, password)
			ftp.prot_p()
			ftp.cwd(remote_path)
			ftp.quit()
			return True, f'FTPS bağlantısı başarılı. Yol erişimi: {remote_path}'

		ftp = ftplib.FTP()
		ftp.connect(account.host, int(account.port or 21), timeout=15)
		ftp.login(account.username, password)
		ftp.cwd(remote_path)
		ftp.quit()
		return True, f'FTP bağlantısı başarılı. Yol erişimi: {remote_path}'
	except (socket.timeout, ConnectionRefusedError) as e:
		return False, f'FTP bağlantı hatası: {e}'
	except Exception as e:
		return False, f'FTP test hatası: {e}'


def _send_telegram_message(bot, chat_id, text):
	if not bot or not bot.is_active:
		return False, 'Telegram bot aktif degil veya secilmedi.'
	if not chat_id:
		return False, 'Telegram chat id secilmedi.'
	token = bot.get_bot_token()
	if not token:
		return False, 'Telegram token cozulmedi.'

	data = {'chat_id': str(chat_id), 'text': text}
	if bot.default_parse_mode:
		data['parse_mode'] = bot.default_parse_mode
	req = Request(
		f'https://api.telegram.org/bot{token}/sendMessage',
		data=urlencode(data).encode('utf-8'),
		method='POST',
	)
	try:
		with urlopen(req, timeout=10) as resp:
			payload = json.loads(resp.read().decode('utf-8') or '{}')
			if payload.get('ok'):
				return True, 'telegram_ok'
			return False, payload.get('description', 'telegram_api_error')
	except Exception as e:
		return False, str(e)


def _send_mail_message(account, to_value, subject, body):
	if not account or not account.is_active:
		return False, 'Mail hesabi aktif degil veya secilmedi.'
	password = account.get_smtp_password()
	if not password:
		return False, 'SMTP şifresi çözülemedi.'

	from_display = account.from_name or account.name
	from_value = f'{from_display} <{account.email}>'
	msg = MIMEText(body, 'plain', 'utf-8')
	msg['Subject'] = subject
	msg['From'] = from_value
	msg['To'] = to_value

	try:
		if account.use_ssl:
			server = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=15)
		else:
			server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=15)
			if account.use_tls:
				server.starttls()

		with server:
			server.login(account.smtp_username, password)
			server.sendmail(account.email, [to_value], msg.as_string())
		return True, 'mail_ok'
	except Exception as e:
		return False, str(e)


def _notify_sap_event(notification, phase, result_payload=None):
	notification = notification or {}
	notes = []
	stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

	tg_bot_id = notification.get('telegram_bot_id')
	tg_group_id = notification.get('telegram_group_id')
	mail_id = notification.get('mail_account_id')

	bot = TelegramBot.objects.filter(pk=tg_bot_id, is_active=True).first() if tg_bot_id else None
	group = TelegramGroup.objects.filter(pk=tg_group_id, is_active=True).first() if tg_group_id else None
	mail_account = MailAccount.objects.filter(pk=mail_id, is_active=True).first() if mail_id else None

	if bot and group:
		default_tg = f'SAP sureci {phase} ({stamp})'
		if phase == 'start':
			text = str(notification.get('telegram_start_message') or '').strip() or default_tg
		else:
			total = len(result_payload or [])
			ok_count = sum(1 for r in (result_payload or []) if r.get('ok'))
			err_count = max(0, total - ok_count)
			end_default = f'SAP süreci tamamlandı ({stamp}) | Başarılı: {ok_count}, Hatalı: {err_count}'
			text = str(notification.get('telegram_end_message') or '').strip() or end_default
		ok, msg = _send_telegram_message(bot, group.chat_id, text)
		notes.append({'channel': 'telegram', 'ok': ok, 'msg': msg})

	if mail_account:
		to_value = str(notification.get('mail_to') or '').strip() or mail_account.email
		subject = str(notification.get('mail_subject') or '').strip() or 'Saggio RPA SAP Bildirimi'
		if phase == 'start':
			body = str(notification.get('mail_start_message') or '').strip() or f'SAP sureci basladi. Zaman: {stamp}'
		else:
			total = len(result_payload or [])
			ok_count = sum(1 for r in (result_payload or []) if r.get('ok'))
			err_count = max(0, total - ok_count)
			body = str(notification.get('mail_end_message') or '').strip() or f'SAP süreci tamamlandı. Başarılı: {ok_count}, Hatalı: {err_count}. Zaman: {stamp}'
		ok, msg = _send_mail_message(mail_account, to_value, subject, body)
		notes.append({'channel': 'mail', 'ok': ok, 'msg': msg})

	return notes


def _manage_contact_entity(request, *, model, form_class, page_title, page_subtitle, success_message, test_handler=None, firebase_sync_handler=None, firebase_entity_name=None, current_key=''):
	edit_id = request.GET.get('edit')
	edit_instance = model.objects.filter(pk=edit_id).first() if edit_id else None
	create_form = form_class(prefix='create')
	edit_form = form_class(instance=edit_instance, prefix='edit') if edit_instance else None
	error_message = ''

	if request.method == 'POST':
		action = request.POST.get('action', '')
		if action == 'create':
			create_form = form_class(request.POST, prefix='create')
			if create_form.is_valid():
				obj = create_form.save()
				if firebase_sync_handler is not None:
					firebase_sync_handler(obj)
				return redirect(f'{request.path}?ok=create')
			error_message = 'Kayit olusturulamadi. Alanlari kontrol edin.'
		elif action == 'update':
			object_id = request.POST.get('object_id', '')
			instance = get_object_or_404(model, pk=object_id)
			edit_form = form_class(request.POST, instance=instance, prefix='edit')
			if edit_form.is_valid():
				obj = edit_form.save()
				if firebase_sync_handler is not None:
					firebase_sync_handler(obj)
				return redirect(f'{request.path}?ok=update')
			error_message = 'Kayıt güncellenemedi. Alanları kontrol edin.'
		elif action == 'delete':
			object_id = request.POST.get('object_id', '')
			instance = get_object_or_404(model, pk=object_id)
			if firebase_entity_name:
				ContactConfigService.delete_entity(firebase_entity_name, instance.id)
			instance.delete()
			return redirect(f'{request.path}?ok=delete')
		elif action == 'test' and test_handler is not None:
			object_id = request.POST.get('object_id', '')
			instance = get_object_or_404(model, pk=object_id)
			ok, msg = test_handler(instance, request.POST)
			state = 'ok' if ok else 'err'
			query = urlencode({'test': state, 'msg': msg or ''})
			return redirect(f'{request.path}?{query}')

	ok_action = request.GET.get('ok', '')
	status_message = ''
	test_state = request.GET.get('test', '')
	test_msg = request.GET.get('msg', '')
	if ok_action == 'create':
		status_message = f'{success_message} olusturuldu.'
	elif ok_action == 'update':
		status_message = f'{success_message} güncellendi.'
	elif ok_action == 'delete':
		status_message = f'{success_message} silindi.'
	elif test_state == 'ok':
		status_message = test_msg or 'Test islemi basarili.'
	elif test_state == 'err':
		error_message = test_msg or 'Test islemi basarisiz.'

	return render(
		request,
		'core/contact_crud.html',
		{
			'current': current_key,
			'page_title': page_title,
			'page_subtitle': page_subtitle,
			'entity_name': success_message,
			'entity_type': model._meta.model_name,
			'items': model.objects.all(),
			'create_form': create_form,
			'edit_form': edit_form,
			'edit_instance': edit_instance,
			'status_message': status_message,
			'error_message': error_message,
		},
	)


def telegram_bots_manage(request):
	return _manage_contact_entity(
		request,
		model=TelegramBot,
		form_class=TelegramBotForm,
		page_title='Telegram Botlari',
		page_subtitle='Bot token, parse mode ve aktiflik durumunu yonetin',
		success_message='Telegram botu',
		current_key='telegram_bots_manage',
		firebase_sync_handler=ContactConfigService.sync_telegram_bot,
		firebase_entity_name='telegram_bots',
	)


def telegram_groups_manage(request):
	return _manage_contact_entity(
		request,
		model=TelegramGroup,
		form_class=TelegramGroupForm,
		page_title='Telegram Gruplari',
		page_subtitle='Sahip ekipler, chat id ve varsayilan bot baglantisini yonetin',
		success_message='Telegram grubu',
		current_key='telegram_groups_manage',
		test_handler=_send_telegram_group_test,
		firebase_sync_handler=ContactConfigService.sync_telegram_group,
		firebase_entity_name='telegram_groups',
	)


def mail_accounts_manage(request):
	return _manage_contact_entity(
		request,
		model=MailAccount,
		form_class=MailAccountForm,
		page_title='Mail Hesaplari',
		page_subtitle='SMTP hesaplari ve gonderim ayarlarini yonetin',
		success_message='Mail hesabi',
		current_key='mail_accounts_manage',
		test_handler=_send_mail_test,
		firebase_sync_handler=ContactConfigService.sync_mail_account,
		firebase_entity_name='mail_accounts',
	)


def ftp_accounts_manage(request):
	return _manage_contact_entity(
		request,
		model=FTPAccount,
		form_class=FTPAccountForm,
		page_title='FTP Hesaplari',
		page_subtitle='FTP/SFTP baglanti profillerini yonetin',
		success_message='FTP hesabi',
		current_key='ftp_accounts_manage',
		test_handler=_send_ftp_test,
		firebase_sync_handler=ContactConfigService.sync_ftp_account,
		firebase_entity_name='ftp_accounts',
	)


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
	"""SAP şablonunu Firebase/yerel depodan sil."""
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

def sap_process_list(request):
	"""SAP süreçlerini listele; yeni süreç oluştur (POST)."""
	if request.method == 'POST':
		name = str(request.POST.get('name', '') or '').strip()
		desc = str(request.POST.get('description', '') or '').strip()
		if not name:
			return JsonResponse({'ok': False, 'error': 'Süreç adı boş olamaz.'}, status=400)
		if SapProcess.objects.filter(name=name).exists():
			return JsonResponse({'ok': False, 'error': 'Bu isimde bir süreç zaten var.'}, status=400)
		proc = SapProcess.objects.create(name=name, description=desc)
		return JsonResponse({'ok': True, 'id': proc.pk, 'name': proc.name})
	# GET: hem JSON hem HTML desteği
	if request.headers.get('Accept') == 'application/json' or request.GET.get('fmt') == 'json':
		processes = list(SapProcess.objects.values('id', 'name', 'description', 'updated_at').order_by('name'))
		return JsonResponse({'ok': True, 'processes': processes})
	return render(request, 'core/sap_process_list.html', {
		'current': 'sap_process',
		'page_title': 'SAP Süreç Tanımları',
		'page_subtitle': 'Otomasyon akışı tanımlayın',
	})


def sap_process_builder(request, process_id):
	"""Belirli bir sürecin adım builder sayfasını göster."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	steps = list(proc.steps.values('id', 'order', 'step_type', 'label', 'config').order_by('order'))
	template_names = SAPTemplateService.list_template_names()
	ftp_accounts = list(FTPAccount.objects.filter(is_active=True).values('id', 'name', 'protocol', 'host', 'port').order_by('name'))
	return render(request, 'core/sap_process_builder.html', {
		'current': 'sap_process',
		'page_title': f'Süreç: {proc.name}',
		'page_subtitle': 'Adım adım otomasyon akışı',
		'process': proc,
		'steps_json': json.dumps(steps, default=str),
		'template_names': template_names,
		'ftp_accounts_json': json.dumps(ftp_accounts, default=str),
	})


def sap_process_delete(request, process_id):
	"""Süreci sil."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	proc.delete()
	return JsonResponse({'ok': True})


@require_POST
def sap_process_step_save(request, process_id):
	"""Adımları toplu kaydet (tam liste — mevcut adımları sil, yenileri ekle)."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	steps_data = body.get('steps', [])
	if not isinstance(steps_data, list):
		return JsonResponse({'ok': False, 'error': 'steps bir liste olmalı.'}, status=400)

	valid_types = {c[0] for c in SapProcessStep.STEP_TYPE_CHOICES}
	proc.steps.all().delete()
	saved = []
	for i, s in enumerate(steps_data):
		step_type = str(s.get('step_type', '') or '').strip()
		if step_type not in valid_types:
			continue
		step = SapProcessStep.objects.create(
			process=proc,
			order=i,
			step_type=step_type,
			label=str(s.get('label', '') or '').strip()[:300],
			config=s.get('config', {}) if isinstance(s.get('config'), dict) else {},
		)
		saved.append({'id': step.pk, 'order': step.order, 'step_type': step.step_type})

	return JsonResponse({'ok': True, 'saved': len(saved), 'steps': saved})


@require_POST
def sap_process_rename(request, process_id):
	"""Süreç adını / açıklamasını güncelle."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
	name = str(body.get('name', '') or '').strip()
	desc = str(body.get('description', '') or '').strip()
	if not name:
		return JsonResponse({'ok': False, 'error': 'Süreç adı boş olamaz.'}, status=400)
	if SapProcess.objects.exclude(pk=process_id).filter(name=name).exists():
		return JsonResponse({'ok': False, 'error': 'Bu isimde başka bir süreç var.'}, status=400)
	proc.name = name
	proc.description = desc
	proc.save(update_fields=['name', 'description', 'updated_at'])
	return JsonResponse({'ok': True, 'name': proc.name})


@require_POST
def sap_process_runtime_settings_save(request, process_id):
	"""Süreç çalışma ayarlarını (overlay + popup + bildirim) güncelle."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	proc.ghost_overlay_enabled = bool(body.get('ghost_overlay_enabled', proc.ghost_overlay_enabled))
	proc.office_express_auto_close = bool(body.get('office_express_auto_close', proc.office_express_auto_close))
	proc.telegram_notifications_enabled = bool(body.get('telegram_notifications_enabled', proc.telegram_notifications_enabled))
	proc.telegram_voice_enabled = bool(body.get('telegram_voice_enabled', proc.telegram_voice_enabled))
	proc.mail_notifications_enabled = bool(body.get('mail_notifications_enabled', proc.mail_notifications_enabled))
	proc.save(update_fields=[
		'ghost_overlay_enabled',
		'office_express_auto_close',
		'telegram_notifications_enabled',
		'telegram_voice_enabled',
		'mail_notifications_enabled',
		'updated_at',
	])

	return JsonResponse({
		'ok': True,
		'ghost_overlay_enabled': proc.ghost_overlay_enabled,
		'office_express_auto_close': proc.office_express_auto_close,
		'telegram_notifications_enabled': proc.telegram_notifications_enabled,
		'telegram_voice_enabled': proc.telegram_voice_enabled,
		'mail_notifications_enabled': proc.mail_notifications_enabled,
	})


@require_POST
def sap_process_scan_buttons(request, process_id):
	"""Açık SAP ekranındaki butonları tarayıp process builder için döndürür."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	steps = _extract_runtime_steps(body, proc)
	if not steps:
		return JsonResponse({'ok': False, 'error': 'Önce en az bir adım tanımlayın.'}, status=400)

	conn, conn_err = _resolve_connection_from_steps(steps)
	if conn_err:
		return JsonResponse({'ok': False, 'error': conn_err}, status=400)

	service = SAPScanService()
	use_current_screen = bool(body.get('use_current_screen', True))
	t_code = '' if use_current_screen else str(conn.get('t_code', '') or '').strip()

	ok, payload = service.scan_screen(
		sys_id=conn.get('sys_id', ''),
		client=conn.get('client', ''),
		user=conn.get('user', ''),
		pwd=conn.get('pwd', ''),
		lang=conn.get('lang', 'TR'),
		t_code=t_code,
		root_id=conn.get('root_id', 'wnd[0]'),
		extra_wait=conn.get('extra_wait', 0),
	)
	if not ok:
		return JsonResponse({'ok': False, 'error': payload}, status=500)

	rows = payload if isinstance(payload, list) else []
	buttons = []
	seen_ids = set()
	for row in rows:
		if not isinstance(row, dict):
			continue
		raw_id = str(row.get('id', '') or '').strip()
		if not raw_id:
			continue
		norm_id = _normalize_session_element_id(raw_id)
		type_name = str(row.get('type', '') or '').strip()
		name = str(row.get('name', '') or '').strip()
		text = str(row.get('text', '') or '').strip()

		is_button = ('button' in type_name.casefold()) or ('/btn[' in norm_id.casefold())
		if not is_button:
			continue
		if norm_id in seen_ids:
			continue
		seen_ids.add(norm_id)
		buttons.append({
			'id': norm_id,
			'type': type_name,
			'name': name,
			'text': text,
			'label': f'{text or name or type_name or "Buton"} [{norm_id}]',
		})

	buttons.sort(key=lambda x: x['id'])
	return JsonResponse({'ok': True, 'buttons': buttons, 'count': len(buttons)})


@require_POST
def sap_process_scan_screens(request, process_id):
	"""Açık SAP oturumundaki ekran başlıklarını (wnd[*]) tarar."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	steps = _extract_runtime_steps(body, proc)
	if not steps:
		return JsonResponse({'ok': False, 'error': 'Önce en az bir adım tanımlayın.'}, status=400)

	conn, conn_err = _resolve_connection_from_steps(steps)
	if conn_err:
		return JsonResponse({'ok': False, 'error': conn_err}, status=400)

	service = SAPScanService()
	ok, payload = service.apply_to_screen(
		sys_id=conn.get('sys_id', ''),
		client=conn.get('client', ''),
		user=conn.get('user', ''),
		pwd=conn.get('pwd', ''),
		lang=conn.get('lang', 'TR'),
		t_code='',
		root_id=conn.get('root_id', 'wnd[0]'),
		extra_wait=conn.get('extra_wait', 0),
		actions=[],
		execute_f8=False,
	)
	if not ok:
		return JsonResponse({'ok': False, 'error': payload}, status=500)

	session = getattr(service, 'session', None)
	if session is None:
		return JsonResponse({'ok': False, 'error': 'Aktif SAP session bulunamadı.'}, status=500)

	windows = []
	seen = set()
	try:
		children = getattr(session, 'Children', None)
		count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		for idx in range(count):
			wnd = None
			try:
				wnd = children(idx)
			except Exception:
				try:
					wnd = children.Item(idx)
				except Exception:
					wnd = None
			if wnd is None:
				continue
			wid = str(getattr(wnd, 'Id', '') or '').strip()
			title = str(getattr(wnd, 'Text', '') or '').strip()
			if not title:
				title = wid or f'wnd[{idx}]'
			key = f'{wid}|{title}'.casefold()
			if key in seen:
				continue
			seen.add(key)
			windows.append({'id': _normalize_session_element_id(wid), 'title': title, 'label': f'{title} [{_normalize_session_element_id(wid)}]'})
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Ekran tarama hatası: {ex}'}, status=500)

	if not windows:
		try:
			current_title = str(service._get_window_title(session) or '').strip()
		except Exception:
			current_title = ''
		if current_title:
			windows.append({'id': 'wnd[0]', 'title': current_title, 'label': f'{current_title} [wnd[0]]'})

	return JsonResponse({'ok': True, 'screens': windows, 'count': len(windows)})


@require_POST
def sap_process_scan_grids(request, process_id):
	"""Açık SAP oturumundaki grid/tablo elementlerini tarar ve döndürür."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	steps = _extract_runtime_steps(body, proc)
	if not steps:
		return JsonResponse({'ok': False, 'error': 'Önce en az bir adım tanımlayın.'}, status=400)

	conn, conn_err = _resolve_connection_from_steps(steps)
	if conn_err:
		return JsonResponse({'ok': False, 'error': conn_err}, status=400)

	service = SAPScanService()
	ok, payload = service.scan_screen(
		sys_id=conn.get('sys_id', ''),
		client=conn.get('client', ''),
		user=conn.get('user', ''),
		pwd=conn.get('pwd', ''),
		lang=conn.get('lang', 'TR'),
		t_code='',
		root_id=conn.get('root_id', 'wnd[0]'),
		extra_wait=conn.get('extra_wait', 0),
	)
	if not ok:
		return JsonResponse({'ok': False, 'error': payload}, status=500)

	rows = payload if isinstance(payload, list) else []
	grids = []
	seen_ids = set()
	for row in rows:
		if not isinstance(row, dict):
			continue
		raw_id = str(row.get('id', '') or '').strip()
		if not raw_id:
			continue
		norm_id = _normalize_session_element_id(raw_id)
		type_name = str(row.get('type', '') or '').strip()
		name = str(row.get('name', '') or '').strip()
		text = str(row.get('text', '') or '').strip()
		lower_type = type_name.casefold()
		lower_id = norm_id.casefold()
		is_grid = (
			'grid' in lower_id or
			'grid' in lower_type or
			'table' in lower_type or
			'shell' in lower_type or
			'GuiTableControl'.casefold() in lower_type or
			'GuiShell'.casefold() in lower_type
		)
		if not is_grid:
			continue
		if norm_id in seen_ids:
			continue
		seen_ids.add(norm_id)
		window_hint = 'wnd[1]' if 'wnd[1]' in norm_id else 'wnd[0]'
		label_text = text or name or type_name or 'Grid'
		grids.append({
			'id': norm_id,
			'type': type_name,
			'name': name,
			'text': text,
			'window': window_hint,
			'label': f'{label_text} [{norm_id}]',
		})

	grids.sort(key=lambda x: x['id'])
	return JsonResponse({'ok': True, 'grids': grids, 'count': len(grids)})


import re as _re

def _normalize_session_element_id(element_id):
	"""'/app/con[0]/ses[0]/wnd[0]/...' → 'wnd[0]/...'  (veya zaten kısa ise olduğu gibi)."""
	eid = str(element_id or '').strip()
	# /app/con[N]/ses[N]/ önekini at
	eid = _re.sub(r'^/?app/con\[\d+\]/ses\[\d+\]/', '', eid)
	eid = eid.lstrip('/')
	return eid


def _calc_dynamic_date(key):
	"""JS calcDynamicDate'in Python karşılığı — SAP DD.MM.YYYY formatında tarih döner."""
	from datetime import date, timedelta
	import calendar
	today = date.today()
	y, m = today.year, today.month

	if key == 'today':
		d = today
	elif key == 'year_start':
		d = date(y, 1, 1)
	elif key == 'month_start':
		d = date(y, m, 1)
	elif key == 'year_end':
		d = date(y, 12, 31)
	elif key == 'month_end':
		d = date(y, m, calendar.monthrange(y, m)[1])
	elif key == 'prev_month_start':
		pm = m - 1 if m > 1 else 12
		py = y if m > 1 else y - 1
		d = date(py, pm, 1)
	elif key == 'prev_month_end':
		pm = m - 1 if m > 1 else 12
		py = y if m > 1 else y - 1
		d = date(py, pm, calendar.monthrange(py, pm)[1])
	elif key == 'month_5':
		d = date(y, m, 5)
	elif key == 'prev_year_start':
		d = date(y - 1, 1, 1)
	elif key == 'days_15':
		d = today - timedelta(days=15)
	elif key == 'days_30':
		d = today - timedelta(days=30)
	elif key == 'days_45':
		d = today - timedelta(days=45)
	elif key == 'days_60':
		d = today - timedelta(days=60)
	elif key == 'days_365':
		d = today - timedelta(days=365)
	else:
		return ''

	return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _parse_loop_values(raw):
	"""Virgül / noktalı virgül / satır sonu ile verilen döngü değerlerini normalize eder."""
	text = str(raw or '').strip()
	if not text:
		return []
	parts = _re.split(r'[\n,;]+', text)
	return [p.strip() for p in parts if str(p).strip()]


def _ensure_runtime_loop_state(runtime_state, state, cfg):
	"""runtime_state içine loop_values ve aktif loop_value bilgisini ilk kez yükler."""
	if not isinstance(runtime_state, dict):
		return
	if runtime_state.get('loop_values'):
		return

	form = state.get('form', {}) if isinstance(state, dict) and isinstance(state.get('form'), dict) else {}
	raw = (
		cfg.get('loop_values')
		or cfg.get('loop_values_override')
		or form.get('loop_values')
		or ''
	)
	values = _parse_loop_values(raw)
	if not values:
		return

	runtime_state['loop_values'] = values
	runtime_state['loop_index'] = 0
	runtime_state['loop_value'] = values[0]


def _close_office_express_popups(service):
	"""Açık SAP popup'larında Ofis Ekspres mesajı varsa otomatik kapatır."""
	closed = 0
	try:
		session = getattr(service, 'session', None)
		if session is None:
			return 0
		while True:
			children = getattr(session, 'Children', None)
			count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
			if count <= 1:
				break
			popup = session.findById('wnd[1]', False)
			if not popup:
				break
			title = str(getattr(popup, 'Text', '') or '').strip().casefold()
			if 'ofis ekspres' in title or 'office express' in title:
				popup.sendVKey(0)
				time.sleep(0.25)
				closed += 1
				continue
			break
	except Exception:
		return closed
	return closed


class _GhostOverlayWindow:
	"""Süreç çalışırken masaüstünde üstte kalan basit durum penceresi."""
	def __init__(self, enabled, process_name):
		self.enabled = bool(enabled)
		self.process_name = str(process_name or '').strip() or 'SAP Süreci'
		self.pc_name = os.environ.get('COMPUTERNAME') or socket.gethostname() or 'Bilinmeyen'
		self.root = None
		self.label = None
		self.logs = []
		self.current_step = ''
		if not self.enabled or tk is None:
			self.enabled = False
			return
		try:
			self.root = tk.Tk()
			self.root.overrideredirect(True)
			self.root.attributes('-topmost', True)
			self.root.attributes('-alpha', 0.86)
			self.root.config(bg='black')
			screen_w = self.root.winfo_screenwidth()
			x = max(20, screen_w - 500)
			self.root.geometry(f'470x180+{x}+40')
			self.label = tk.Label(
				self.root,
				text='',
				font=('Consolas', 10, 'bold'),
				fg='#58a6ff',
				bg='black',
				justify='left',
				anchor='nw',
				padx=10,
				pady=10,
			)
			self.label.pack(expand=True, fill='both')
			self._render()
		except Exception:
			self.enabled = False
			self.root = None
			self.label = None

	def _render(self):
		if not self.enabled or self.root is None or self.label is None:
			return
		try:
			stamp = datetime.now().strftime('%H:%M:%S')
			lines = [
				'SAGGIO HAYALET EKRAN',
				f'Süreç: {self.process_name}',
				f'PC: {self.pc_name}',
				f'Adım: {self.current_step or "-"}',
				'',
				'Log:',
			]
			lines.extend(self.logs[-5:] if self.logs else ['Hazır'])
			lines.append('')
			lines.append(f'Güncelleme: {stamp}')
			self.label.config(text='\n'.join(lines))
			self.root.update_idletasks()
			self.root.update()
		except Exception:
			pass

	def set_step(self, step_no, total_steps, step_name):
		if not self.enabled:
			return
		self.current_step = f'{step_no}/{total_steps} - {step_name}'
		self._render()

	def push_log(self, text):
		if not self.enabled:
			return
		msg = str(text or '').strip()
		if msg:
			self.logs.append(msg)
		self._render()

	def close(self):
		if self.root is None:
			return
		try:
			self.root.destroy()
		except Exception:
			pass
		self.root = None
		self.label = None

	def __del__(self):
		self.close()


def _build_actions_from_template_state_with_runtime(state, runtime_state=None):
	"""
	Şablon state'indeki rows'dan SAP apply_to_screen actions listesi oluşturur.
	runtime_state: dongu tipi alanlar için {"loop_value": "..."} gibi değerler içerebilir.
	"""
	if not isinstance(state, dict):
		return []
	rows = state.get('rows', {})
	if not isinstance(rows, dict):
		return []

	rt = runtime_state or {}
	actions = []

	for raw_id, row in rows.items():
		if not isinstance(row, dict):
			continue
		if not row.get('checked'):
			continue

		element_id  = _normalize_session_element_id(raw_id)
		if not element_id or not element_id.startswith('wnd['):
			continue

		action_type = str(row.get('action_type', '') or '').strip()
		if not action_type:
			continue

		if action_type == 'sabit':
			value = str(row.get('value_text', '') or '')
		elif action_type == 'dinamik':
			value = _calc_dynamic_date(str(row.get('value_date', '') or ''))
		elif action_type == 'selectbox':
			value = str(row.get('value_select', '') or '')
		elif action_type == 'dongu':
			value = str(rt.get('loop_value', '') or '')
		else:
			# radio, chk, secilecek, vb.
			value = str(row.get('value_text', '') or '')

		actions.append({'element_id': element_id, 'action_type': action_type, 'value': value})

	return actions


def _iter_children(node):
	try:
		children = getattr(node, 'Children', None)
		if children is None:
			return []
		try:
			count = int(children.Count)
		except Exception:
			count = 0
		result = []
		for idx in range(count):
			try:
				result.append(children(idx))
			except Exception:
				continue
		return result
	except Exception:
		return []


def find_alv_grid(root, candidate_id=None, grid_type='main'):
	search_id = _normalize_session_element_id(candidate_id) if candidate_id else ''
	preferred = None
	stack = [root] if root is not None else []
	while stack:
		node = stack.pop(0)
		try:
			node_id = str(getattr(node, 'Id', '') or getattr(node, 'ID', '') or '')
			node_type = str(getattr(node, 'Type', '') or '')
			lower_id = node_id.lower()
			lower_type = node_type.lower()
			if search_id and node_id == search_id:
				return node
			if 'grid' in lower_id or 'grid' in lower_type or 'shell' in lower_type:
				if grid_type == 'detail':
					if 'wnd[1]' in node_id or 'alv_ht' in lower_id:
						return node
					if preferred is None:
						preferred = node
				else:
					if 'wnd[0]' in node_id:
						return node
					if preferred is None:
						preferred = node
		except Exception:
			pass
		stack.extend(_iter_children(node))
	return preferred


def _get_grid_row_count(grid):
	for attr in ('rowCount', 'RowCount', 'visibleRowCount', 'VisibleRowCount'):
		try:
			value = int(getattr(grid, attr, 0) or 0)
			if value >= 0:
				return value
		except Exception:
			continue
	return 0


def _find_grid(service, grid_id='', timeout_sec=5, grid_type='main'):
	normalized_id = _normalize_session_element_id(grid_id)
	deadline = time.time() + max(1, timeout_sec)
	while time.time() < deadline:
		service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
		grid = None
		if normalized_id:
			grid = service._safe_find(service.session, normalized_id)
		if grid is None:
			grid = find_alv_grid(service.session, normalized_id or None, grid_type=grid_type)
		if grid is not None:
			return grid
		time.sleep(0.2)
	return None


def _collect_node_text(node, limit=40):
	parts = []
	stack = [node] if node is not None else []
	while stack and len(parts) < limit:
		current = stack.pop(0)
		for attr in ('Text', 'text', 'Tooltip', 'DefaultTooltip'):
			try:
				value = str(getattr(current, attr, '') or '').strip()
			except Exception:
				value = ''
			if value and value not in parts:
				parts.append(value)
		stack.extend(_iter_children(current))
	return ' | '.join(parts)


def _safe_send_popup_mail(cfg, mail_enabled=True):
	if not mail_enabled:
		return 'Mail gönderimi süreç ayarında kapalı.'
	if not bool(cfg.get('send_mail_on_match')):
		return None
	mail_to = str(cfg.get('mail_to', '') or '').strip()
	account_id = cfg.get('mail_account_id')
	if not mail_to or not account_id:
		return 'Mail atlandi: hesap veya alici eksik.'
	account = MailAccount.objects.filter(pk=account_id, is_active=True).first()
	if not account:
		return f'Mail atlandi: hesap bulunamadi (id={account_id}).'
	try:
		msg = MIMEText(str(cfg.get('mail_body', '') or ''), _charset='utf-8')
		msg['Subject'] = str(cfg.get('mail_subject', '') or 'SAP popup bildirimi')
		msg['From'] = account.email
		msg['To'] = mail_to
		if account.use_ssl:
			server = smtplib.SMTP_SSL(account.smtp_host, int(account.smtp_port or 465), timeout=20)
		else:
			server = smtplib.SMTP(account.smtp_host, int(account.smtp_port or 587), timeout=20)
		try:
			server.ehlo()
			if account.use_tls and not account.use_ssl:
				server.starttls()
				server.ehlo()
			server.login(account.smtp_username, account.get_smtp_password())
			server.sendmail(account.email, [mail_to], msg.as_string())
		finally:
			server.quit()
		return f'Mail gonderildi: {mail_to}'
	except Exception as ex:
		return f'Mail gonderim hatasi: {ex}'


def _extract_runtime_steps(body, proc):
	"""İstekte gelen steps varsa onu, yoksa DB steps'i kullan."""
	steps_data = body.get('steps')
	if isinstance(steps_data, list):
		clean = []
		for i, s in enumerate(steps_data):
			if not isinstance(s, dict):
				continue
			clean.append({
				'order': i,
				'step_type': str(s.get('step_type', '') or '').strip(),
				'label': str(s.get('label', '') or '').strip(),
				'config': s.get('config', {}) if isinstance(s.get('config'), dict) else {},
			})
		return clean

	return list(proc.steps.values('order', 'step_type', 'label', 'config').order_by('order'))


def _resolve_connection_from_steps(steps):
	"""İlk uygun sap_fill adımındaki şablondan connection/form bilgisini al."""
	for step in steps:
		step_type = str(step.get('step_type', '') or '').strip()
		if step_type != SapProcessStep.TYPE_SAP_FILL:
			continue
		cfg = step.get('config', {}) if isinstance(step.get('config'), dict) else {}
		tpl_name = str(cfg.get('template_name', '') or '').strip()
		if not tpl_name:
			continue
		tpl = SAPTemplateService.get_template(tpl_name)
		if not isinstance(tpl, dict):
			continue
		state = tpl.get('state', {}) if isinstance(tpl.get('state'), dict) else {}
		form = state.get('form', {}) if isinstance(state.get('form'), dict) else {}
		conn = {
			'sys_id': str(form.get('sys_id', '') or '').strip(),
			'client': str(form.get('client', '') or '').strip(),
			'user': str(form.get('user', '') or '').strip(),
			'pwd': str(form.get('pwd', '') or '').strip(),
			'lang': str(form.get('lang', 'TR') or 'TR').strip(),
			't_code': str(form.get('t_code', '') or '').strip(),
			'root_id': str(form.get('root_id', 'wnd[0]') or 'wnd[0]').strip(),
			'extra_wait': form.get('extra_wait', 0),
			'template_name': tpl_name,
		}
		if conn['sys_id'] and conn['client'] and conn['user'] and conn['pwd']:
			return conn, None
		return None, f'Şablon bağlantı bilgileri eksik: {tpl_name}'

	return None, 'Bağlantı bilgisi çözümlemek için en az bir geçerli Şablon adımı gerekli.'


def _ftp_list_files(account, remote_path='.', file_pattern='*'):
	remote_path = str(remote_path or '.').strip() or '.'
	file_pattern = str(file_pattern or '*').strip() or '*'
	items = []

	if account.protocol == 'sftp':
		if paramiko is None:
			raise RuntimeError('SFTP için paramiko kurulu değil.')
		transport = paramiko.Transport((account.host, int(account.port or 22)))
		try:
			transport.connect(username=account.username, password=account.get_password())
			sftp = paramiko.SFTPClient.from_transport(transport)
			for attr in sftp.listdir_attr(remote_path):
				name = attr.filename
				if fnmatch.fnmatch(name, file_pattern):
					items.append(name)
			sftp.close()
		finally:
			transport.close()
		return items

	if account.protocol == 'ftps':
		ftp = ftplib.FTP_TLS()
		ftp.connect(account.host, int(account.port or 21), timeout=20)
		ftp.login(account.username, account.get_password())
		ftp.prot_p()
		ftp.cwd(remote_path)
		try:
			items = [n for n in ftp.nlst() if fnmatch.fnmatch(os.path.basename(n), file_pattern)]
		finally:
			ftp.quit()
		return items

	ftp = ftplib.FTP()
	ftp.connect(account.host, int(account.port or 21), timeout=20)
	ftp.login(account.username, account.get_password())
	ftp.cwd(remote_path)
	try:
		items = [n for n in ftp.nlst() if fnmatch.fnmatch(os.path.basename(n), file_pattern)]
	finally:
		ftp.quit()
	return items


def _ftp_download(account, remote_path, local_path, file_pattern='*', limit=0):
	remote_path = str(remote_path or '.').strip() or '.'
	local_path = str(local_path or '').strip()
	if not local_path:
		raise RuntimeError('local_path zorunlu.')
	os.makedirs(local_path, exist_ok=True)

	files = _ftp_list_files(account, remote_path=remote_path, file_pattern=file_pattern)
	if limit and limit > 0:
		files = files[:limit]

	downloaded = []
	if account.protocol == 'sftp':
		if paramiko is None:
			raise RuntimeError('SFTP için paramiko kurulu değil.')
		transport = paramiko.Transport((account.host, int(account.port or 22)))
		try:
			transport.connect(username=account.username, password=account.get_password())
			sftp = paramiko.SFTPClient.from_transport(transport)
			for name in files:
				remote_file = f"{remote_path.rstrip('/')}/{os.path.basename(name)}"
				local_file = os.path.join(local_path, os.path.basename(name))
				sftp.get(remote_file, local_file)
				downloaded.append(local_file)
			sftp.close()
		finally:
			transport.close()
		return downloaded

	if account.protocol == 'ftps':
		ftp = ftplib.FTP_TLS()
		ftp.connect(account.host, int(account.port or 21), timeout=20)
		ftp.login(account.username, account.get_password())
		ftp.prot_p()
		ftp.cwd(remote_path)
		try:
			for name in files:
				base = os.path.basename(name)
				local_file = os.path.join(local_path, base)
				with open(local_file, 'wb') as fp:
					ftp.retrbinary(f'RETR {base}', fp.write)
				downloaded.append(local_file)
		finally:
			ftp.quit()
		return downloaded

	ftp = ftplib.FTP()
	ftp.connect(account.host, int(account.port or 21), timeout=20)
	ftp.login(account.username, account.get_password())
	ftp.cwd(remote_path)
	try:
		for name in files:
			base = os.path.basename(name)
			local_file = os.path.join(local_path, base)
			with open(local_file, 'wb') as fp:
				ftp.retrbinary(f'RETR {base}', fp.write)
			downloaded.append(local_file)
	finally:
		ftp.quit()
	return downloaded


def _ftp_upload(account, local_file, remote_path):
	local_file = str(local_file or '').strip()
	remote_path = str(remote_path or '.').strip() or '.'
	if not local_file:
		raise RuntimeError('local_file zorunlu.')
	if not os.path.isfile(local_file):
		raise RuntimeError(f'Yerel dosya bulunamadı: {local_file}')
	base = os.path.basename(local_file)

	if account.protocol == 'sftp':
		if paramiko is None:
			raise RuntimeError('SFTP için paramiko kurulu değil.')
		transport = paramiko.Transport((account.host, int(account.port or 22)))
		try:
			transport.connect(username=account.username, password=account.get_password())
			sftp = paramiko.SFTPClient.from_transport(transport)
			remote_file = f"{remote_path.rstrip('/')}/{base}"
			sftp.put(local_file, remote_file)
			sftp.close()
		finally:
			transport.close()
		return remote_file

	if account.protocol == 'ftps':
		ftp = ftplib.FTP_TLS()
		ftp.connect(account.host, int(account.port or 21), timeout=20)
		ftp.login(account.username, account.get_password())
		ftp.prot_p()
		ftp.cwd(remote_path)
		try:
			with open(local_file, 'rb') as fp:
				ftp.storbinary(f'STOR {base}', fp)
		finally:
			ftp.quit()
		return f"{remote_path.rstrip('/')}/{base}"

	ftp = ftplib.FTP()
	ftp.connect(account.host, int(account.port or 21), timeout=20)
	ftp.login(account.username, account.get_password())
	ftp.cwd(remote_path)
	try:
		with open(local_file, 'rb') as fp:
			ftp.storbinary(f'STOR {base}', fp)
	finally:
		ftp.quit()
	return f"{remote_path.rstrip('/')}/{base}"


@require_POST
def sap_process_run_preview(request, process_id):
	"""Süreci (veya belirtilen adıma kadar) gerçek SAP oturumunda çalıştır."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	overlay = _GhostOverlayWindow(enabled=proc.ghost_overlay_enabled, process_name=proc.name)
	overlay.push_log('Süreç başlatıldı')
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		overlay.close()
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	steps = _extract_runtime_steps(body, proc)
	if not steps:
		overlay.close()
		return JsonResponse({'ok': False, 'error': 'Çalıştırılacak adım yok.'}, status=400)

	conn, conn_err = _resolve_connection_from_steps(steps)
	if conn_err:
		overlay.close()
		return JsonResponse({'ok': False, 'error': conn_err}, status=400)

	try:
		upto_index = int(body.get('upto_index', len(steps) - 1))
	except (TypeError, ValueError):
		upto_index = len(steps) - 1
	if upto_index < 0:
		upto_index = 0
	if upto_index > len(steps) - 1:
		upto_index = len(steps) - 1

	service = SAPScanService()
	logs = []
	runtime_state = {}

	def _ensure_session_ready():
		ok, payload = service.apply_to_screen(
			sys_id=conn.get('sys_id', ''),
			client=conn.get('client', ''),
			user=conn.get('user', ''),
			pwd=conn.get('pwd', ''),
			lang=conn.get('lang', 'TR'),
			t_code='',
			root_id=conn.get('root_id', 'wnd[0]'),
			extra_wait=conn.get('extra_wait', 0),
			actions=[],
			execute_f8=False,
		)
		return ok, payload

	i = 0
	iteration_count = 0
	max_iterations = max(100, len(steps) * 20)
	while i < len(steps) and i <= upto_index:
		overlay.set_step(i + 1, len(steps), str(steps[i].get('label') or steps[i].get('step_type') or 'Adım'))
		if proc.office_express_auto_close:
			closed_before = _close_office_express_popups(service)
			if closed_before > 0:
				msg = f'Ofis Ekspres popup kapatıldı (adım öncesi): {closed_before}'
				logs.append({'step': i + 1, 'type': 'office_popup', 'label': 'Office Popup', 'ok': True, 'msg': msg})
				overlay.push_log(msg)
		if iteration_count >= max_iterations:
			overlay.close()
			return JsonResponse({'ok': False, 'error': 'Süreç maksimum iterasyon sınırına ulaştı.', 'logs': logs, 'failed_at': i}, status=500)
		iteration_count += 1
		step = steps[i]
		next_i = i + 1

		step_type = str(step.get('step_type', '') or '').strip()
		label = str(step.get('label', '') or '').strip()
		cfg = step.get('config', {}) if isinstance(step.get('config'), dict) else {}
		step_name = label or step_type
		continue_on_error = bool(cfg.get('continue_on_error'))

		try:
			if step_type == SapProcessStep.TYPE_SAP_FILL:
				tpl_name = str(cfg.get('template_name', '') or '').strip()
				if not tpl_name:
					return JsonResponse({'ok': False, 'error': f'{i + 1}. adımda şablon adı boş.', 'logs': logs, 'failed_at': i}, status=400)
				tpl = SAPTemplateService.get_template(tpl_name)
				if not isinstance(tpl, dict):
					return JsonResponse({'ok': False, 'error': f'Şablon bulunamadı: {tpl_name}', 'logs': logs, 'failed_at': i}, status=404)

				state = tpl.get('state', {}) if isinstance(tpl.get('state'), dict) else {}
				_ensure_runtime_loop_state(runtime_state, state, cfg)
				actions = _build_actions_from_template_state_with_runtime(state, runtime_state=runtime_state)
				form = state.get('form', {}) if isinstance(state.get('form'), dict) else {}
				t_code = str(cfg.get('t_code_override', '') or form.get('t_code', '') or conn.get('t_code', '') or '').strip()

				ok, payload = service.apply_to_screen(
					sys_id=conn.get('sys_id', ''),
					client=conn.get('client', ''),
					user=conn.get('user', ''),
					pwd=conn.get('pwd', ''),
					lang=conn.get('lang', 'TR'),
					t_code=t_code,
					root_id=conn.get('root_id', 'wnd[0]'),
					extra_wait=conn.get('extra_wait', 0),
					actions=actions,
					execute_f8=False,
				)
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				loop_msg = ''
				if runtime_state.get('loop_values'):
					current_loop = str(runtime_state.get('loop_value', '') or '')
					loop_idx = int(runtime_state.get('loop_index', 0) or 0) + 1
					loop_total = len(runtime_state.get('loop_values') or [])
					loop_msg = f' | döngü: {loop_idx}/{loop_total} ({current_loop})'
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Şablon uygulandı ({tpl_name}), aksiyon: {len(actions)}{loop_msg}'})

			elif step_type == SapProcessStep.TYPE_SAP_RUN:
				key = str(cfg.get('key', 'F8') or 'F8').strip()
				if key.upper() == 'F8':
					ok, payload = service.apply_to_screen(
						sys_id=conn.get('sys_id', ''),
						client=conn.get('client', ''),
						user=conn.get('user', ''),
						pwd=conn.get('pwd', ''),
						lang=conn.get('lang', 'TR'),
						t_code='',
						root_id=conn.get('root_id', 'wnd[0]'),
						extra_wait=conn.get('extra_wait', 0),
						actions=[],
						execute_f8=True,
					)
					if not ok:
						return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'F8 çalıştırıldı'})
				else:
					ok, payload = _ensure_session_ready()
					if not ok:
						return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
					vkey_map = {'ENTER': 0, 'F5': 5, 'F6': 6, 'F7': 7, 'F8': 8, 'ESCAPE': 12, 'ESC': 12}
					vk = vkey_map.get(key.upper())
					if vk is None:
						return JsonResponse({'ok': False, 'error': f'Desteklenmeyen tuş: {key}', 'logs': logs, 'failed_at': i}, status=400)
					service._wait_until_idle(service.session, timeout_sec=15)
					service.session.findById('wnd[0]').sendVKey(vk)
					service._wait_until_idle(service.session, timeout_sec=30)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{key} gönderildi'})

				delay_after_ms = int(cfg.get('delay_after_ms') or 0)
				if delay_after_ms > 0:
					time.sleep(min(delay_after_ms / 1000.0, 60.0))

			elif step_type == SapProcessStep.TYPE_SAP_PRESS_BUTTON:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				button_id = _normalize_session_element_id(cfg.get('button_id', ''))
				wait_timeout_sec = max(1, min(int(cfg.get('wait_timeout_sec') or 25), 60))
				button = service._wait_for_element(service.session, button_id, timeout_sec=wait_timeout_sec)
				if not button:
					return JsonResponse({'ok': False, 'error': f'Buton bulunamadı: {button_id}', 'logs': logs, 'failed_at': i}, status=404)
				button.press()
				service._wait_until_idle(service.session, timeout_sec=min(wait_timeout_sec, 30))
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Butona basıldı: {button_id}'})

			elif step_type == SapProcessStep.TYPE_SAP_SELECT_ROW:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				grid_id = str(cfg.get('grid_id', '') or '').strip()
				wait_timeout_sec = max(1, min(int(cfg.get('wait_timeout_sec') or 25), 60))
				grid = _find_grid(service, grid_id=grid_id, timeout_sec=wait_timeout_sec, grid_type='detail' if 'wnd[1]' in grid_id else 'main')
				if not grid:
					return JsonResponse({'ok': False, 'error': f'Grid bulunamadı: {grid_id}', 'logs': logs, 'failed_at': i}, status=404)
				try:
					row_index = max(0, int(cfg.get('row_index') or 1) - 1)
				except (TypeError, ValueError):
					row_index = 0
				grid.currentCellRow = row_index
				grid.selectedRows = str(row_index)
				service._wait_until_idle(service.session, timeout_sec=5)
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Grid satırı seçildi: {row_index + 1}'})

			elif step_type == SapProcessStep.TYPE_SAP_POPUP_DECIDE:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				popup_root_id = _normalize_session_element_id(cfg.get('popup_root_id', 'wnd[1]') or 'wnd[1]')
				popup = service._wait_for_element(service.session, popup_root_id, timeout_sec=max(1, min(int(cfg.get('timeout_sec') or 5), 30)))
				if not popup:
					if bool(cfg.get('fail_if_not_found')):
						return JsonResponse({'ok': False, 'error': 'Beklenen popup bulunamadı.', 'logs': logs, 'failed_at': i}, status=404)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Popup bulunamadı, adım atlandı'})
					i = next_i
					continue
				title = str(getattr(popup, 'Text', '') or '').strip()
				popup_text = _collect_node_text(popup)
				title_contains = str(cfg.get('popup_title_contains', '') or '').strip().casefold()
				text_contains = str(cfg.get('popup_text_contains', '') or '').strip().casefold()
				matched = True
				if title_contains and title_contains not in title.casefold():
					matched = False
				if text_contains and text_contains not in popup_text.casefold():
					matched = False
				if not matched:
					if bool(cfg.get('fail_if_not_match')):
						return JsonResponse({'ok': False, 'error': f'Popup eşleşmedi. Başlık: {title} | Metin: {popup_text}', 'logs': logs, 'failed_at': i}, status=400)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Popup geldi ama eşleşmedi. Başlık: {title}'})
					i = next_i
					continue
				action = str(cfg.get('popup_action', '') or '').strip().casefold()
				if action == 'close_escape':
					popup.sendVKey(12)
				elif action == 'close_enter':
					popup.sendVKey(0)
				elif action == 'press_button_id':
					button_id = _normalize_session_element_id(cfg.get('popup_button_id', ''))
					button = service._wait_for_element(service.session, button_id, timeout_sec=5)
					if not button:
						return JsonResponse({'ok': False, 'error': f'Popup butonu bulunamadı: {button_id}', 'logs': logs, 'failed_at': i}, status=404)
					button.press()
				service._wait_until_idle(service.session, timeout_sec=10)
				mail_msg = _safe_send_popup_mail(cfg, mail_enabled=proc.mail_notifications_enabled)
				log_msg = f'Popup işlendi. Başlık: {title}'
				if mail_msg:
					log_msg = f'{log_msg} | {mail_msg}'
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': log_msg})

			elif step_type == SapProcessStep.TYPE_SAP_WAIT:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

				timeout_sec = max(1, min(int(cfg.get('timeout_sec') or 60), 600))
				poll_ms = max(200, min(int(cfg.get('poll_ms') or 1000), 10000))
				screen_title = str(cfg.get('screen_title', '') or '').strip().casefold()

				if not screen_title:
					service._wait_until_idle(service.session, timeout_sec=min(timeout_sec, 30))
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Ekran hazır (idle) olarak algılandı'})
				else:
					deadline = time.time() + timeout_sec
					found = False
					while time.time() < deadline:
						service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
						title = service._get_window_title(service.session).casefold()
						if screen_title in title:
							found = True
							break
						time.sleep(poll_ms / 1000.0)
					if not found:
						timeout_action = str(cfg.get('on_timeout_action', 'fail') or 'fail').strip().casefold()
						if timeout_action == 'next_step':
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, sonraki adıma geçildi: {cfg.get("screen_title", "")}'})
						elif timeout_action == 'goto_step':
							try:
								target_step_no = int(cfg.get('timeout_target_step') or 1)
							except (TypeError, ValueError):
								target_step_no = 1
							target_step_no = max(1, min(target_step_no, len(steps)))
							next_i = target_step_no - 1
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, {target_step_no}. adıma dönüldü: {cfg.get("screen_title", "")}'})
						elif timeout_action == 'loop_next':
							loop_idx = None
							for k in range(i + 1, len(steps)):
								st = str(steps[k].get('step_type', '') or '').strip()
								if st == SapProcessStep.TYPE_LOOP_NEXT:
									loop_idx = k
									break
							if loop_idx is not None:
								next_i = loop_idx
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, döngüde sonraki elemana geçildi ({loop_idx + 1}. adım): {cfg.get("screen_title", "")}'})
							else:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, loop_next adımı bulunamadı; sonraki adıma geçildi: {cfg.get("screen_title", "")}'})
						else:
							return JsonResponse({'ok': False, 'error': f'Beklenen ekran başlığı zaman aşımına uğradı: {cfg.get("screen_title", "")}', 'logs': logs, 'failed_at': i}, status=408)
					else:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Ekran geldi: {cfg.get("screen_title", "")}'})

			elif step_type == SapProcessStep.TYPE_SAP_ACTION:
				raw_actions = cfg.get('actions', []) if isinstance(cfg.get('actions'), list) else []
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

				for a in raw_actions:
					if not isinstance(a, dict):
						continue
					a_type = str(a.get('type', '') or '').strip()
					a_value = str(a.get('value', '') or '').strip()

					if a_type == 'grid_select_row':
						try:
							grid = find_alv_grid(service.session, None, grid_type="main")
							if grid:
								if a_value.lower() == 'current':
									# User'ın SAP'ta tıkladığı satırı al
									row_idx = grid.currentCellRow
								else:
									row_idx = int(a_value or 0)
								grid.currentCellRow = row_idx
								grid.selectedRows = str(row_idx)
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Grid satırı seçildi: {row_idx}'})
							else:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': 'Grid bulunamadı'})
						except Exception as ge:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Grid seçim hatası: {ge}'})

					elif a_type == 'click_button' and a_value:
						try:
							btn = service.session.findById(a_value)
							if btn:
								btn.press()
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Buton tıklandı: {a_value}'})
							else:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Buton bulunamadı: {a_value}'})
						except Exception as be:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Buton tıklama hatası: {be}'})

					elif a_type == 'wait_ms':
						try:
							wait_ms = int(a_value or '0')
						except ValueError:
							wait_ms = 0
						if wait_ms > 0:
							time.sleep(min(wait_ms / 1000.0, 60.0))

					elif a_type in ('key_press', 'popup_close'):
						vkey_map = {'ENTER': 0, 'F5': 5, 'F6': 6, 'F7': 7, 'F8': 8, 'ESCAPE': 12, 'ESC': 12}
						key_name = a_value or ('Escape' if a_type == 'popup_close' else 'Enter')
						vk = vkey_map.get(key_name.upper(), 0)
						service._wait_until_idle(service.session, timeout_sec=10)
						service.session.findById('wnd[0]').sendVKey(vk)
						service._wait_until_idle(service.session, timeout_sec=20)

					elif a_type == 'select_variant' and ':' in a_value:
						element_id, key_val = a_value.split(':', 1)
						ok, payload = service.apply_to_screen(
							sys_id=conn.get('sys_id', ''),
							client=conn.get('client', ''),
							user=conn.get('user', ''),
							pwd=conn.get('pwd', ''),
							lang=conn.get('lang', 'TR'),
							t_code='',
							root_id=conn.get('root_id', 'wnd[0]'),
							extra_wait=conn.get('extra_wait', 0),
							actions=[{'element_id': element_id.strip(), 'action_type': 'selectbox', 'value': key_val.strip()}],
							execute_f8=False,
						)
						if not ok:
							return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Aksiyon adımı uygulandı ({len(raw_actions)} işlem)'})

			elif step_type == SapProcessStep.TYPE_FTP_LIST:
				account_id = cfg.get('ftp_account_id')
				account = FTPAccount.objects.filter(pk=account_id, is_active=True).first()
				if not account:
					msg = f'Geçerli FTP hesabı bulunamadı (id={account_id}).'
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
						continue
					return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
				remote_path = str(cfg.get('remote_path', '') or account.remote_base_path or '.').strip()
				file_pattern = str(cfg.get('file_pattern', '*') or '*').strip()
				items = _ftp_list_files(account, remote_path=remote_path, file_pattern=file_pattern)
				preview = ', '.join(items[:6])
				if len(items) > 6:
					preview += ' ...'
				if not preview:
					preview = 'liste boş'
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{len(items)} dosya listelendi ({account.name}) | {preview}'})

			elif step_type == SapProcessStep.TYPE_FTP_DOWNLOAD:
				account_id = cfg.get('ftp_account_id')
				account = FTPAccount.objects.filter(pk=account_id, is_active=True).first()
				if not account:
					msg = f'Geçerli FTP hesabı bulunamadı (id={account_id}).'
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
						continue
					return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
				remote_path = str(cfg.get('remote_path', '') or account.remote_base_path or '.').strip()
				local_path = str(cfg.get('local_path', '') or '').strip()
				file_pattern = str(cfg.get('file_pattern', '*') or '*').strip()
				try:
					limit = int(cfg.get('limit') or 0)
				except (TypeError, ValueError):
					limit = 0
				downloaded = _ftp_download(account, remote_path=remote_path, local_path=local_path, file_pattern=file_pattern, limit=limit)
				files_preview = ', '.join([os.path.basename(x) for x in downloaded[:6]])
				if len(downloaded) > 6:
					files_preview += ' ...'
				if not files_preview:
					files_preview = 'indirilen dosya yok'
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{len(downloaded)} dosya indirildi ({account.name}) | {files_preview}'})

			elif step_type == SapProcessStep.TYPE_FTP_UPLOAD:
				account_id = cfg.get('ftp_account_id')
				account = FTPAccount.objects.filter(pk=account_id, is_active=True).first()
				if not account:
					msg = f'Geçerli FTP hesabı bulunamadı (id={account_id}).'
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
						continue
					return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
				local_file = str(cfg.get('local_file', '') or '').strip()
				remote_path = str(cfg.get('remote_path', '') or account.remote_base_path or '.').strip()
				uploaded = _ftp_upload(account, local_file=local_file, remote_path=remote_path)
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Dosya yüklendi ({account.name}): {uploaded}'})

			elif step_type == SapProcessStep.TYPE_SAP_CLOSE:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				try:
					service.session.findById('wnd[0]').close()
				except Exception:
					pass
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'SAP kapatma komutu gönderildi'})

			elif step_type == SapProcessStep.TYPE_LOOP_NEXT:
				loop_values = runtime_state.get('loop_values') or []
				if not loop_values:
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Döngü değeri tanımlı değil, adım atlandı'})
				else:
					current_idx = int(runtime_state.get('loop_index', 0) or 0)
					next_loop_idx = current_idx + 1
					if next_loop_idx >= len(loop_values):
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Döngü değerleri tamamlandı'})
					else:
						runtime_state['loop_index'] = next_loop_idx
						runtime_state['loop_value'] = loop_values[next_loop_idx]

						# Varsayılan davranış: bir önceki sap_fill adımına dön ve yeni loop değeriyle devam et.
						target_idx = None
						for back_i in range(i - 1, -1, -1):
							st = str(steps[back_i].get('step_type', '') or '').strip()
							if st == SapProcessStep.TYPE_SAP_FILL:
								target_idx = back_i
								break
						if target_idx is None:
							target_idx = 0
						next_i = target_idx
						logs.append({
							'step': i + 1,
							'type': step_type,
							'label': step_name,
							'ok': True,
							'msg': f'Döngüde sonraki kayıt: {next_loop_idx + 1}/{len(loop_values)} ({runtime_state.get("loop_value", "")}) | adıma dön: {target_idx + 1}'
						})

			elif step_type == SapProcessStep.TYPE_SAP_SCAN:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				
				try:
					# Detail grid'i bul
					detail_grid = find_alv_grid(service.session, None, grid_type="detail")
					if not detail_grid:
						return JsonResponse({'ok': False, 'error': 'Detail grid bulunamadı', 'logs': logs, 'failed_at': i}, status=500)
					
					# Yöntem deteksiyonu (detail grid ID'sine bakarak)
					d_id = str(getattr(detail_grid, 'ID', '') or '')
					yontem = 1
					if 'ALV_HT_FR/' in d_id:
						yontem = 2
					elif 'ALV_HT_FRUG/' in d_id:
						yontem = 3
					
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Detail grid bulundu (Yöntem: {yontem}, Grid ID: {d_id[:50]})'})
					
					# Yöntem 3 için malzeme kodları ve ürün grubu kodları oku
					if yontem == 3:
						try:
							# Column headers'ı al
							d_col_headers = str(getattr(detail_grid, 'colHeaders', '') or '')
							d_col_names = d_col_headers.split('\t')
							
							# Satır sayısı al
							d_row_count = int(getattr(detail_grid, 'visibleRowCount', 0) or 0)
							
							malzeme_kodlari = []
							logs_detail = []
							
							for dr in range(d_row_count):
								try:
									# Scroll işlemi: satırı görüntülemek için grid scroll'ını ayarla
									vis_count = int(getattr(detail_grid, 'visibleRowCount', 0) or 0)
									first_vis = int(getattr(detail_grid, 'firstVisibleRow', 0) or 0)
									if dr < first_vis or dr >= first_vis + vis_count:
										detail_grid.firstVisibleRow = max(0, dr - 1)
										service._wait_until_idle(service.session, timeout_sec=3)
									
									# Column 2 ve 3'ten değerleri al
									if len(d_col_names) > 3:
										v1 = str(detail_grid.getCellValue(dr, d_col_names[2])).strip() if d_col_names[2] else ''
										v2 = str(detail_grid.getCellValue(dr, d_col_names[3])).strip() if len(d_col_names) > 3 and d_col_names[3] else ''
										if v1:
											malzeme_kodlari.append({'malzeme': v1.lstrip('0'), 'urun_grubu': v2.lstrip('0')})
											logs_detail.append(f'Satır {dr}: malzeme={v1} urungrup={v2}')
								except Exception as row_err:
									logs_detail.append(f'Satır {dr} okuma hatası: {row_err}')
							
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{len(malzeme_kodlari)} malzeme kodu okudu', 'detail': logs_detail[:10]})
						except Exception as detail_err:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Detail grid okuma hatası: {detail_err}'})
					else:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Yöntem {yontem} için scan henüz implement edilmedi'})
				
				except Exception as scan_err:
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Scan hatası: {scan_err}'})

			else:
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Bilinmeyen step_type: {step_type}'})

		except Exception as ex:
			if continue_on_error and step_type in (SapProcessStep.TYPE_FTP_LIST, SapProcessStep.TYPE_FTP_DOWNLOAD, SapProcessStep.TYPE_FTP_UPLOAD):
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {ex}'})
				overlay.push_log(f'Hata (devam): {ex}')
				continue
			overlay.close()
			return JsonResponse({'ok': False, 'error': str(ex), 'logs': logs, 'failed_at': i}, status=500)

		if proc.office_express_auto_close:
			closed_after = _close_office_express_popups(service)
			if closed_after > 0:
				msg = f'Ofis Ekspres popup kapatıldı (adım sonrası): {closed_after}'
				logs.append({'step': i + 1, 'type': 'office_popup', 'label': 'Office Popup', 'ok': True, 'msg': msg})
				overlay.push_log(msg)

		if logs:
			overlay.push_log(logs[-1].get('msg', 'Adım tamamlandı'))

		i = next_i
	overlay.push_log('Süreç tamamlandı')
	overlay.close()
	return JsonResponse({'ok': True, 'logs': logs, 'ran_until': upto_index, 'connection_template': conn.get('template_name', '')})
