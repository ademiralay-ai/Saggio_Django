from django.shortcuts import get_object_or_404, redirect, render
import json
import smtplib
import time
import ftplib
import socket
import os
import re
import shutil
import subprocess
import fnmatch
import tempfile
import uuid
import threading
from email.mime.text import MIMEText
from datetime import datetime
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import ensure_csrf_cookie
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


_PROCESS_RUNTIME = {}
_PROCESS_RUNTIME_LOCK = threading.Lock()


def _runtime_init(process_id, process_name, total_steps):
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		_PROCESS_RUNTIME[pid] = {
			'process_id': pid,
			'process_name': str(process_name or ''),
			'total_steps': int(total_steps or 0),
			'current_step': 0,
			'step_name': '',
			'paused': False,
			'stop_requested': False,
			'running': True,
			'updated_at': datetime.now().isoformat(),
			'logs': [],
		}


def _runtime_get(process_id):
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		state = _PROCESS_RUNTIME.get(pid)
		if not state:
			return None
		return {
			'process_id': state.get('process_id'),
			'process_name': state.get('process_name', ''),
			'total_steps': int(state.get('total_steps', 0) or 0),
			'current_step': int(state.get('current_step', 0) or 0),
			'step_name': state.get('step_name', ''),
			'paused': bool(state.get('paused')),
			'stop_requested': bool(state.get('stop_requested')),
			'running': bool(state.get('running')),
			'updated_at': state.get('updated_at'),
			'logs': list(state.get('logs') or []),
		}


def _runtime_touch(process_id):
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		state = _PROCESS_RUNTIME.get(pid)
		if not state:
			return
		state['updated_at'] = datetime.now().isoformat()


def _runtime_set_controls(process_id, *, paused=None, stop_requested=None):
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		state = _PROCESS_RUNTIME.get(pid)
		if not state:
			return
		if paused is not None:
			state['paused'] = bool(paused)
		if stop_requested is not None:
			state['stop_requested'] = bool(stop_requested)
		state['updated_at'] = datetime.now().isoformat()


def _runtime_set_step(process_id, step_no, total_steps, step_name):
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		state = _PROCESS_RUNTIME.get(pid)
		if not state:
			return
		state['current_step'] = int(step_no or 0)
		state['total_steps'] = int(total_steps or state.get('total_steps', 0) or 0)
		state['step_name'] = str(step_name or '')
		state['updated_at'] = datetime.now().isoformat()


def _runtime_push_log(process_id, text):
	msg = str(text or '').strip()
	if not msg:
		return
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		state = _PROCESS_RUNTIME.get(pid)
		if not state:
			return
		logs = state.setdefault('logs', [])
		logs.append(msg)
		if len(logs) > 120:
			del logs[:-120]
		state['updated_at'] = datetime.now().isoformat()


def _runtime_finish(process_id):
	pid = int(process_id)
	with _PROCESS_RUNTIME_LOCK:
		state = _PROCESS_RUNTIME.get(pid)
		if not state:
			return
		state['running'] = False
		state['updated_at'] = datetime.now().isoformat()


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

	base_data = {'chat_id': str(chat_id), 'text': text}
	data = dict(base_data)
	if bot.default_parse_mode:
		data['parse_mode'] = bot.default_parse_mode

	def _call_send_message(payload):
		req = Request(
			f'https://api.telegram.org/bot{token}/sendMessage',
			data=urlencode(payload).encode('utf-8'),
			method='POST',
		)
		with urlopen(req, timeout=10) as resp:
			return json.loads(resp.read().decode('utf-8') or '{}')

	try:
		payload = _call_send_message(data)
		if payload.get('ok'):
			return True, 'telegram_ok'
		desc = str(payload.get('description', 'telegram_api_error') or '')
		# parse_mode kaynaklı hata olursa sade metin ile yeniden dene.
		if data.get('parse_mode') and ('parse entities' in desc.casefold() or 'can\'t parse' in desc.casefold()):
			payload2 = _call_send_message(base_data)
			if payload2.get('ok'):
				return True, 'telegram_ok_plain'
			return False, payload2.get('description', 'telegram_api_error')
		return False, desc or 'telegram_api_error'
	except Exception as e:
		return False, str(e)


def _send_telegram_voice_message(bot, chat_id, text):
	"""Windows SAPI ile ses üretip Telegram'a gerçek voice note olarak gönderir."""
	if not bot or not bot.is_active:
		return False, 'Telegram bot aktif degil veya secilmedi.'
	if not chat_id:
		return False, 'Telegram chat id secilmedi.'
	token = bot.get_bot_token()
	if not token:
		return False, 'Telegram token cozulmedi.'

	voice_text = str(text or '').strip()
	if not voice_text:
		return False, 'Sesli mesaj metni boş.'

	tmp_wav_path = None
	tmp_ogg_path = None
	tmp_mp3_path = None
	co_initialized = False
	errors = []

	def _send_voice_file(path_value, filename_value, content_type_value):
		with open(path_value, 'rb') as fp:
			file_data = fp.read()

		boundary = f'----SaggioBoundary{uuid.uuid4().hex}'
		parts = []

		def _add_text(name, value):
			parts.append(f'--{boundary}'.encode('utf-8'))
			parts.append(f'Content-Disposition: form-data; name="{name}"'.encode('utf-8'))
			parts.append(b'')
			parts.append(str(value).encode('utf-8'))

		_add_text('chat_id', str(chat_id))
		_add_text('caption', 'Saggio RPA sesli bildirim')

		parts.append(f'--{boundary}'.encode('utf-8'))
		parts.append(f'Content-Disposition: form-data; name="voice"; filename="{filename_value}"'.encode('utf-8'))
		parts.append(f'Content-Type: {content_type_value}'.encode('utf-8'))
		parts.append(b'')
		parts.append(file_data)

		parts.append(f'--{boundary}--'.encode('utf-8'))
		parts.append(b'')
		body = b'\r\n'.join(parts)

		req = Request(
			f'https://api.telegram.org/bot{token}/sendVoice',
			data=body,
			method='POST',
			headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
		)
		with urlopen(req, timeout=20) as resp:
			payload = json.loads(resp.read().decode('utf-8') or '{}')
			if payload.get('ok'):
				return True, 'telegram_voice_ok'
			return False, payload.get('description', 'telegram_voice_api_error')

	def _send_audio_file(path_value, filename_value, content_type_value):
		with open(path_value, 'rb') as fp:
			file_data = fp.read()

		boundary = f'----SaggioBoundary{uuid.uuid4().hex}'
		parts = []

		def _add_text(name, value):
			parts.append(f'--{boundary}'.encode('utf-8'))
			parts.append(f'Content-Disposition: form-data; name="{name}"'.encode('utf-8'))
			parts.append(b'')
			parts.append(str(value).encode('utf-8'))

		_add_text('chat_id', str(chat_id))
		_add_text('caption', 'Saggio RPA sesli bildirim')

		parts.append(f'--{boundary}'.encode('utf-8'))
		parts.append(f'Content-Disposition: form-data; name="audio"; filename="{filename_value}"'.encode('utf-8'))
		parts.append(f'Content-Type: {content_type_value}'.encode('utf-8'))
		parts.append(b'')
		parts.append(file_data)

		parts.append(f'--{boundary}--'.encode('utf-8'))
		parts.append(b'')
		body = b'\r\n'.join(parts)

		req = Request(
			f'https://api.telegram.org/bot{token}/sendAudio',
			data=body,
			method='POST',
			headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
		)
		with urlopen(req, timeout=20) as resp:
			payload = json.loads(resp.read().decode('utf-8') or '{}')
			if payload.get('ok'):
				return True, 'telegram_audio_ok'
			return False, payload.get('description', 'telegram_audio_api_error')
	try:
		try:
			import pythoncom
			import win32com.client

			pythoncom.CoInitialize()
			co_initialized = True
			with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmpf:
				tmp_wav_path = tmpf.name
			with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmpf:
				tmp_ogg_path = tmpf.name

			voice = win32com.client.Dispatch('SAPI.SpVoice')
			# Türkçe sese öncelik ver (kuruluysa)
			try:
				voices = voice.GetVoices()
				selected_voice = None
				count = int(getattr(voices, 'Count', 0) or 0)
				for i in range(count):
					try:
						candidate = voices.Item(i)
						desc = str(candidate.GetDescription() or '').casefold()
						lang = str(candidate.GetAttribute('Language') or '').casefold()
						if 'turkish' in desc or 'türk' in desc or '041f' in lang:
							selected_voice = candidate
							break
					except Exception:
						continue
				if selected_voice is not None:
					voice.Voice = selected_voice
			except Exception:
				pass
			try:
				voice.Rate = -1
			except Exception:
				pass
			stream = win32com.client.Dispatch('SAPI.SpFileStream')
			# 3 = SSFMCreateForWrite
			stream.Open(tmp_wav_path, 3, False)
			voice.AudioOutputStream = stream
			voice.Speak(voice_text)
			stream.Close()

			ffmpeg_path = shutil.which('ffmpeg')
			if ffmpeg_path:
				convert_cmd = [
					ffmpeg_path,
					'-y',
					'-i',
					tmp_wav_path,
					'-c:a',
					'libopus',
					'-b:a',
					'24k',
					tmp_ogg_path,
				]
				convert_result = subprocess.run(convert_cmd, capture_output=True, text=True)
				if convert_result.returncode == 0 and os.path.exists(tmp_ogg_path) and os.path.getsize(tmp_ogg_path) > 0:
					ok, detail = _send_voice_file(tmp_ogg_path, 'saggio_notification.ogg', 'audio/ogg')
					if ok:
						return True, detail
					errors.append(f'ogg_send_failed: {detail}')
				else:
					err = (convert_result.stderr or convert_result.stdout or 'ffmpeg convert hatasi').strip()
					errors.append(f'ffmpeg_convert_failed: {err}')
			else:
				errors.append('ffmpeg_not_found')
		except Exception as sapi_ex:
			errors.append(f'sapi_flow_failed: {sapi_ex}')

		# SAPI/ffmpeg başarısız olursa gTTS ile MP3 üretip sendVoice dene.
		try:
			from gtts import gTTS
			with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmpf:
				tmp_mp3_path = tmpf.name
			clean_text = voice_text.replace('*', '').replace('_', '')
			gTTS(text=clean_text, lang='tr', slow=False).save(tmp_mp3_path)
			ok, detail = _send_voice_file(tmp_mp3_path, 'saggio_notification.mp3', 'audio/mpeg')
			if ok:
				return True, detail
			errors.append(f'gtts_send_failed: {detail}')
			# Voice endpoint reddederse normal audio olarak düşür.
			a_ok, a_msg = _send_audio_file(tmp_mp3_path, 'saggio_notification.mp3', 'audio/mpeg')
			if a_ok:
				return True, a_msg
			errors.append(f'gtts_audio_fallback_failed: {a_msg}')
		except Exception as ge:
			errors.append(f'gtts_fallback_failed: {ge}')

		return False, 'Voice note gonderilemedi: ' + ' | '.join(errors)
	except Exception as e:
		return False, str(e)
	finally:
		if co_initialized:
			try:
				pythoncom.CoUninitialize()
			except Exception:
				pass
		if tmp_wav_path and os.path.exists(tmp_wav_path):
			try:
				os.remove(tmp_wav_path)
			except Exception:
				pass
		if tmp_ogg_path and os.path.exists(tmp_ogg_path):
			try:
				os.remove(tmp_ogg_path)
			except Exception:
				pass
		if tmp_mp3_path and os.path.exists(tmp_mp3_path):
			try:
				os.remove(tmp_mp3_path)
			except Exception:
				pass


@require_POST
def _sap_process_scan_popups_impl(request, process_id):
	"""Açık SAP popup pencerelerini ve içeriklerindeki butonları tarar."""
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

	popups = []
	seen = set()
	try:
		children = getattr(session, 'Children', None)
		count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		for idx in range(1, count):
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

			popup_id = _normalize_session_element_id(str(getattr(wnd, 'Id', '') or '').strip())
			title = str(getattr(wnd, 'Text', '') or '').strip()
			legacy_text = _collect_popup_text_legacy(session, popup_id or 'wnd[1]', limit=220)
			message_text = _collect_popup_message_text(session, popup_id or 'wnd[1]', limit=120)
			deep_text = _collect_node_text(wnd, limit=220)
			text = ' | '.join([p for p in [legacy_text, message_text, deep_text] if p])
			key = f'{popup_id}|{title}|{text}'.casefold()
			if key in seen:
				continue
			seen.add(key)

			buttons = []
			btn_seen = set()
			stack = [wnd]
			while stack:
				node = stack.pop(0)
				try:
					node_type = str(getattr(node, 'Type', '') or '').casefold()
					node_id = _normalize_session_element_id(str(getattr(node, 'Id', '') or '').strip())
					if ('button' in node_type or '/btn' in node_id.casefold()) and node_id not in btn_seen:
						btn_seen.add(node_id)
						btn_text = str(getattr(node, 'Text', '') or '').strip()
						btn_name = str(getattr(node, 'Name', '') or '').strip()
						btn_label = btn_text or btn_name or node_id or 'Popup Butonu'
						buttons.append({
							'id': node_id,
							'text': btn_text,
							'name': btn_name,
							'label': f'{btn_label} [{node_id}]',
						})
				except Exception:
					pass
				stack.extend(_iter_children(node))

			popups.append({
				'id': popup_id,
				'title': title,
				'text': text,
				'buttons': buttons,
				'label': f'{title or popup_id or "Popup"} [{popup_id}]',
			})
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Popup tarama hatası: {ex}'}, status=500)

	return JsonResponse({'ok': True, 'popups': popups, 'count': len(popups)})


@require_POST
def sap_process_scan_popups(request, process_id):
	"""Açık SAP popup pencerelerini ve içeriklerindeki butonları tarar (hata güvenli JSON)."""
	try:
		return _sap_process_scan_popups_impl(request, process_id)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Popup tarama beklenmeyen hata: {ex}'}, status=500)


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
	tg_voice_enabled = bool(notification.get('telegram_voice_enabled'))
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
		if tg_voice_enabled:
			v_ok, v_msg = _send_telegram_voice_message(bot, group.chat_id, text)
			notes.append({'channel': 'telegram_voice', 'ok': v_ok, 'msg': v_msg})

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


@ensure_csrf_cookie
def sap_process_builder(request, process_id):
	"""Belirli bir sürecin adım builder sayfasını göster."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	steps = list(proc.steps.values('id', 'order', 'step_type', 'label', 'config').order_by('order'))
	template_names = SAPTemplateService.list_template_names()
	ftp_accounts = list(FTPAccount.objects.filter(is_active=True).values('id', 'name', 'protocol', 'host', 'port').order_by('name'))
	other_processes = list(SapProcess.objects.exclude(pk=proc.pk).values('id', 'name').order_by('name'))
	return render(request, 'core/sap_process_builder.html', {
		'current': 'sap_process',
		'page_title': f'Süreç: {proc.name}',
		'page_subtitle': 'Adım adım otomasyon akışı',
		'process': proc,
		'steps_json': json.dumps(steps, default=str),
		'template_names': template_names,
		'ftp_accounts_json': json.dumps(ftp_accounts, default=str),
		'processes_json': json.dumps(other_processes, default=str),
	})


def sap_process_delete(request, process_id):
	"""Süreci sil."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	proc.delete()
	return JsonResponse({'ok': True})


@require_POST
def sap_process_step_save(request, process_id):
	"""Adımları toplu kaydet (tam liste — mevcut adımları sil, yenileri ekle)."""
	try:
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
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Adımlar kaydedilemedi: {ex}'}, status=500)


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
def sap_process_runtime_control(request, process_id):
	"""Canlı süreç kontrolü: duraklat/devam et/durdur."""
	get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	action = str(body.get('action', '') or '').strip().casefold()
	state = _runtime_get(process_id)
	if state is None:
		return JsonResponse({'ok': False, 'error': 'Bu süreç için aktif runtime bulunamadı.'}, status=404)

	if action == 'pause_toggle':
		_runtime_set_controls(process_id, paused=not bool(state.get('paused')), stop_requested=bool(state.get('stop_requested')))
	elif action == 'pause':
		_runtime_set_controls(process_id, paused=True)
	elif action == 'resume':
		_runtime_set_controls(process_id, paused=False)
	elif action == 'stop':
		_runtime_set_controls(process_id, paused=False, stop_requested=True)
	else:
		return JsonResponse({'ok': False, 'error': f'Desteklenmeyen aksiyon: {action}'}, status=400)

	return JsonResponse({'ok': True, 'state': _runtime_get(process_id)})


def sap_process_runtime_status(request, process_id):
	"""Canlı süreç durumunu ve hayalet log akışını döndürür."""
	get_object_or_404(SapProcess, pk=process_id)
	state = _runtime_get(process_id)
	if state is None:
		return JsonResponse({'ok': True, 'state': {'running': False, 'paused': False, 'stop_requested': False, 'current_step': 0, 'total_steps': 0, 'step_name': '', 'logs': []}})
	return JsonResponse({'ok': True, 'state': state})


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

	# apply_to_screen ile bağlan — session'a erişerek tüm pencereleri (wnd[0]+wnd[1]+...) tarayabilelim
	ok, payload = service.apply_to_screen(
		sys_id=conn.get('sys_id', ''),
		client=conn.get('client', ''),
		user=conn.get('user', ''),
		pwd=conn.get('pwd', ''),
		lang=conn.get('lang', 'TR'),
		t_code=t_code,
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

	buttons = []
	seen_ids = set()

	def _collect_buttons(node):
		stack = [node] if node is not None else []
		while stack:
			current = stack.pop(0)
			try:
				node_id = str(getattr(current, 'Id', '') or '').strip()
				node_type = str(getattr(current, 'Type', '') or '').strip()
				norm_id = _normalize_session_element_id(node_id)
				lower_type = node_type.casefold()
				is_button = ('button' in lower_type) or ('/btn[' in norm_id.casefold())
				if is_button and norm_id and norm_id not in seen_ids:
					name = str(getattr(current, 'Name', '') or '').strip()
					text = str(getattr(current, 'Text', '') or '').strip()
					seen_ids.add(norm_id)
					buttons.append({
						'id': norm_id,
						'type': node_type,
						'name': name,
						'text': text,
						'label': f'{text or name or node_type or "Buton"} [{norm_id}]',
					})
			except Exception:
				pass
			stack.extend(_iter_children(current))

	try:
		children = getattr(session, 'Children', None)
		wnd_count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		if wnd_count == 0:
			_collect_buttons(session)
		else:
			for idx in range(wnd_count):
				wnd = None
				try:
					wnd = children(idx)
				except Exception:
					try:
						wnd = children.Item(idx)
					except Exception:
						wnd = None
				if wnd is not None:
					_collect_buttons(wnd)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Buton tarama hatası: {ex}'}, status=500)

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
	# apply_to_screen ile bağlan (scan_screens ile aynı yöntem) — session nesnesine erişmek için
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

	grids = []
	seen_ids = set()

	def _collect_grids(node):
		"""node altındaki tüm GuiTableControl ve GuiShell grid elementlerini recursive toplar."""
		stack = [node] if node is not None else []
		while stack:
			current = stack.pop(0)
			try:
				node_id = str(getattr(current, 'Id', '') or '').strip()
				node_type = str(getattr(current, 'Type', '') or '').strip()
				norm_id = _normalize_session_element_id(node_id)
				lower_type = node_type.casefold()
				lower_id = norm_id.casefold()
				last_segment = lower_id.split('/')[-1] if lower_id else ''
				# Yalnızca gerçek grid kontrolü dönsün; hücre (txt..., lbl...) ID'lerini dışarıda bırak.
				is_table_control = ('tablecontrol' in lower_type) or last_segment.startswith('tbl')
				is_shell_grid = ('shell' in lower_type) and (
					last_segment.startswith('shell') or 'grid' in lower_id or 'shellcont' in lower_id
				)
				is_grid = is_table_control or is_shell_grid
				if is_grid and norm_id and norm_id not in seen_ids:
					name = str(getattr(current, 'Name', '') or '').strip()
					text = str(getattr(current, 'Text', '') or '').strip()
					window_hint = 'wnd[1]' if 'wnd[1]' in norm_id else 'wnd[0]'
					label_text = text or name or node_type or 'Grid'
					seen_ids.add(norm_id)
					grids.append({
						'id': norm_id,
						'type': node_type,
						'name': name,
						'text': text,
						'window': window_hint,
						'label': f'{label_text} [{norm_id}]',
					})
			except Exception:
				pass
			stack.extend(_iter_children(current))

	# Tüm SAP pencerelerini (wnd[0], wnd[1], ...) tara
	try:
		children = getattr(session, 'Children', None)
		wnd_count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		if wnd_count == 0:
			_collect_grids(session)
		else:
			for idx in range(wnd_count):
				wnd = None
				try:
					wnd = children(idx)
				except Exception:
					try:
						wnd = children.Item(idx)
					except Exception:
						wnd = None
				if wnd is not None:
					_collect_grids(wnd)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Grid tarama hatası: {ex}'}, status=500)

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
	def __init__(self, enabled, process_name, process_id=None):
		self.enabled = bool(enabled)
		self.process_name = str(process_name or '').strip() or 'SAP Süreci'
		self.process_id = int(process_id) if process_id is not None else None
		self.pc_name = os.environ.get('COMPUTERNAME') or socket.gethostname() or 'Bilinmeyen'
		self.root = None
		self.label = None
		self.log_text = None
		self.log_scroll = None
		self.pause_btn = None
		self.stop_btn = None
		self.logs = []
		self.current_step = ''
		self.paused = False
		self.stop_requested = False
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
			self.root.geometry(f'470x220+{x}+40')
			self.root.minsize(470, 220)
			self.root.maxsize(470, 220)
			self.root.resizable(False, False)

			btn_wrap = tk.Frame(self.root, bg='black')
			btn_wrap.pack(fill='x', padx=10, pady=(10, 6))
			self.pause_btn = tk.Button(
				btn_wrap,
				text='Duraklat',
				font=('Consolas', 9, 'bold'),
				bg='#1f6feb',
				fg='white',
				activebackground='#1f6feb',
				activeforeground='white',
				relief='flat',
				command=self.toggle_pause,
			)
			self.pause_btn.pack(side='left', fill='x', expand=True, padx=(0, 6))
			self.stop_btn = tk.Button(
				btn_wrap,
				text='Durdur',
				font=('Consolas', 9, 'bold'),
				bg='#da3633',
				fg='white',
				activebackground='#da3633',
				activeforeground='white',
				relief='flat',
				command=self.request_stop,
			)
			self.stop_btn.pack(side='left', fill='x', expand=True)

			self.label = tk.Label(
				self.root,
				text='',
				font=('Consolas', 10, 'bold'),
				fg='#58a6ff',
				bg='black',
				justify='left',
				anchor='nw',
				padx=10,
				pady=6,
			)
			self.label.pack(fill='x')

			log_wrap = tk.Frame(self.root, bg='black')
			log_wrap.pack(expand=True, fill='both', padx=10, pady=(4, 10))
			self.log_text = tk.Text(
				log_wrap,
				font=('Consolas', 9, 'bold'),
				fg='#58a6ff',
				bg='black',
				insertbackground='#58a6ff',
				relief='flat',
				borderwidth=0,
				highlightthickness=0,
				wrap='word',
			)
			self.log_scroll = tk.Scrollbar(log_wrap, orient='vertical', command=self.log_text.yview)
			self.log_text.configure(yscrollcommand=self.log_scroll.set)
			self.log_text.pack(side='left', expand=True, fill='both')
			self.log_scroll.pack(side='right', fill='y')
			self.log_text.configure(state='disabled')
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
			status_text = 'Durduruldu' if self.stop_requested else ('Duraklatıldı' if self.paused else 'Çalışıyor')
			lines = [
				'SAGGIO HAYALET EKRAN',
				f'Süreç: {self.process_name}',
				f'PC: {self.pc_name}',
				f'Durum: {status_text}',
				f'Adım: {self.current_step or "-"}',
				f'Güncelleme: {stamp}',
			]
			self.label.config(text='\n'.join(lines))
			if self.log_text is not None:
				self.log_text.configure(state='normal')
				self.log_text.delete('1.0', 'end')
				log_lines = self.logs[-200:] if self.logs else ['Hazır']
				for line in log_lines:
					self.log_text.insert('end', f'{line}\n')
				self.log_text.see('end')
				self.log_text.configure(state='disabled')
			if self.pause_btn is not None:
				self.pause_btn.config(text='Devam Et' if self.paused else 'Duraklat')
			self.root.update_idletasks()
			self.root.update()
		except Exception:
			pass

	def toggle_pause(self):
		if not self.enabled or self.stop_requested:
			return
		self.paused = not self.paused
		if self.process_id is not None:
			_runtime_set_controls(self.process_id, paused=self.paused, stop_requested=self.stop_requested)
		self._render()

	def request_stop(self):
		if not self.enabled:
			return
		self.stop_requested = True
		self.paused = False
		if self.process_id is not None:
			_runtime_set_controls(self.process_id, paused=False, stop_requested=True)
		self._render()

	def poll_controls(self):
		if not self.enabled:
			return False
		self._render()
		return bool(self.stop_requested)

	def wait_if_paused(self):
		if not self.enabled:
			return False
		while self.paused and not self.stop_requested:
			try:
				self._render()
				time.sleep(0.15)
			except Exception:
				break
		return bool(self.stop_requested)

	def set_step(self, step_no, total_steps, step_name):
		if self.process_id is not None:
			_runtime_set_step(self.process_id, step_no, total_steps, step_name)
		if not self.enabled:
			return
		self.current_step = f'{step_no}/{total_steps} - {step_name}'
		self._render()

	def push_log(self, text):
		msg = str(text or '').strip()
		if self.process_id is not None and msg:
			_runtime_push_log(self.process_id, msg)
		if not self.enabled:
			return
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
		self.log_text = None
		self.log_scroll = None
		self.pause_btn = None
		self.stop_btn = None

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

		# {sutun_N} ve {loop_value} placeholder'larını runtime değerleriyle değiştir
		if '{' in value and '}' in value:
			for rt_key, rt_val in rt.items():
				value = value.replace(f'{{{rt_key}}}', str(rt_val or ''))

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
				try:
					result.append(children.Item(idx))
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
			is_grid_like = (
				'grid' in lower_id
				or 'grid' in lower_type
				or 'shell' in lower_type
				or 'tablecontrol' in lower_type
				or lower_id.split('/')[-1].startswith('tbl')
			)
			if is_grid_like:
				if grid_type == 'detail':
					if 'wnd[1]' in node_id or 'alv_ht' in lower_id:
						return node
				else:
					if 'wnd[0]' in node_id:
						return node
					if preferred is None:
						preferred = node
		except Exception:
			pass
		stack.extend(_iter_children(node))
	if search_id:
		return None
	return preferred


def _has_popup_window(session):
	try:
		children = getattr(session, 'Children', None)
		count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		return count > 1
	except Exception:
		return False


def _get_grid_row_count(grid):
	for attr in ('rowCount', 'RowCount', 'visibleRowCount', 'VisibleRowCount'):
		try:
			value = int(getattr(grid, attr, 0) or 0)
			if value >= 0:
				return value
		except Exception:
			continue
	return 0


def _normalize_match_text(value):
	return ' '.join(str(value or '').strip().casefold().split())


def _resolve_grid_row_by_text(grid, text_contains):
	needle = _normalize_match_text(text_contains)
	if not needle:
		return None

	row_count = _get_grid_row_count(grid)
	if row_count <= 0:
		return None

	columns = []
	try:
		order = list(getattr(grid, 'ColumnOrder', []) or [])
		columns = [c for c in order if c is not None and str(c).strip()]
	except Exception:
		columns = []

	if not columns:
		try:
			cols_obj = getattr(grid, 'columns', None)
			cnt = int(getattr(cols_obj, 'Count', 0) or 0) if cols_obj is not None else 0
			for ci in range(cnt):
				try:
					col = cols_obj.elementAt(ci)
				except Exception:
					try:
						col = cols_obj.Item(ci)
					except Exception:
						col = None
				if col is None:
					continue
				name = str(getattr(col, 'Name', '') or getattr(col, 'name', '') or '').strip()
				columns.append(name if name else ci)
		except Exception:
			columns = []

	for ridx in range(row_count):
		cell_values = []
		seen_values = set()
		for col in columns:
			try:
				v = str(grid.getCellValue(ridx, col) or '').strip()
				if v and v not in seen_values:
					cell_values.append(v)
					seen_values.add(v)
				continue
			except Exception:
				pass
			try:
				cell = grid.GetCell(ridx, col)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
				if v and v not in seen_values:
					cell_values.append(v)
					seen_values.add(v)
			except Exception:
				continue

		# GuiTableControl için index bazlı hücre okumayı her durumda dene.
		for ci in range(30):
			try:
				cell = grid.GetCell(ridx, ci)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
				if v and v not in seen_values:
					cell_values.append(v)
					seen_values.add(v)
			except Exception:
				if ci > 8:
					break

		row_text = _normalize_match_text(' | '.join(v for v in cell_values if v))
		if row_text and needle in row_text:
			return ridx

	return None


def _read_grid_row_data(grid, row_index):
	"""
	Seçilen grid satırındaki tüm hücre değerlerini sutun_1, sutun_2, ... olarak döndürür.
	Boş hücreler dahil edilmez; her sutun_N için hem sütun adı hem değer saklanır.
	Dönüş: {'sutun_1': 'değer', 'sutun_2': 'değer', ...}  (en fazla 50 sütun)
	"""
	result = {}
	ridx = max(0, int(row_index or 0))
	columns = []

	try:
		order = list(getattr(grid, 'ColumnOrder', []) or [])
		columns = [c for c in order if c is not None and str(c).strip()]
	except Exception:
		columns = []

	if not columns:
		try:
			cols_obj = getattr(grid, 'columns', None)
			cnt = int(getattr(cols_obj, 'Count', 0) or 0) if cols_obj is not None else 0
			for ci in range(min(cnt, 50)):
				try:
					col = cols_obj.elementAt(ci)
				except Exception:
					try:
						col = cols_obj.Item(ci)
					except Exception:
						col = None
				if col is None:
					continue
				name = str(getattr(col, 'Name', '') or getattr(col, 'name', '') or '').strip()
				columns.append(name if name else ci)
		except Exception:
			columns = []

	slot = 1
	seen_values = set()
	for col in columns[:50]:
		v = ''
		try:
			v = str(grid.getCellValue(ridx, col) or '').strip()
		except Exception:
			pass
		if not v:
			try:
				cell = grid.GetCell(ridx, col)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
			except Exception:
				pass
		if v and v not in seen_values:
			result[f'sutun_{slot}'] = v
			seen_values.add(v)
			slot += 1

	# GuiTableControl index bazlı fallback
	if not result:
		for ci in range(50):
			try:
				cell = grid.GetCell(ridx, ci)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
				if v and v not in seen_values:
					result[f'sutun_{slot}'] = v
					seen_values.add(v)
					slot += 1
			except Exception:
				if ci > 8:
					break

	return result


def _select_row_on_grid(grid, row_index):
	"""Hem ALV grid hem GuiTableControl için satır seçmeyi dener."""
	try:
		idx = max(0, int(row_index or 0))
	except Exception:
		idx = 0

	row_count = _get_grid_row_count(grid)
	if row_count > 0:
		idx = min(idx, row_count - 1)

	errors = []

	# GuiTableControl için en güvenilir yöntem
	try:
		abs_row = grid.getAbsoluteRow(idx)
		abs_row.selected = True
		try:
			grid.currentCellRow = idx
		except Exception:
			pass
		# Eski scriptteki gibi ilk hücreye focus vermeyi dene
		try:
			first_cell = None
			for child in _iter_children(grid):
				try:
					cid = str(getattr(child, 'Id', '') or '')
					if cid.endswith('[0,0]') or cid.endswith(f'[0,{idx}]'):
						first_cell = child
						break
				except Exception:
					pass
			if first_cell is not None:
				first_cell.setFocus()
				try:
					first_cell.caretPosition = 0
				except Exception:
					pass
		except Exception:
			pass
		return True, idx, None
	except Exception as ex:
		errors.append(f'getAbsoluteRow: {ex}')

	# ALV GridView için yaygın yöntem
	try:
		grid.currentCellRow = idx
		try:
			grid.selectedRows = str(idx)
		except Exception:
			pass
		return True, idx, None
	except Exception as ex:
		errors.append(f'currentCellRow/selectedRows: {ex}')

	return False, idx, ' | '.join(errors)


def _find_grid(service, grid_id='', timeout_sec=5, grid_type='main'):
	normalized_id = _normalize_session_element_id(grid_id)
	deadline = time.time() + max(1, timeout_sec)
	while time.time() < deadline:
		service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
		grid = None
		if normalized_id:
			grid = service._safe_find(service.session, normalized_id)
			# Bazı kayıtlarda grid yerine hücre id gelebilir; üst segmentlerden gerçek gridi bul.
			if grid is None and '/' in normalized_id:
				parts = normalized_id.split('/')
				for end in range(len(parts) - 1, 0, -1):
					candidate = '/'.join(parts[:end])
					last = candidate.split('/')[-1].lower()
					if not (last.startswith('tbl') or last.startswith('shell') or 'grid' in last):
						continue
					grid = service._safe_find(service.session, candidate)
					if grid is not None:
						break
		if grid is None:
			grid = find_alv_grid(service.session, normalized_id or None, grid_type=grid_type)
		# İstenen id verilmişse ve o bulunamadıysa yanlış grid'e düşmeyelim.
		if normalized_id and grid is not None:
			try:
				gid = _normalize_session_element_id(str(getattr(grid, 'Id', '') or ''))
				if gid != normalized_id and (f'{gid}/' not in f'{normalized_id}/'):
					grid = None
			except Exception:
				pass
		if grid is not None:
			return grid
		time.sleep(0.2)
	return None


def _collect_node_text(node, limit=40):
	parts = []
	stack = [node] if node is not None else []

	def _push_value(value):
		v = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
		if not v:
			return
		v = ' '.join(v.split())
		if v and v not in parts:
			parts.append(v)

	def _extract_html_text(obj):
		for doc_attr in ('Document', 'document', 'HtmlDocument', 'BrowserDocument'):
			try:
				doc = getattr(obj, doc_attr, None)
			except Exception:
				doc = None
			if doc is None:
				continue
			candidates = [doc]
			for sub_attr in ('body', 'documentElement'):
				try:
					sub = getattr(doc, sub_attr, None)
				except Exception:
					sub = None
				if sub is not None:
					candidates.append(sub)
			for cand in candidates:
				for txt_attr in ('innerText', 'Text', 'text', 'innerHTML'):
					try:
						raw = getattr(cand, txt_attr, None)
					except Exception:
						raw = None
					if not raw:
						continue
					value = str(raw)
					if txt_attr == 'innerHTML':
						value = re.sub(r'<[^>]+>', ' ', value)
					_push_value(value)

	while stack and len(parts) < limit:
		current = stack.pop(0)
		for attr in ('Text', 'text', 'Tooltip', 'DefaultTooltip', 'Name', 'Caption', 'Title', 'Value', 'MessageText'):
			try:
				value = str(getattr(current, attr, '') or '').strip()
			except Exception:
				value = ''
			_push_value(value)
		_extract_html_text(current)
		stack.extend(_iter_children(current))
	return ' | '.join(parts)


def _collect_popup_message_text(session, popup_root_id='wnd[1]', limit=80):
	"""SAP popup'larda soru metnini doğrudan txt/lbl alanlarından toplamayı dener."""
	if session is None:
		return ''
	root = _normalize_session_element_id(popup_root_id or 'wnd[1]')
	parts = []
	seen = set()

	def _push(v):
		try:
			txt = str(v or '').replace('\r', ' ').replace('\n', ' ').strip()
		except Exception:
			txt = ''
		if not txt:
			return
		txt = ' '.join(txt.split())
		if txt and txt not in seen:
			seen.add(txt)
			parts.append(txt)

	attrs = (
		'Text', 'text', 'Value', 'DisplayedText', 'PromptText', 'Caption', 'Title',
		'Tooltip', 'DefaultTooltip', 'MessageText', 'Name'
	)

	# Bilinen popup mesaj alanlarını doğrudan dene.
	candidates = []
	for i in range(1, 10):
		candidates.extend([
			f'{root}/usr/txtMESSTXT{i}',
			f'{root}/usr/txtSPOP-TEXTLINE{i}',
			f'{root}/usr/subSUBSCREEN:SAPLSPO1:0502/txtSPOP-TEXTLINE{i}',
		])
	for cid in candidates:
		try:
			obj = session.findById(cid)
		except Exception:
			obj = None
		if obj is None:
			continue
		for attr in attrs:
			try:
				_push(getattr(obj, attr, ''))
			except Exception:
				continue

	# Hala yoksa popup altındaki txt/lbl tiplerini gez.
	try:
		root_obj = session.findById(root)
	except Exception:
		root_obj = None

	stack = [root_obj] if root_obj is not None else []
	while stack and len(parts) < limit:
		node = stack.pop(0)
		try:
			node_id = str(getattr(node, 'Id', '') or getattr(node, 'ID', '') or '')
			node_type = str(getattr(node, 'Type', '') or '')
		except Exception:
			node_id = ''
			node_type = ''
		low_id = node_id.casefold()
		low_type = node_type.casefold()
		if '/txt' in low_id or '/lbl' in low_id or 'label' in low_type or 'text' in low_type:
			for attr in attrs:
				try:
					_push(getattr(node, attr, ''))
				except Exception:
					continue
		stack.extend(_iter_children(node))

	# Sık görülen teknik etiketleri eleyerek daha temiz mesaj döndür.
	noise_tokens = {'wnd[1]', 'usr', 'tbar[0]', 'shellcont', 'shell', 'button_1', 'button_2', 'button_3'}
	clean = []
	for p in parts:
		if p.casefold() in noise_tokens:
			continue
		clean.append(p)
	return ' | '.join(clean[:limit])


def _collect_popup_text_legacy(session, popup_root_id='wnd[1]', limit=200):
	"""Eski süreçte çalışan yöntemi birebir uygular: recursive Children.Item(i) + Text/text."""
	if session is None:
		return ''
	root = _normalize_session_element_id(popup_root_id or 'wnd[1]')
	try:
		popup = session.findById(root)
	except Exception:
		return ''

	parts = []
	seen = set()

	def _push(v):
		try:
			txt = str(v or '').replace('\r', ' ').replace('\n', ' ').strip()
		except Exception:
			txt = ''
		if not txt:
			return
		txt = ' '.join(txt.split())
		if txt and txt not in seen:
			seen.add(txt)
			parts.append(txt)

	def _extract_all_text(obj):
		if obj is None or len(parts) >= limit:
			return
		try:
			t = getattr(obj, 'text', getattr(obj, 'Text', ''))
		except Exception:
			t = ''
		_push(t)

		try:
			children = getattr(obj, 'Children', None)
			count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		except Exception:
			count = 0

		for i in range(count):
			if len(parts) >= limit:
				break
			child = None
			try:
				child = children.Item(i)
			except Exception:
				try:
					child = children(i)
				except Exception:
					child = None
			if child is not None:
				_extract_all_text(child)

	_extract_all_text(popup)
	return ' | '.join(parts[:limit])


def _press_popup_button_by_text(popup, keyword_list):
	"""Popup içinde metnine göre uygun butonu bulup basar."""
	keywords = [str(k or '').strip().casefold() for k in (keyword_list or []) if str(k or '').strip()]
	if not keywords:
		return False, 'anahtar kelime listesi boş.'

	stack = [popup] if popup is not None else []
	while stack:
		node = stack.pop(0)
		try:
			node_type = str(getattr(node, 'Type', '') or '').casefold()
			node_id = str(getattr(node, 'Id', '') or '').strip()
			if 'button' in node_type:
				text = str(getattr(node, 'Text', '') or '').strip()
				name = str(getattr(node, 'Name', '') or '').strip()
				tip = str(getattr(node, 'Tooltip', '') or '').strip()
				haystack = f'{text} {name} {tip}'.casefold()
				if any(k in haystack for k in keywords):
					node.press()
					return True, node_id or text or name
		except Exception:
			pass
		stack.extend(_iter_children(node))
	return False, 'metne uyan popup butonu bulunamadı.'


def _popup_has_button_by_text(popup, keyword_list):
	"""Popup içinde verilen anahtar kelimelerden birini içeren buton var mı?"""
	keywords = [str(k or '').strip().casefold() for k in (keyword_list or []) if str(k or '').strip()]
	if not popup or not keywords:
		return False

	stack = [popup]
	while stack:
		node = stack.pop(0)
		try:
			node_type = str(getattr(node, 'Type', '') or '').casefold()
			node_id = str(getattr(node, 'Id', '') or '').casefold()
			if 'button' in node_type or '/btn' in node_id:
				text = str(getattr(node, 'Text', '') or '').strip()
				name = str(getattr(node, 'Name', '') or '').strip()
				tip = str(getattr(node, 'Tooltip', '') or '').strip()
				haystack = f'{text} {name} {tip}'.casefold()
				if any(k in haystack for k in keywords):
					return True
		except Exception:
			pass
		stack.extend(_iter_children(node))
	return False


def _safe_send_popup_mail(cfg, mail_enabled=True, runtime_state=None, notification_cfg=None, popup_title='', popup_text=''):
	if not mail_enabled:
		return 'Mail gönderimi süreç ayarında kapalı.'
	if not bool(cfg.get('send_mail_on_match')):
		return None
	rt = runtime_state if isinstance(runtime_state, dict) else {}
	notify = notification_cfg if isinstance(notification_cfg, dict) else {}

	mail_to = str(cfg.get('mail_to', '') or '').strip() or str(notify.get('mail_to', '') or '').strip()
	account_id = cfg.get('mail_account_id') or notify.get('mail_account_id')
	if not account_id:
		return 'Mail atlandi: mail hesabı seçili değil.'
	account = MailAccount.objects.filter(pk=account_id, is_active=True).first()
	if not account:
		return f'Mail atlandi: hesap bulunamadi (id={account_id}).'
	if not mail_to:
		mail_to = str(account.email or '').strip()
	if not mail_to:
		return 'Mail atlandi: alıcı bulunamadı.'

	subject = str(cfg.get('mail_subject', '') or '').strip() or f'SAP popup uyarısı: {popup_title or "Popup"}'
	body_lines = []
	custom_body = str(cfg.get('mail_body', '') or '').strip()
	if custom_body:
		body_lines.append(custom_body)
	body_lines.append(f'Popup Başlığı: {popup_title or "(boş)"}')
	body_lines.append(f'Popup Metni: {popup_text or "(boş)"}')

	memory_items = []
	for k in sorted(rt.keys(), key=lambda x: str(x)):
		ks = str(k)
		if ks.startswith('sutun_') or ks.startswith('loop_'):
			memory_items.append((ks, rt.get(k)))
	if memory_items:
		body_lines.append('')
		body_lines.append('Hafıza Değerleri:')
		for mk, mv in memory_items:
			body_lines.append(f'- {mk}: {mv}')
	body = '\n'.join(body_lines)

	try:
		msg = MIMEText(body, _charset='utf-8')
		msg['Subject'] = subject
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


def _find_loop_next_step_index(steps, current_index):
	"""loop_next adımını bulur; önce ileri, yoksa baştan mevcut adıma kadar arar."""
	try:
		start_idx = int(current_index)
	except Exception:
		start_idx = -1

	for k in range(start_idx + 1, len(steps)):
		st = str(steps[k].get('step_type', '') or '').strip()
		if st == SapProcessStep.TYPE_LOOP_NEXT:
			return k

	for k in range(0, max(0, start_idx + 1)):
		st = str(steps[k].get('step_type', '') or '').strip()
		if st == SapProcessStep.TYPE_LOOP_NEXT:
			return k

	return None


def _advance_loop_runtime(steps, runtime_state, current_index):
	"""loop değerini bir sonraki elemana taşır ve hedef adıma dönüş indexini hesaplar."""
	loop_values = runtime_state.get('loop_values') or []
	if not loop_values:
		return False, 'Döngü değeri tanımlı değil', None
	current_idx = int(runtime_state.get('loop_index', 0) or 0)
	next_loop_idx = current_idx + 1
	if next_loop_idx >= len(loop_values):
		return False, 'Döngü değerleri tamamlandı', None

	runtime_state['loop_index'] = next_loop_idx
	runtime_state['loop_value'] = loop_values[next_loop_idx]

	target_idx = None
	for back_i in range(int(current_index) - 1, -1, -1):
		st = str(steps[back_i].get('step_type', '') or '').strip()
		if st == SapProcessStep.TYPE_SAP_FILL:
			target_idx = back_i
			break
	if target_idx is None:
		target_idx = 0

	msg = f'Döngüde sonraki kayıt: {next_loop_idx + 1}/{len(loop_values)} ({runtime_state.get("loop_value", "")}) | adıma dön: {target_idx + 1}'
	return True, msg, target_idx


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
	_runtime_init(process_id, proc.name, 0)
	overlay = _GhostOverlayWindow(enabled=proc.ghost_overlay_enabled, process_name=proc.name, process_id=process_id)
	overlay.push_log('Süreç başlatıldı')
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		overlay.close()
		_runtime_finish(process_id)
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	# Alt süreç zincirinde döngüsel çağrıları engelle (A -> B -> A)
	process_chain = []
	for raw_pid in (body.get('_process_chain', []) if isinstance(body.get('_process_chain', []), list) else []):
		try:
			process_chain.append(int(raw_pid))
		except Exception:
			continue
	if int(process_id) in process_chain:
		overlay.close()
		_runtime_finish(process_id)
		return JsonResponse({'ok': False, 'error': 'Döngüsel alt süreç çağrısı engellendi.'}, status=400)

	steps = _extract_runtime_steps(body, proc)
	if not steps:
		overlay.close()
		_runtime_finish(process_id)
		return JsonResponse({'ok': False, 'error': 'Çalıştırılacak adım yok.'}, status=400)
	_runtime_set_step(process_id, 0, len(steps), '')

	conn, conn_err = _resolve_connection_from_steps(steps)
	if conn_err:
		overlay.close()
		_runtime_finish(process_id)
		return JsonResponse({'ok': False, 'error': conn_err}, status=400)

	# Bildirim konfigürasyonu
	# Bildirim konfigürasyonu — sadece şablondaki notification alanından alınır.
	_notify_cfg = {}
	_notify_setup_notes = []
	_template_notify = {}
	try:
		tpl_name = str(conn.get('template_name', '') or '').strip()
		if tpl_name:
			tpl = SAPTemplateService.get_template(tpl_name)
			if isinstance(tpl, dict):
				state = tpl.get('state', {}) if isinstance(tpl.get('state'), dict) else {}
				notification = state.get('notification', {}) if isinstance(state.get('notification'), dict) else {}
				_template_notify = notification
	except Exception:
		_template_notify = {}

	def _as_int(value):
		try:
			v = str(value or '').strip()
			return int(v) if v else None
		except Exception:
			return None

	if proc.telegram_notifications_enabled:
		tg_bot_id = _as_int(_template_notify.get('telegram_bot_id'))
		tg_group_id = _as_int(_template_notify.get('telegram_group_id'))
		if tg_bot_id and tg_group_id:
			_notify_cfg['telegram_bot_id'] = tg_bot_id
			_notify_cfg['telegram_group_id'] = tg_group_id
			_notify_cfg['telegram_voice_enabled'] = bool(proc.telegram_voice_enabled)
			for key in ('telegram_start_message', 'telegram_end_message'):
				value = str(_template_notify.get(key, '') or '').strip()
				if value:
					_notify_cfg[key] = value
		else:
			_notify_setup_notes.append('Telegram bildirim atlandı: şablonda Telegram bot/grup seçili değil.')

	if proc.mail_notifications_enabled:
		mail_id = _as_int(_template_notify.get('mail_account_id'))
		if mail_id:
			_notify_cfg['mail_account_id'] = mail_id
			for key in ('mail_to', 'mail_subject', 'mail_start_message', 'mail_end_message'):
				value = str(_template_notify.get(key, '') or '').strip()
				if value:
					_notify_cfg[key] = value
		else:
			_notify_setup_notes.append('Mail bildirimi atlandı: şablonda mail hesabı seçili değil.')


	# Başlangıç bildirimi
	if ('telegram_bot_id' in _notify_cfg and 'telegram_group_id' in _notify_cfg) or ('mail_account_id' in _notify_cfg):
		start_notes = _notify_sap_event(_notify_cfg, 'start')
		for n in (start_notes or []):
			ch = n.get('channel', '')
			ok_flag = n.get('ok', False)
			msg = n.get('msg', '')
			if not ok_flag:
				_notify_setup_notes.append(f"{ch} hatası: {msg}")
			else:
				_notify_setup_notes.append(f"{ch} gönderildi.")

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
	for note in (_notify_setup_notes or []):
		logs.append({'step': 0, 'type': 'notification', 'label': 'Bildirim', 'ok': False if 'atlandı' in str(note).casefold() else True, 'msg': str(note)})
		overlay.push_log(str(note))

	_end_notify_sent = False
	def _send_end_notify_once():
		nonlocal _end_notify_sent
		if _end_notify_sent:
			return
		if ('telegram_bot_id' in _notify_cfg and 'telegram_group_id' in _notify_cfg) or ('mail_account_id' in _notify_cfg):
			_notify_sap_event(_notify_cfg, 'end', logs)
		_end_notify_sent = True

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

	def _handle_overlay_controls(failed_at_index):
		state = _runtime_get(process_id) or {}
		web_stop = bool(state.get('stop_requested'))
		web_paused = bool(state.get('paused'))
		if web_stop:
			overlay.stop_requested = True
		if web_paused != bool(overlay.paused):
			overlay.paused = web_paused
		if overlay.poll_controls():
			overlay.push_log('Kullanıcı süreci durdurdu')
			overlay.close()
			_runtime_finish(process_id)
			return JsonResponse({'ok': False, 'error': 'Süreç kullanıcı tarafından durduruldu.', 'logs': logs, 'failed_at': failed_at_index}, status=409)
		if overlay.wait_if_paused():
			overlay.push_log('Kullanıcı süreci durdurdu')
			overlay.close()
			_runtime_finish(process_id)
			return JsonResponse({'ok': False, 'error': 'Süreç kullanıcı tarafından durduruldu.', 'logs': logs, 'failed_at': failed_at_index}, status=409)
		return None

	i = 0
	iteration_count = 0
	max_iterations = max(100, len(steps) * 20)
	while i < len(steps) and i <= upto_index:
		stop_response = _handle_overlay_controls(i)
		if stop_response is not None:
			return stop_response
		overlay.set_step(i + 1, len(steps), str(steps[i].get('label') or steps[i].get('step_type') or 'Adım'))
		if proc.office_express_auto_close:
			closed_before = _close_office_express_popups(service)
			if closed_before > 0:
				msg = f'Ofis Ekspres popup kapatıldı (adım öncesi): {closed_before}'
				logs.append({'step': i + 1, 'type': 'office_popup', 'label': 'Office Popup', 'ok': True, 'msg': msg})
				overlay.push_log(msg)
		if iteration_count >= max_iterations:
			overlay.close()
			_runtime_finish(process_id)
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
				# Şablon uygulamadan önce açık popup pencereleri (wnd[1]+) kapat
				if service.session is not None:
					try:
						_children = getattr(service.session, 'Children', None)
						_wnd_count = int(getattr(_children, 'Count', 0) or 0) if _children is not None else 0
						for _wi in range(_wnd_count - 1, 0, -1):
							try:
								_wnd = _children(_wi)
								_wnd.sendVKey(12)  # ESC
								service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
							except Exception:
								pass
					except Exception:
						pass
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
				row_text_contains = str(cfg.get('row_text_contains', '') or '').strip()
				normalized_grid_id = _normalize_session_element_id(grid_id)
				wait_timeout_sec = max(1, min(int(cfg.get('wait_timeout_sec') or 25), 60))
				popup_wait_sec = max(1, min(int(cfg.get('popup_wait_sec') or wait_timeout_sec), wait_timeout_sec))
				allow_main_fallback = bool(cfg.get('allow_main_fallback', True))
				grid = None
				grid_source = ''
				if normalized_grid_id:
					# Popup grid hedeflenmişse önce popup penceresini bekle.
					if normalized_grid_id.startswith('wnd[1]/'):
						service._wait_for_element(service.session, 'wnd[1]', timeout_sec=popup_wait_sec)
					grid = _find_grid(
						service,
						grid_id=normalized_grid_id,
						timeout_sec=wait_timeout_sec,
						grid_type='detail' if 'wnd[1]' in normalized_grid_id else 'main',
					)
					grid_source = normalized_grid_id
				else:
					# Grid ID yoksa önce popup detay tablosunu aktif olarak bekle.
					service._wait_for_element(service.session, 'wnd[1]', timeout_sec=popup_wait_sec)
					grid = _find_grid(service, grid_id='', timeout_sec=popup_wait_sec, grid_type='detail')
					if grid is not None:
						grid_source = 'auto-detail'
					elif allow_main_fallback:
						remain_timeout = max(1, wait_timeout_sec - popup_wait_sec)
						grid = _find_grid(service, grid_id='', timeout_sec=remain_timeout, grid_type='main')
						grid_source = 'auto-main'
					else:
						grid = None
						grid_source = 'auto-detail-only'
				if not grid:
					gid_msg = normalized_grid_id or 'auto-detect'
					return JsonResponse({'ok': False, 'error': f'Grid bulunamadı: {gid_msg}', 'logs': logs, 'failed_at': i}, status=404)
				resolved_by = 'row_index'
				row_index = 0
				if row_text_contains:
					resolved_row = _resolve_grid_row_by_text(grid, row_text_contains)
					if resolved_row is None:
						return JsonResponse({'ok': False, 'error': f'Satır metni bulunamadı: {row_text_contains}', 'logs': logs, 'failed_at': i}, status=404)
					row_index = int(resolved_row)
					resolved_by = 'row_text_contains'
				else:
					try:
						row_index = max(0, int(cfg.get('row_index') or 1) - 1)
					except (TypeError, ValueError):
						row_index = 0
				ok_select, applied_idx, err_msg = _select_row_on_grid(grid, row_index)
				if not ok_select:
					return JsonResponse({'ok': False, 'error': f'Grid satırı seçilemedi: {err_msg}', 'logs': logs, 'failed_at': i}, status=500)
				service._wait_until_idle(service.session, timeout_sec=5)
				copy_row_to_memory = bool(cfg.get('copy_row_to_memory', False))
				select_hint = f'{applied_idx + 1} ({grid_source})'
				if resolved_by == 'row_text_contains':
					select_hint = f'{select_hint} | metin: {row_text_contains}'
				if copy_row_to_memory:
					# Seçilen satırın verilerini runtime_state'e kopyala
					row_data = _read_grid_row_data(grid, applied_idx)
					runtime_state.update(row_data)
					row_data_hint = ', '.join(f'{k}={v}' for k, v in row_data.items()) if row_data else 'veri okunamadı'
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Grid satırı seçildi: {select_hint} | hafızaya kopyalandı | {row_data_hint}'})
				else:
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Grid satırı seçildi: {select_hint}'})

			elif step_type == SapProcessStep.TYPE_SAP_POPUP_DECIDE:
				ok, payload = _ensure_session_ready()
				if not ok:
					return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
				popup_root_id = _normalize_session_element_id(cfg.get('popup_root_id', 'wnd[1]') or 'wnd[1]')
				popup = service._wait_for_element(service.session, popup_root_id, timeout_sec=max(1, min(int(cfg.get('timeout_sec') or 5), 30)))
				if not popup:
					if bool(cfg.get('fail_if_not_found')):
						return JsonResponse({'ok': False, 'error': 'Beklenen popup bulunamadı.', 'logs': logs, 'failed_at': i}, status=404)
					if bool(cfg.get('next_if_not_found', True)):
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Popup bulunamadı, sonraki adıma geçildi'})
						i = next_i
						continue
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Popup bulunamadı, süreç bu adımda sonlandırıldı'})
					overlay.push_log('Popup bulunamadı, süreç sonlandırıldı')
					overlay.close()
					_runtime_finish(process_id)
					return JsonResponse({'ok': True, 'logs': logs, 'ran_until': i, 'connection_template': conn.get('template_name', '')})
				title = str(getattr(popup, 'Text', '') or '').strip()
				popup_legacy_text = _collect_popup_text_legacy(service.session, popup_root_id, limit=220)
				popup_message_text = _collect_popup_message_text(service.session, popup_root_id, limit=120)
				popup_deep_text = _collect_node_text(popup, limit=220)
				popup_text = ' | '.join([p for p in [popup_legacy_text, popup_message_text, popup_deep_text] if p])
				title_contains = _normalize_match_text(str(cfg.get('popup_title_contains', '') or ''))
				text_contains = _normalize_match_text(str(cfg.get('popup_text_contains', '') or ''))
				title_norm = _normalize_match_text(title)
				popup_text_norm = _normalize_match_text(popup_text)
				matched = True
				if title_contains and title_contains not in title_norm:
					matched = False
				if text_contains and text_contains not in popup_text_norm:
					matched = False
				fallback_used = False
				if not matched and bool(cfg.get('allow_question_popup_fallback', True)):
					title_ok = (not title_contains) or (title_contains in title_norm)
					has_yes = _popup_has_button_by_text(popup, ['evet', 'yes'])
					has_no = _popup_has_button_by_text(popup, ['hayır', 'hayir', 'no'])
					if title_ok and has_yes and has_no:
						# Eski süreçteki gibi soru popup'ını başlık+buton deseniyle yakala.
						# Özellikle HTML kontrol içinde metin dönmeyen popup'lar için.
						matched = True
						fallback_used = True
				if not matched:
					if bool(cfg.get('fail_if_not_match')):
						return JsonResponse({'ok': False, 'error': f'Popup eşleşmedi. Başlık: {title} | Metin: {popup_text}', 'logs': logs, 'failed_at': i}, status=400)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Popup geldi ama eşleşmedi. Başlık: {title}'})
					i = next_i
					continue
				if fallback_used:
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Popup metni alınamadı; başlık ve Evet/Hayır buton desenine göre eşleşti (fallback).'})
				action = str(cfg.get('popup_action', '') or '').strip().casefold()
				if action == 'close_escape':
					popup.sendVKey(12)
				elif action == 'close_enter':
					popup.sendVKey(0)
				elif action == 'press_yes':
					ok_btn, btn_msg = _press_popup_button_by_text(popup, ['evet', 'yes', 'ok', 'tamam'])
					if not ok_btn:
						return JsonResponse({'ok': False, 'error': f'Popup evet butonu bulunamadı: {btn_msg}', 'logs': logs, 'failed_at': i}, status=404)
				elif action == 'press_no':
					ok_btn, btn_msg = _press_popup_button_by_text(popup, ['hayır', 'hayir', 'no'])
					if not ok_btn:
						return JsonResponse({'ok': False, 'error': f'Popup hayır/no butonu bulunamadı: {btn_msg}', 'logs': logs, 'failed_at': i}, status=404)
				elif action == 'press_cancel':
					ok_btn, btn_msg = _press_popup_button_by_text(popup, ['iptal', 'cancel', 'vazgeç', 'vazgec'])
					if not ok_btn:
						return JsonResponse({'ok': False, 'error': f'Popup iptal butonu bulunamadı: {btn_msg}', 'logs': logs, 'failed_at': i}, status=404)
				elif action == 'press_button_id':
					button_id = _normalize_session_element_id(cfg.get('popup_button_id', ''))
					button = service._wait_for_element(service.session, button_id, timeout_sec=5)
					if not button:
						return JsonResponse({'ok': False, 'error': f'Popup butonu bulunamadı: {button_id}', 'logs': logs, 'failed_at': i}, status=404)
					button.press()
				service._wait_until_idle(service.session, timeout_sec=10)
				mail_msg = _safe_send_popup_mail(
					cfg,
					mail_enabled=proc.mail_notifications_enabled,
					runtime_state=runtime_state,
					notification_cfg=_notify_cfg,
					popup_title=title,
					popup_text=popup_text,
				)
				log_msg = f'Popup işlendi. Başlık: {title}'
				if mail_msg:
					log_msg = f'{log_msg} | {mail_msg}'
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': log_msg})
				on_match_action = str(cfg.get('on_match_action', 'next_step') or 'next_step').strip().casefold()
				if on_match_action == 'goto_step':
					try:
						target_step_no = int(cfg.get('popup_target_step') or 1)
					except (TypeError, ValueError):
						target_step_no = 1
					target_step_no = max(1, min(target_step_no, len(steps)))
					next_i = target_step_no - 1
				elif on_match_action == 'loop_next':
					loop_idx = _find_loop_next_step_index(steps, i)
					if loop_idx is not None:
						next_i = loop_idx
					else:
						advanced, loop_msg, target_idx = _advance_loop_runtime(steps, runtime_state, i)
						if advanced:
							next_i = target_idx
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Popup sonrası loop_next adımı olmadan döngü ilerletildi: {loop_msg}'})
						else:
							if loop_msg == 'Döngü değerleri tamamlandı':
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Döngü değerleri tamamlandı, süreç bitirildi'})
								overlay.push_log('Döngü değerleri tamamlandı, süreç bitirildi')
								overlay.close()
								_runtime_finish(process_id)
								_send_end_notify_once()
								return JsonResponse({'ok': True, 'logs': logs, 'ran_until': i, 'connection_template': conn.get('template_name', '')})
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Popup sonrası loop_next adımı bulunamadı ve döngü ilerletilemedi: {loop_msg}'})
				elif on_match_action == 'stop':
					overlay.push_log('Popup adımı sonrası süreç durduruldu')
					overlay.close()
					_runtime_finish(process_id)
					_send_end_notify_once()
					return JsonResponse({'ok': True, 'logs': logs, 'ran_until': i, 'connection_template': conn.get('template_name', '')})
				elif on_match_action == 'fail':
					return JsonResponse({'ok': False, 'error': f'Popup eşleşti ve hata aksiyonu tetiklendi. Başlık: {title}', 'logs': logs, 'failed_at': i}, status=400)

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
					last_countdown = None
					while time.time() < deadline:
						stop_response = _handle_overlay_controls(i)
						if stop_response is not None:
							return stop_response
						remain = max(0, int(deadline - time.time()))
						if remain != last_countdown:
							last_countdown = remain
							wait_msg = f'Ekran bekleniyor: {cfg.get("screen_title", "")} | kalan: {remain}s'
							overlay.push_log(wait_msg)
						service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
						title = service._get_window_title(service.session).casefold()
						if screen_title in title:
							found = True
							overlay.push_log(f'Ekran geldi: {cfg.get("screen_title", "")}')
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
							loop_idx = _find_loop_next_step_index(steps, i)
							if loop_idx is not None:
								next_i = loop_idx
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, döngüde sonraki elemana geçildi ({loop_idx + 1}. adım): {cfg.get("screen_title", "")}'})
							else:
								advanced, loop_msg, target_idx = _advance_loop_runtime(steps, runtime_state, i)
								if advanced:
									next_i = target_idx
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, loop_next adımı olmadan döngü ilerletildi: {loop_msg}'})
								else:
									if loop_msg == 'Döngü değerleri tamamlandı':
										logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Döngü değerleri tamamlandı, süreç bitirildi'})
										overlay.push_log('Döngü değerleri tamamlandı, süreç bitirildi')
										overlay.close()
										_runtime_finish(process_id)
										_send_end_notify_once()
										return JsonResponse({'ok': True, 'logs': logs, 'ran_until': i, 'connection_template': conn.get('template_name', '')})
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, loop_next adımı bulunamadı ve döngü ilerletilemedi: {loop_msg}'})
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
					stop_response = _handle_overlay_controls(i)
					if stop_response is not None:
						return stop_response
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
									row_idx = int(getattr(grid, 'currentCellRow', 0) or 0)
								else:
									row_idx = int(a_value or 0)
								ok_select, applied_idx, err_msg = _select_row_on_grid(grid, row_idx)
								if ok_select:
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Grid satırı seçildi: {applied_idx + 1}'})
								else:
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Grid seçim hatası: {err_msg}'})
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
				advanced, loop_msg, target_idx = _advance_loop_runtime(steps, runtime_state, i)
				if not advanced:
					if loop_msg == 'Döngü değerleri tamamlandı':
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Döngü değerleri tamamlandı, süreç bitirildi'})
						overlay.push_log('Döngü değerleri tamamlandı, süreç bitirildi')
						overlay.close()
						_runtime_finish(process_id)
						_send_end_notify_once()
						return JsonResponse({'ok': True, 'logs': logs, 'ran_until': i, 'connection_template': conn.get('template_name', '')})
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': loop_msg})
				else:
					next_i = target_idx
					logs.append({
						'step': i + 1,
						'type': step_type,
						'label': step_name,
						'ok': True,
						'msg': loop_msg
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

			elif step_type == SapProcessStep.TYPE_RUN_PROCESS:
				try:
					target_process_id = int(cfg.get('target_process_id') or 0)
				except (TypeError, ValueError):
					target_process_id = 0
				if target_process_id <= 0:
					msg = 'Çalıştırılacak alt süreç seçilmedi.'
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
					else:
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
					continue
				if target_process_id == int(process_id):
					msg = 'Bir süreç kendisini alt süreç olarak çağıramaz.'
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
					else:
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
					continue

				target_proc = SapProcess.objects.filter(pk=target_process_id).first()
				if not target_proc:
					msg = f'Alt süreç bulunamadı (id={target_process_id}).'
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
					else:
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=404)
					continue

				child_req = HttpRequest()
				child_req.method = 'POST'
				child_req.META = getattr(request, 'META', {}).copy()
				if hasattr(request, 'user'):
					child_req.user = request.user
				child_body = {
					'_process_chain': process_chain + [int(process_id)],
				}
				child_req._body = json.dumps(child_body).encode('utf-8')

				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Alt süreç başlatıldı: {target_proc.name}'})
				child_resp = sap_process_run_preview(child_req, target_process_id)
				child_status = int(getattr(child_resp, 'status_code', 500) or 500)
				try:
					child_data = json.loads((child_resp.content or b'{}').decode('utf-8'))
				except Exception:
					child_data = {}
				child_ok = bool(child_data.get('ok')) and child_status < 400
				if child_ok:
					child_logs = child_data.get('logs', []) if isinstance(child_data.get('logs'), list) else []
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Alt süreç tamamlandı: {target_proc.name} | log: {len(child_logs)}'})
				else:
					child_err = str(child_data.get('error') or f'Alt süreç hata döndürdü (HTTP {child_status})')
					if continue_on_error:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Alt süreç hatası (devam): {child_err}'})
					else:
						return JsonResponse({'ok': False, 'error': f'Alt süreç başarısız: {child_err}', 'logs': logs, 'failed_at': i}, status=500 if child_status < 400 else child_status)

			else:
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Bilinmeyen step_type: {step_type}'})

		except Exception as ex:
			if continue_on_error and step_type in (SapProcessStep.TYPE_FTP_LIST, SapProcessStep.TYPE_FTP_DOWNLOAD, SapProcessStep.TYPE_FTP_UPLOAD):
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {ex}'})
				overlay.push_log(f'Hata (devam): {ex}')
				continue
			overlay.close()
			_runtime_finish(process_id)
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
	_runtime_finish(process_id)
	# Bitiş bildirimi
	_send_end_notify_once()
	return JsonResponse({'ok': True, 'logs': logs, 'ran_until': upto_index, 'connection_template': conn.get('template_name', '')})
