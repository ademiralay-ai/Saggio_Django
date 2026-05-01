"""SAP process run/preview JSON endpoint (interactive runtime).

Originally lived in ``core/views.py``.

This is the largest endpoint in the project: it walks through ``SapProcessStep``
records and executes them against a live SAP GUI session, producing a step-by-step
preview / execution log. Helper logic lives in ``core/services`` and ``core/utils``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ..firebase_service import SAPTemplateService
from ..models import (
	FTPAccount,
	MailAccount,
	SapProcess,
	SapProcessStep,
)
from ..sap_service import SAPScanService
from ..utils.parsing import (
	_as_bool,
	_invoke_button_or_menu,
	_is_menu_target,
	_normalize_match_text,
	_normalize_session_element_id,
	_parse_decimal_text,
	_parse_toolbar_context_command,
	_resolve_rule_target_index,
	_resolve_step_target_index,
)
from ..utils.placeholders import _resolve_placeholders
from ..utils.runtime_state import (
	_runtime_init,
	_runtime_get,
	_runtime_finish,
	_runtime_push_log,
	_runtime_set_step,
)
from ..gui.ghost_overlay import _GhostOverlayWindow
from ..services.excel_service import _resolve_fill_input_excel_value
from ..services.ftp_service import (
	_ftp_list_files,
	_ftp_download,
	_ftp_upload,
)
from ..services.notification_service import (
	_generate_row_report_xlsx,
	_notify_sap_event,
	_safe_send_popup_mail,
	_send_mail_message,
)
from ..services.sap_runtime_service import (
	_advance_excel_loop_runtime,
	_advance_loop_runtime,
	_build_actions_from_template_state_with_runtime,
	_ensure_runtime_loop_state,
	_extract_runtime_steps,
	_find_loop_next_step_index,
	_iter_children,
	_read_sap_element_text,
	_read_sap_statusbar,
	_resolve_connection_from_steps,
	_send_sap_hotkey,
)
from ..services.sap_grid_service import (
	_find_grid,
	_read_grid_row_data,
	_resolve_grid_row_by_text,
	_select_row_on_grid,
)
from ..services.sap_popup_service import (
	_close_office_express_popups,
	_collect_node_text,
	_collect_popup_message_text,
	_collect_popup_text_legacy,
	_popup_has_button_by_text,
	_press_popup_button_by_text,
)
from ..services.sap_grid_service import find_alv_grid
from ..sap_popup_utils import fill_popup_input_value, select_popup_radio_by_id
from ..windows_dialog_utils import scan_visible_dialogs


@require_POST
def sap_process_run_preview(request, process_id):
	"""Süreci (veya belirtilen adıma kadar) gerçek SAP oturumunda çalıştır."""
	proc = get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body)
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	async_mode = _as_bool(body.get('async_mode', False), False)
	if async_mode:
		state = _runtime_get(process_id)
		if state and bool(state.get('running')):
			# Stop istendi, force_reset talebi geldi veya updated_at 30+ saniyedir
			# güncellenmediyse runtime kaydını otomatik sıfırla.
			_force_reset = bool(body.get('_force_reset')) or bool(state.get('stop_requested'))
			if not _force_reset:
				try:
					from datetime import datetime as _dt
					_upd = state.get('updated_at', '')
					_age = (_dt.now() - _dt.fromisoformat(_upd)).total_seconds() if _upd else 999
					_force_reset = _age > 30
				except Exception:
					_force_reset = True
			if _force_reset:
				_runtime_finish(process_id)
			else:
				return JsonResponse({
					'ok': False,
					'error': 'Bu süreç zaten çalışıyor. Eğer takıldıysa "Zorla Sıfırla" deneyin.',
					'can_force_reset': True,
				}, status=409)

		def _async_runner(snapshot_body, req_meta, req_user):
			try:
				child_req = HttpRequest()
				child_req.method = 'POST'
				child_req.META = dict(req_meta or {})
				if req_user is not None:
					child_req.user = req_user
				payload = dict(snapshot_body or {})
				payload['async_mode'] = False
				child_req._body = json.dumps(payload).encode('utf-8')
				sap_process_run_preview(child_req, process_id)
			except Exception as ex:
				_runtime_push_log(process_id, f'Async runner hatası: {ex}')
				_runtime_finish(process_id)

		_runtime_init(process_id, proc.name, 0)
		_runtime_push_log(process_id, 'Süreç başlatılıyor (arka plan)...')
		threading.Thread(
			target=_async_runner,
			args=(body, getattr(request, 'META', {}).copy(), getattr(request, 'user', None)),
			daemon=True,
		).start()
		return JsonResponse({'ok': True, 'started': True, 'message': 'Süreç arka planda başlatıldı.'})

	_runtime_init(process_id, proc.name, 0)
	agent_info = {
		'agent_code': str(body.get('_triggered_by_agent') or ''),
		'agent_ip': str(body.get('_triggered_by_agent_ip') or ''),
		'job_id': body.get('_job_id'),
	}
	overlay = _GhostOverlayWindow(enabled=proc.ghost_overlay_enabled, process_name=proc.name, process_id=process_id, agent_info=agent_info)
	overlay.push_log('Süreç başlatıldı')
	try:

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
		# Bildirim konfigürasyonu — tüm sap_fill adımlarındaki şablonlar taranır;
		# telegram_bot_id ve telegram_group_id içeren ilk şablon kullanılır.
		_notify_cfg = {}
		_notify_setup_notes = []
		_template_notify = {}
		try:
			# Önce bağlantı şablonunu dene, sonra diğer sap_fill adımlarını tara
			candidate_tpl_names = []
			_conn_tpl = str(conn.get('template_name', '') or '').strip()
			if _conn_tpl:
				candidate_tpl_names.append(_conn_tpl)
			for _step in steps:
				_stype = str(_step.get('step_type', '') or '').strip()
				if _stype == SapProcessStep.TYPE_SAP_FILL:
					_scfg = _step.get('config', {}) if isinstance(_step.get('config'), dict) else {}
					_stpl = str(_scfg.get('template_name', '') or '').strip()
					if _stpl and _stpl not in candidate_tpl_names:
						candidate_tpl_names.append(_stpl)
			for _tpl_name in candidate_tpl_names:
				_tpl = SAPTemplateService.get_template(_tpl_name)
				if not isinstance(_tpl, dict):
					continue
				_state = _tpl.get('state', {}) if isinstance(_tpl.get('state'), dict) else {}
				_notif = _state.get('notification', {}) if isinstance(_state.get('notification'), dict) else {}
				_bot_raw = str(_notif.get('telegram_bot_id', '') or '').strip()
				_grp_raw = str(_notif.get('telegram_group_id', '') or '').strip()
				if _bot_raw and _grp_raw:
					_template_notify = _notif
					break
				if not _template_notify and (_notif.get('mail_account_id')):
					_template_notify = _notif  # mail-only fallback; keep scanning for telegram
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
			try:
				start_notes = _notify_sap_event(_notify_cfg, 'start')
			except Exception as _ex:
				start_notes = []
				_notify_setup_notes.append(f'Başlangıç bildirimi sırasında beklenmedik hata: {_ex}')
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
		try:
			start_index = int(body.get('start_index', 0))
		except (TypeError, ValueError):
			start_index = 0
		if start_index < 0:
			start_index = 0
		if start_index > len(steps) - 1:
			start_index = len(steps) - 1
		if upto_index < 0:
			upto_index = 0
		if upto_index > len(steps) - 1:
			upto_index = len(steps) - 1
		if start_index > upto_index:
			start_index = upto_index

		service = SAPScanService()
		logs = []
		runtime_state = {}
		runtime_state['row_results'] = []  # satır bazlı sonuç raporu için
		for note in (_notify_setup_notes or []):
			logs.append({'step': 0, 'type': 'notification', 'label': 'Bildirim', 'ok': False if 'atlandı' in str(note).casefold() else True, 'msg': str(note)})
			overlay.push_log(str(note))

		# ─── SAP Bağlantı Hazırlık (Retry) ───────────────────────────────
		# Süreç ayarlarında "SAP bağlantı yoksa tekrar dene" açıksa, ana
		# döngüye girmeden önce SAP'ın gerçekten ulaşılabilir olduğundan
		# emin oluruz. Aksi halde verilen aralıkta tekrar tekrar deneriz.
		if bool(getattr(proc, 'sap_retry_enabled', True)):
			_target_sys_id = str(conn.get('sys_id', '') or '').strip()
			if _target_sys_id:
				_retry_interval_min = max(1, int(getattr(proc, 'sap_retry_interval_minutes', 10) or 10))
				_retry_max_min = int(getattr(proc, 'sap_retry_max_duration_minutes', 180) or 0)
				_retry_interval_sec = _retry_interval_min * 60
				_retry_max_sec = _retry_max_min * 60 if _retry_max_min > 0 else 0

				def _retry_stop_check():
					_st = _runtime_get(process_id) or {}
					if bool(_st.get('stop_requested')):
						return True
					if getattr(overlay, 'stop_requested', False):
						return True
					return False

				def _retry_on_attempt(attempt_no, ok_attempt, err_attempt, next_wait_sec):
					if ok_attempt:
						_msg = f'SAP bağlantısı kuruldu (deneme #{attempt_no}).'
						overlay.push_log(_msg)
						logs.append({'step': 0, 'type': 'sap_retry', 'label': 'SAP Bağlantı', 'ok': True, 'msg': _msg})
					else:
						_min = max(1, int(round(next_wait_sec / 60)))
						_msg = f'SAP bağlantı denemesi #{attempt_no} başarısız: {err_attempt or "bilinmeyen hata"}. {_min} dk sonra tekrar denenecek.'
						overlay.push_log(_msg)
						logs.append({'step': 0, 'type': 'sap_retry', 'label': 'SAP Bağlantı', 'ok': False, 'msg': _msg})

				overlay.push_log(f'SAP bağlantısı kontrol ediliyor: {_target_sys_id}')
				_ok_conn, _attempts, _last_err = service.wait_for_sap_available(
					_target_sys_id,
					retry_interval_sec=_retry_interval_sec,
					max_duration_sec=_retry_max_sec,
					stop_check=_retry_stop_check,
					on_attempt=_retry_on_attempt,
				)
				if not _ok_conn:
					_err_summary = _last_err or 'Bilinmeyen SAP bağlantı hatası'
					return JsonResponse({
						'ok': False,
						'error': f'SAP bağlantısı sağlanamadı ({_attempts} deneme). Son hata: {_err_summary}',
						'logs': logs,
						'failed_at': 0,
					}, status=503)

		_end_notify_sent = False
		def _send_end_notify_once():
			nonlocal _end_notify_sent
			if _end_notify_sent:
				return
			if ('telegram_bot_id' in _notify_cfg and 'telegram_group_id' in _notify_cfg) or ('mail_account_id' in _notify_cfg):
				try:
					_notify_sap_event(_notify_cfg, 'end', logs)
				except Exception as _ex:
					try:
						logs.append({'step': 0, 'type': 'notification', 'label': 'Bildirim', 'ok': False, 'msg': f'Bitiş bildirimi hatası: {_ex}'})
					except Exception:
						pass
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

		def _wait_until_idle_or_popup(timeout_sec=30):
			"""Wait until session is idle, but return early if a popup window appears."""
			deadline = time.time() + max(1, min(int(timeout_sec or 30), 120))
			while time.time() < deadline:
				session = getattr(service, 'session', None)
				if session is None:
					return False, 'session_missing'

				try:
					children = getattr(session, 'Children', None)
					wnd_count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
					if wnd_count > 1:
						return True, 'popup_detected'
				except Exception:
					pass

				try:
					if not bool(getattr(session, 'Busy', False)):
						return True, 'idle'
				except Exception:
					return True, 'unknown'

				time.sleep(0.15)

			return False, 'timeout'

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

		i = start_index
		iteration_count = 0
		max_iterations = max(100, len(steps) * 20)
		while i < len(steps) and i <= upto_index:
			stop_response = _handle_overlay_controls(i)
			if stop_response is not None:
				return stop_response
			overlay.set_step(i + 1, len(steps), str(steps[i].get('label') or steps[i].get('step_type') or 'Adım'))
			pre_step_type = str(steps[i].get('step_type', '') or '').strip()
			if proc.office_express_auto_close and pre_step_type not in (
				SapProcessStep.TYPE_WINDOWS_DIALOG_ACTION,
				SapProcessStep.TYPE_WINDOWS_SCAN_DIALOGS,
				SapProcessStep.TYPE_CONVERT_SAP_EXPORT,
			):
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
			continue_on_error = _as_bool(cfg.get('continue_on_error'))
			skip_step_end_auto_close = False

			if bool(cfg.get('disabled', False)):
				logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'Adım pasif olduğu için atlandı'})
				overlay.push_log(f'{step_name}: pasif adım atlandı')
				i = next_i
				continue

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
					# Doldurma verilerini raporlama için biriktir
					filled_bucket = runtime_state.setdefault('_current_row_filled', [])
					for _act in actions:
						_act_type = str(_act.get('action_type', '') or '')
						if _act_type in ('sabit', 'dinamik', 'dongu', 'selectbox'):
							filled_bucket.append({
								'alan': str(_act.get('element_id', '') or ''),
								'kaynak': _act_type,
								'deger': str(_act.get('value', '') or ''),
							})
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
							return JsonResponse({'ok': False, 'error': f'Desteklenmeyen tuÅŸ: {key}', 'logs': logs, 'failed_at': i}, status=400)
						service._wait_until_idle(service.session, timeout_sec=15)
						service.session.findById('wnd[0]').sendVKey(vk)
						service._wait_until_idle(service.session, timeout_sec=30)
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{key} gönderildi'})

					delay_after_ms = int(cfg.get('delay_after_ms') or 0)
					if delay_after_ms > 0:
						time.sleep(min(delay_after_ms / 1000.0, 60.0))

				elif step_type == SapProcessStep.TYPE_SAP_KEY_PRESS:
					ok, payload = _ensure_session_ready()
					if not ok:
						return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

					combo_text = str(cfg.get('combo_text', '') or '').strip()
					key_name = str(cfg.get('key_name', '') or '').strip()
					use_ctrl = bool(cfg.get('use_ctrl', False))
					use_alt = bool(cfg.get('use_alt', False))
					use_shift = bool(cfg.get('use_shift', False))
					use_win = bool(cfg.get('use_win', False))
					try:
						repeat_count = int(cfg.get('repeat_count') or 1)
					except (TypeError, ValueError):
						repeat_count = 1
					repeat_count = max(1, min(repeat_count, 20))
					try:
						delay_between_ms = int(cfg.get('delay_between_ms') or 120)
					except (TypeError, ValueError):
						delay_between_ms = 120
					delay_between_ms = max(0, min(delay_between_ms, 5000))

					last_combo = ''
					for r in range(repeat_count):
						ok_key, key_msg = _send_sap_hotkey(
							service,
							combo_text=combo_text,
							key=key_name,
							use_ctrl=use_ctrl,
							use_alt=use_alt,
							use_shift=use_shift,
							use_win=use_win,
						)
						if not ok_key:
							if continue_on_error:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Tuş gönderimi hatası (devam): {key_msg}'})
								break
							return JsonResponse({'ok': False, 'error': f'Tuş gönderimi hatası: {key_msg}', 'logs': logs, 'failed_at': i}, status=500)
						last_combo = key_msg
						if r < repeat_count - 1 and delay_between_ms > 0:
							time.sleep(delay_between_ms / 1000.0)

					if last_combo:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Tuş gönderildi: {last_combo} | tekrar: {repeat_count}'})

				elif step_type == SapProcessStep.TYPE_SAP_SELECT_OPTION:
					ok, payload = _ensure_session_ready()
					if not ok:
						return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

					element_id = _normalize_session_element_id(cfg.get('element_id', ''))
					select_mode = str(cfg.get('select_mode', 'auto') or 'auto').strip().casefold()
					wait_timeout_sec = max(1, min(int(cfg.get('wait_timeout_sec') or 20), 60))
					obj = service._wait_for_element(service.session, element_id, timeout_sec=wait_timeout_sec)
					if not obj:
						return JsonResponse({'ok': False, 'error': f'Secim alanı bulunamadı: {element_id}', 'logs': logs, 'failed_at': i}, status=404)

					obj_type = str(getattr(obj, 'Type', '') or '').casefold()
					is_checkbox = ('checkbox' in obj_type) or ('/chk' in element_id.casefold())
					is_radio = ('radiobutton' in obj_type) or ('/rad' in element_id.casefold())

					if is_checkbox:
						if select_mode in ('toggle', 'auto'):
							obj.selected = not bool(getattr(obj, 'selected', False))
						elif select_mode in ('set_on', 'check', 'true'):
							obj.selected = True
						elif select_mode in ('set_off', 'uncheck', 'false'):
							obj.selected = False
						else:
							obj.selected = not bool(getattr(obj, 'selected', False))
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Checkbox uygulandı: {element_id} | mod: {select_mode}'})
					elif is_radio:
						try:
							obj.select()
						except Exception:
							try:
								obj.selected = True
							except Exception:
								obj.setFocus()
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Radio seçildi: {element_id}'})
					else:
						try:
							obj.select()
						except Exception:
							try:
								obj.selected = True
							except Exception:
								obj.setFocus()
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Secim uygulandı: {element_id}'})

					service._wait_until_idle(service.session, timeout_sec=5)

				elif step_type == SapProcessStep.TYPE_SAP_FILL_INPUT:
					ok, payload = _ensure_session_ready()
					if not ok:
						return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

					element_id = _normalize_session_element_id(cfg.get('element_id', ''))
					value_source = str(cfg.get('value_source', 'static') or 'static').strip().casefold()
					value_text = str(cfg.get('value_text', '') or '')
					if value_source == 'excel_column':
						ok_excel, excel_value, excel_msg = _resolve_fill_input_excel_value(cfg, runtime_state)
						if not ok_excel:
							return JsonResponse({'ok': False, 'error': f'Excel değeri alınamadı: {excel_msg}', 'logs': logs, 'failed_at': i}, status=400)
						value_text = excel_value
						_runtime_push_log(process_id, f'{step_name}: {excel_msg}')
						# Excel'den okunan input değerini raporlama için biriktir
						_col_ref = str(cfg.get('excel_column', '') or cfg.get('column_ref', '') or '')
						runtime_state.setdefault('_current_row_filled', []).append({
							'alan': str(element_id or ''),
							'kaynak': f'excel({_col_ref})',
							'deger': str(excel_value or ''),
						})
					wait_timeout_sec = max(1, min(int(cfg.get('wait_timeout_sec') or 20), 60))
					obj = service._wait_for_element(service.session, element_id, timeout_sec=wait_timeout_sec)
					if not obj:
						return JsonResponse({'ok': False, 'error': f'Input alanı bulunamadı: {element_id}', 'logs': logs, 'failed_at': i}, status=404)

					ok_fill, fill_msg = fill_popup_input_value(obj, value_text)
					if not ok_fill:
						return JsonResponse({'ok': False, 'error': f'Input doldurulamadı: {element_id} | {fill_msg}', 'logs': logs, 'failed_at': i}, status=500)

					# Export diyalogunda (DY_PATH / DY_FILENAME) dosya zaten varsa önceden sil,
					# böylece "already exists" onay popup'ı açılmadan yazma devam eder.
					element_id_norm = str(element_id or '').casefold()
					filled_value = str(value_text or '').strip()
					if element_id_norm.endswith('/ctxtdy_path') or '/ctxtdy_path' in element_id_norm:
						runtime_state['_sap_export_path'] = filled_value
					if element_id_norm.endswith('/ctxtdy_filename') or '/ctxtdy_filename' in element_id_norm:
						runtime_state['_sap_export_filename'] = filled_value

					export_path = str(runtime_state.get('_sap_export_path') or '').strip()
					export_name = str(runtime_state.get('_sap_export_filename') or '').strip()
					if export_name and (
						element_id_norm.endswith('/ctxtdy_filename')
						or '/ctxtdy_filename' in element_id_norm
						or element_id_norm.endswith('/ctxtdy_path')
						or '/ctxtdy_path' in element_id_norm
					):
						candidate = export_name if os.path.isabs(export_name) else (os.path.join(export_path, export_name) if export_path else '')
						candidate = os.path.normpath(os.path.expandvars(os.path.expanduser(candidate))) if candidate else ''
						if candidate:
							try:
								if os.path.isfile(candidate):
									os.remove(candidate)
									del_msg = f'Mevcut dosya silindi (overwrite için): {candidate}'
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': del_msg})
									_runtime_push_log(process_id, f'{step_name}: {del_msg}')
							except Exception as del_ex:
								warn_msg = f'Mevcut dosya silinemedi, popup ile devam edilecek: {candidate} | {del_ex}'
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': warn_msg})
								_runtime_push_log(process_id, f'{step_name}: {warn_msg}')
					service._wait_until_idle(service.session, timeout_sec=5)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Input dolduruldu: {element_id} = {value_text}'})

				elif step_type == SapProcessStep.TYPE_CONVERT_SAP_EXPORT:
					input_path = str(cfg.get('input_path', '') or '').strip()
					output_path = str(cfg.get('output_path', '') or '').strip()
					delimiter = str(cfg.get('delimiter', '\\t') or '\\t')
					encodings = str(cfg.get('encodings', 'utf-16,utf-16-le,cp1254,latin-1,utf-8') or 'utf-16,utf-16-le,cp1254,latin-1,utf-8').strip()
					drop_top_rows = max(0, int(cfg.get('drop_top_rows') or 0))
					drop_left_cols = max(0, int(cfg.get('drop_left_cols') or 0))
					drop_rows = str(cfg.get('drop_rows', '') or '').strip()
					drop_cols = str(cfg.get('drop_cols', '') or '').strip()
					skip_empty_lines = _as_bool(cfg.get('skip_empty_lines', True), True)
					trim_cells = _as_bool(cfg.get('trim_cells', True), True)
					strip_quotes = _as_bool(cfg.get('strip_quotes', True), True)

					if not input_path:
						msg = 'Dönüştürme için input_path zorunludur.'
						if continue_on_error:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': msg})
							continue
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)

					# SAP dosyasını yazmasını bekle (max 15 saniye)
					_file_wait_deadline = time.time() + 15
					_file_ready = False
					_last_size = -1
					_stable_count = 0
					while time.time() < _file_wait_deadline:
						try:
							if os.path.isfile(input_path):
								_cur_size = os.path.getsize(input_path)
								if _cur_size > 0 and _cur_size == _last_size:
									_stable_count += 1
									if _stable_count >= 2:
										_file_ready = True
										break
								else:
									_stable_count = 0
								_last_size = _cur_size
						except OSError:
							pass
						time.sleep(0.5)
					if not _file_ready:
						msg = f'SAP export dosyası 15sn içinde stabil olmadı: {input_path}'
						_runtime_push_log(process_id, f'{step_name}: {msg}')
						if continue_on_error:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': msg})
							continue
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=404)

					_runtime_push_log(process_id, f'{step_name}: dönüştürme başlıyor: {input_path}')
					# In-process dönüştürme (subprocess Windows + ağ sürücüsünde bloklayabiliyor)
					try:
						from core.management.commands.convert_sap_export import (
							_decode_escapes as _conv_decode,
							_parse_index_spec as _conv_parse_idx,
							_read_text_with_fallback as _conv_read,
							_remove_noise_rows as _conv_remove_noise_rows,
							_write_xlsx as _conv_write,
						)
						from pathlib import Path as _ConvPath
						_in_path = _ConvPath(input_path).expanduser().resolve()
						if output_path:
							_out_path = _ConvPath(output_path).expanduser().resolve()
						else:
							_out_path = _in_path.with_suffix('.xlsx')
						_delim = _conv_decode(delimiter or '\\t')
						_encs = [x.strip() for x in (encodings or '').split(',') if x.strip()] or ['utf-16','cp1254','latin-1','utf-8']
						_drop_rows_set = _conv_parse_idx(drop_rows)
						_drop_cols_set = _conv_parse_idx(drop_cols)
						_raw_text, _used_enc = _conv_read(_in_path, _encs)
						_raw_lines = _raw_text.splitlines()
						_rows = []
						_max_cols = 0
						for _line in _raw_lines:
							if skip_empty_lines and (not str(_line or '').strip()):
								continue
							_parts = str(_line).split(_delim)
							if trim_cells:
								_parts = [p.strip() for p in _parts]
							if strip_quotes:
								_parts = [p.replace('"', '') for p in _parts]
							_rows.append(_parts)
							if len(_parts) > _max_cols:
								_max_cols = len(_parts)
						if not _rows:
							raise RuntimeError('Okunan veri boÅŸ.')
						for _r in _rows:
							if len(_r) < _max_cols:
								_r.extend([''] * (_max_cols - len(_r)))
						if drop_top_rows > 0:
							_rows = _rows[drop_top_rows:]
						if drop_left_cols > 0:
							_rows = [r[drop_left_cols:] if len(r) > drop_left_cols else [] for r in _rows]
						if _drop_rows_set:
							_rows = [r for idx, r in enumerate(_rows) if idx not in _drop_rows_set]
						if _drop_cols_set:
							_rows = [[c for idx, c in enumerate(r) if idx not in _drop_cols_set] for r in _rows]
						_rows = _conv_remove_noise_rows(_rows)
						if not _rows:
							raise RuntimeError('Temizlikten sonra veri kalmadı.')
						_out_path.parent.mkdir(parents=True, exist_ok=True)
						_conv_write(_out_path, _rows)
						_conv_msg = f'Donusum tamamlandi | enc={_used_enc} | satir={len(_rows)} | sutun={max((len(r) for r in _rows), default=0)}'
					except Exception as conv_ex:
						msg = f'SAP export dönüştürme başarısız: {conv_ex}'
						_runtime_push_log(process_id, f'{step_name}: {msg}')
						if continue_on_error:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': msg})
							continue
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=500)

					msg = f'SAP export dönüştürüldü: {input_path} -> {_out_path} | {_conv_msg}'
					_runtime_push_log(process_id, f'{step_name}: {msg}')
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': msg})

				elif step_type == SapProcessStep.TYPE_WINDOWS_SCAN_DIALOGS:
					# Diagnostic: tüm açık Windows popup'larını tara ve logla
					title_filter = str(cfg.get('title_filter', '') or '').strip()
					scan_timeout_sec = max(1, min(int(cfg.get('scan_timeout_sec') or 10), 60))
					import time as _time_mod
					scan_msg = f'Windows popup tanı taraması başlıyor... (filter="{title_filter or "*"}", timeout={scan_timeout_sec}s)'
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': scan_msg})
					_runtime_push_log(process_id, f'{step_name}: {scan_msg}')

					deadline = _time_mod.time() + scan_timeout_sec
					found_any = False
					while _time_mod.time() < deadline:
						dialogs = scan_visible_dialogs(title_filter=title_filter)
						if dialogs:
							found_any = True
							break
						_time_mod.sleep(0.3)

					if not dialogs:
						no_result_msg = f'Hiç Windows popup bulunamadı (filter="{title_filter or "*"}", {scan_timeout_sec}s beklendi)'
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': no_result_msg})
						_runtime_push_log(process_id, f'{step_name}: {no_result_msg}')
					else:
						for dlg in dialogs:
							dlg_title = dlg.get('title', '?')
							dlg_hwnd = dlg.get('hwnd', '?')
							dlg_cls = dlg.get('class_name', '')
							btns = [b.get('text', '') for b in dlg.get('buttons', []) if b.get('text')]
							chks = [c.get('text', '') for c in dlg.get('checkboxes', []) if c.get('text')]
							rads = [r.get('text', '') for r in dlg.get('radios', []) if r.get('text')]
							inps = [inp.get('text', inp.get('class_name', '')) for inp in dlg.get('inputs', [])]
							detail_parts = []
							if btns:
								detail_parts.append(f'Butonlar: {btns}')
							if chks:
								detail_parts.append(f'Checkbox: {chks}')
							if rads:
								detail_parts.append(f'Radio: {rads}')
							if inps:
								detail_parts.append(f'Input: {inps}')
							detail = ' | '.join(detail_parts) if detail_parts else '(kontrol yok)'
							dlg_msg = f'DIALOG BULUNDU: hwnd={dlg_hwnd} class="{dlg_cls}" title="{dlg_title}" => {detail}'
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': dlg_msg})
							_runtime_push_log(process_id, f'{step_name}: {dlg_msg}')

				elif step_type == SapProcessStep.TYPE_WINDOWS_DIALOG_ACTION:
					window_title = str(cfg.get('window_title', '') or '').strip()
					button_text = str(cfg.get('button_text', '') or '').strip()
					checkbox_text = str(cfg.get('checkbox_text', '') or '').strip()
					if '?' in window_title and 'SAP' in window_title.upper():
						# Bozuk karakter içeren SAP GUI başlığı için genel eşleşme
						window_title = 'SAP GUI'
					title_match_mode = str(cfg.get('title_match_mode', 'contains') or 'contains').strip().casefold()
					button_match_mode = str(cfg.get('button_match_mode', 'contains') or 'contains').strip().casefold()
					checkbox_match_mode = str(cfg.get('checkbox_match_mode', 'contains') or 'contains').strip().casefold()
					apply_checkbox = _as_bool(cfg.get('apply_checkbox', False))
					checkbox_state_raw = cfg.get('checkbox_state', True)
					checkbox_state = _as_bool(checkbox_state_raw, True)
					# "Kararımı hatırla" benzeri akışlarda popup bir kez çıktıktan sonra tekrar gelmeyebilir.
					# Bu durumda adımın süreci kırmaması için not-found durumunu opsiyonel başarı kabul et.
					allow_not_found = _as_bool(cfg.get('allow_not_found', True), True)
					timeout_sec = max(1, min(int(cfg.get('timeout_sec') or 25), 120))
					poll_ms = max(50, min(int(cfg.get('poll_ms') or 250), 5000))
					ready_delay_ms = max(0, min(int(cfg.get('ready_delay_ms') or 350), 5000))

					if not window_title:
						msg = 'Windows popup başlığı boş bırakılamaz.'
						if continue_on_error:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': msg})
							continue
						return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)

					if not apply_checkbox:
						checkbox_text = ''

					wait_msg = f'Windows popup bekleniyor: {window_title} | timeout={timeout_sec}s'
					if checkbox_text:
						wait_msg = f'{wait_msg} | kontrol={checkbox_text}'
					if button_text:
						wait_msg = f'{wait_msg} | buton={button_text}'
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': wait_msg})
					_runtime_push_log(process_id, f'{step_name}: {wait_msg}')

					_popup_progress_state = {'last_remaining': None, 'last_status': ''}

					def _popup_progress(payload):
						if not isinstance(payload, dict):
							return
						remaining = payload.get('remaining_sec')
						status = str(payload.get('status', '') or '')
						if status == 'searching':
							if remaining == _popup_progress_state['last_remaining']:
								return
							_popup_progress_state['last_remaining'] = remaining
							_runtime_push_log(process_id, f'{step_name}: popup aranıyor... kalan ~{remaining}s')
						elif status == 'found' and _popup_progress_state['last_status'] != 'found':
							_popup_progress_state['last_status'] = 'found'
							title = str(payload.get('title', '') or window_title)
							_runtime_push_log(process_id, f'{step_name}: popup bulundu: {title}')

					dialog_kwargs = {
						'window_title': window_title,
						'button_text': button_text,
						'checkbox_text': checkbox_text,
						'checkbox_state': checkbox_state,
						'title_match_mode': title_match_mode,
						'button_match_mode': button_match_mode,
						'checkbox_match_mode': checkbox_match_mode,
						'allow_control_fallback': True,
						'timeout_sec': timeout_sec,
						'poll_ms': poll_ms,
						'ready_delay_ms': ready_delay_ms,
					}

					ok_dialog = False
					dialog_msg = 'Windows popup işlemi başlatılamadı.'
					worker_proc = None
					try:
						worker_script = os.path.join(os.path.dirname(__file__), 'windows_dialog_worker.py')
						worker_cmd = [
							sys.executable,
							worker_script,
							json.dumps(dialog_kwargs, ensure_ascii=False),
						]
						worker_proc = subprocess.Popen(
							worker_cmd,
							stdout=subprocess.PIPE,
							stderr=subprocess.PIPE,
							text=True,
						)

						worker_deadline = time.time() + timeout_sec + 4
						last_remain = None
						while time.time() < worker_deadline:
							if worker_proc is not None and worker_proc.poll() is not None:
								out, err = worker_proc.communicate(timeout=0.2)
								parsed = None
								try:
									parsed = json.loads(str(out or '').strip() or '{}')
								except Exception:
									parsed = None
								if isinstance(parsed, dict):
									ok_dialog = bool(parsed.get('ok'))
									dialog_msg = str(parsed.get('msg') or '').strip()
								else:
									ok_dialog = False
									dialog_msg = str(err or out or 'Windows popup worker çıktısı okunamadı.').strip()
								break

							remain = max(0, int(round(worker_deadline - time.time())))
							if remain != last_remain:
								last_remain = remain
								_popup_progress({'remaining_sec': remain, 'status': 'searching'})
							time.sleep(0.2)

						if not ok_dialog and (not dialog_msg):
							dialog_msg = 'Windows popup worker zaman aşımı veya yanıt vermedi.'
					except Exception as worker_ex:
							ok_dialog = False
							dialog_msg = f'Windows popup worker başlatılamadı: {worker_ex}'
					finally:
						try:
							if worker_proc is not None and worker_proc.poll() is None:
								worker_proc.terminate()
								worker_proc.wait(timeout=1)
						except Exception:
							pass
					if not ok_dialog:
						dialog_msg_n = str(dialog_msg or '').strip().casefold()
						dialog_not_found = (
							('dialog bulunamadi' in dialog_msg_n)
							or ('dialog bulunamadi.' in dialog_msg_n)
							or ('dialog bulunamadı' in dialog_msg_n)
							or ('dialog bulunamadı.' in dialog_msg_n)
							or ('dialog not found' in dialog_msg_n)
						)
						if dialog_not_found and allow_not_found:
							skip_msg = f'Popup bulunamadı, adım opsiyonel kabul edildi: {window_title}'
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': skip_msg})
							_runtime_push_log(process_id, f'{step_name}: {skip_msg}')
							continue
						_runtime_push_log(process_id, f'{step_name}: Windows popup işlemi başarısız: {dialog_msg}')
						if continue_on_error:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Windows popup işlemi başarısız (devam): {dialog_msg}'})
							continue
						return JsonResponse({'ok': False, 'error': f'Windows popup işlemi başarısız: {dialog_msg}', 'logs': logs, 'failed_at': i}, status=500)

					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': dialog_msg})
					_runtime_push_log(process_id, f'{step_name}: {dialog_msg}')

				elif step_type == SapProcessStep.TYPE_SAP_PRESS_BUTTON:
					ok, payload = _ensure_session_ready()
					if not ok:
						return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)
					next_active_i = next_i
					while next_active_i < len(steps):
						_candidate_step = steps[next_active_i] if isinstance(steps[next_active_i], dict) else {}
						_candidate_cfg = _candidate_step.get('config', {}) if isinstance(_candidate_step.get('config'), dict) else {}
						if bool(_candidate_cfg.get('disabled', False)):
							next_active_i += 1
							continue
						break
					next_step_type = ''
					if next_active_i < len(steps):
						next_step_type = str(steps[next_active_i].get('step_type', '') or '').strip()
					windows_handoff_types = {
						SapProcessStep.TYPE_WINDOWS_DIALOG_ACTION,
						SapProcessStep.TYPE_WINDOWS_SCAN_DIALOGS,
					}
					handoff_to_windows_dialog = (next_step_type in windows_handoff_types)
					raw_button_id = str(cfg.get('button_id', '') or '').strip()
					button_id = _normalize_session_element_id(raw_button_id)
					wait_timeout_sec = max(1, min(int(cfg.get('wait_timeout_sec') or 25), 60))
					_runtime_push_log(process_id, f'{step_name}: buton adımı başlıyor | hedef={button_id or raw_button_id} | sonraki={next_step_type or "-"}')
					ctx_cmd = _parse_toolbar_context_command(raw_button_id)
					if ctx_cmd:
						shell = service._wait_for_element(service.session, ctx_cmd['shell_id'], timeout_sec=wait_timeout_sec)
						if not shell:
							return JsonResponse({'ok': False, 'error': f'Context shell bulunamadı: {ctx_cmd["shell_id"]}', 'logs': logs, 'failed_at': i}, status=404)
						if ctx_cmd.get('command'):
							try:
								shell.pressToolbarContextButton(ctx_cmd['command'])
							except Exception as ex_ctx:
								return JsonResponse({'ok': False, 'error': f'Context toolbar komutu çalıştırılamadı ({ctx_cmd["command"]}): {ex_ctx}', 'logs': logs, 'failed_at': i}, status=500)
						if ctx_cmd.get('menu_item'):
							try:
								shell.selectContextMenuItem(ctx_cmd['menu_item'])
							except Exception as ex_item:
								return JsonResponse({'ok': False, 'error': f'Context menu seçimi yapılamadı ({ctx_cmd["menu_item"]}): {ex_item}', 'logs': logs, 'failed_at': i}, status=500)
						if not handoff_to_windows_dialog:
							_wait_until_idle_or_popup(timeout_sec=min(wait_timeout_sec, 30))
						ctx_msg = f'Context komutu uygulandı ({ctx_cmd["shell_id"]})'
						if ctx_cmd.get('command'):
							ctx_msg = f'{ctx_msg}: {ctx_cmd["command"]}'
						if ctx_cmd.get('menu_item'):
							ctx_msg = f'{ctx_msg} -> {ctx_cmd["menu_item"]}'
						wait_state = ''
						if handoff_to_windows_dialog:
							skip_step_end_auto_close = True
							ctx_msg = f'{ctx_msg} | windows popup adımına hızlı geçiş'
						else:
							_, wait_state = _wait_until_idle_or_popup(timeout_sec=1)
							if wait_state == 'popup_detected':
								ctx_msg = f'{ctx_msg} | popup algılandı, sonraki adıma geçiliyor'
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': ctx_msg})
					else:
						button = service._wait_for_element(service.session, button_id, timeout_sec=wait_timeout_sec)
						if not button:
							return JsonResponse({'ok': False, 'error': f'Buton bulunamadı: {button_id}', 'logs': logs, 'failed_at': i}, status=404)
						if handoff_to_windows_dialog:
							# SAP COM senkron: button.press() Windows güvenlik popup açılınca bloklar.
							# Çözüm: önce popup watcher subprocess'ini başlat, sonra button.press() çağır.
							# press() bloke olurken subprocess popup'ı bulur ve kapatır → press() unblock olur.
							next_step_cfg = steps[next_active_i].get('config', {}) if next_active_i < len(steps) else {}
							if not isinstance(next_step_cfg, dict):
								next_step_cfg = {}
							watcher_window_title = str(next_step_cfg.get('window_title', '') or '').strip()
							watcher_button_text  = str(next_step_cfg.get('button_text', '') or '').strip()
							watcher_checkbox_text = str(next_step_cfg.get('checkbox_text', '') or '').strip()
							watcher_apply_chk     = _as_bool(next_step_cfg.get('apply_checkbox', False))
							watcher_chk_state     = _as_bool(next_step_cfg.get('checkbox_state', True), True)
							watcher_timeout       = max(15, min(int(next_step_cfg.get('timeout_sec') or 30), 120))
							if '?' in watcher_window_title and 'SAP' in watcher_window_title.upper():
								watcher_window_title = 'SAP GUI'
							if not watcher_apply_chk:
								watcher_checkbox_text = ''
							watcher_kwargs = {
								'window_title':     watcher_window_title or 'SAP GUI',
								'button_text':      watcher_button_text,
								'checkbox_text':    watcher_checkbox_text,
								'checkbox_state':   watcher_chk_state,
								'title_match_mode': str(next_step_cfg.get('title_match_mode', 'contains') or 'contains').strip().casefold(),
								'button_match_mode': str(next_step_cfg.get('button_match_mode', 'contains') or 'contains').strip().casefold(),
								'checkbox_match_mode': str(next_step_cfg.get('checkbox_match_mode', 'contains') or 'contains').strip().casefold(),
								'allow_control_fallback': True,
								'timeout_sec':      watcher_timeout,
								'poll_ms':          max(50, min(int(next_step_cfg.get('poll_ms') or 250), 2000)),
								'ready_delay_ms':   max(0,  min(int(next_step_cfg.get('ready_delay_ms') or 300), 3000)),
							}
							worker_script = os.path.join(os.path.dirname(__file__), 'windows_dialog_worker.py')
							watcher_proc = subprocess.Popen(
								[sys.executable, worker_script, json.dumps(watcher_kwargs, ensure_ascii=False)],
								stdout=subprocess.PIPE,
								stderr=subprocess.PIPE,
								text=True,
							)
							_runtime_push_log(process_id, f'{step_name}: popup watcher başlatıldı ({watcher_kwargs["window_title"]}), şimdi butona basılıyor...')
							# Şimdi button.press() / menu.select() çağır — popup gelince subprocess kapatır, bu döner
							try:
								_invoke_button_or_menu(button, button_id)
							except Exception as _press_ex:
								_runtime_push_log(process_id, f'{step_name}: press()/select() exception: {_press_ex}')
							# press() döndü (popup kapandı veya hata), subprocess sonucunu oku
							try:
								watcher_parsed = None
								quick_deadline = time.time() + 2.5
								while time.time() < quick_deadline:
									if watcher_proc.poll() is not None:
										watcher_out, watcher_err = watcher_proc.communicate(timeout=0.2)
										watcher_parsed = json.loads(str(watcher_out or '').strip() or '{}')
										break
									time.sleep(0.1)
								if watcher_parsed is None:
									try:
										watcher_proc.terminate()
									except Exception:
										pass
									watcher_parsed = {'ok': False, 'msg': 'Dialog bulunamadı.'}
							except Exception:
								watcher_parsed = {'ok': False, 'msg': 'Dialog bulunamadı.'}
								try:
									watcher_proc.terminate()
								except Exception:
									pass
							watcher_ok  = bool(watcher_parsed.get('ok'))
							watcher_msg = str(watcher_parsed.get('msg') or '').strip() or 'watcher sonuç yok'
							watcher_msg_n = str(watcher_msg or '').strip().casefold()
							watcher_not_found = (
								('dialog bulunamadi' in watcher_msg_n)
								or ('dialog bulunamadi.' in watcher_msg_n)
								or ('dialog bulunamadı' in watcher_msg_n)
								or ('dialog bulunamadı.' in watcher_msg_n)
								or ('dialog not found' in watcher_msg_n)
							)
							skip_step_end_auto_close = True
							msg = f'Butona basıldı: {button_id} | popup watcher: {"OK" if watcher_ok else "FAIL"} | {watcher_msg}'
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': msg})
							_runtime_push_log(process_id, f'{step_name}: {msg}')
							# Handoff modunda watcher popup'ı paralel ele alır.
							# press() döndüyse aynı popup için ayrı windows_dialog_action bekletmesine girme.
							if next_step_type == SapProcessStep.TYPE_WINDOWS_DIALOG_ACTION:
								next_i = next_active_i + 1  # windows_dialog_action adımını atla
								_runtime_push_log(process_id, f'{step_name}: handoff tamamlandı, windows_dialog_action adımı atlanıyor')
						else:
							_invoke_button_or_menu(button, button_id)
							wait_state = ''
							_, wait_state = _wait_until_idle_or_popup(timeout_sec=min(wait_timeout_sec, 30))
							_action_word = 'Menü seçildi' if _is_menu_target(button, button_id) else 'Butona basıldı'
							msg = f'{_action_word}: {button_id}'
							if wait_state == 'popup_detected':
								msg = f'{msg} | popup algılandı, popup adımına geçiliyor'
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': msg})

					explicit_target_idx = _resolve_step_target_index(
						steps,
						cfg,
						step_no_key='next_step_no',
						step_id_key='next_step_id',
					)
					if explicit_target_idx is not None:
						next_i = explicit_target_idx
						logs.append({
							'step': i + 1,
							'type': step_type,
							'label': step_name,
							'ok': True,
							'msg': f'Buton sonrası yönlendirme aktif: hedef adım {explicit_target_idx + 1}'
						})
						_runtime_push_log(process_id, f'{step_name}: buton sonrası hedef adım {explicit_target_idx + 1}')

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
					elif action == 'select_radio_id':
						radio_id = _normalize_session_element_id(cfg.get('popup_radio_id', ''))
						radio = service._wait_for_element(service.session, radio_id, timeout_sec=5)
						if not radio:
							return JsonResponse({'ok': False, 'error': f'Popup radio bulunamadı: {radio_id}', 'logs': logs, 'failed_at': i}, status=404)
						ok_radio, radio_msg = select_popup_radio_by_id(radio)
						if not ok_radio:
							return JsonResponse({'ok': False, 'error': f'Popup radio seçilemedi: {radio_id} | {radio_msg}', 'logs': logs, 'failed_at': i}, status=500)
					elif action == 'fill_input_id':
						input_id = _normalize_session_element_id(cfg.get('popup_input_id', ''))
						input_value = str(cfg.get('popup_input_value', '') or '')
						popup_input = service._wait_for_element(service.session, input_id, timeout_sec=5)
						if not popup_input:
							return JsonResponse({'ok': False, 'error': f'Popup input bulunamadı: {input_id}', 'logs': logs, 'failed_at': i}, status=404)
						ok_input, input_msg = fill_popup_input_value(popup_input, input_value)
						if not ok_input:
							return JsonResponse({'ok': False, 'error': f'Popup input doldurulamadı: {input_id} | {input_msg}', 'logs': logs, 'failed_at': i}, status=500)
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
						target_idx = _resolve_step_target_index(
							steps,
							cfg,
							step_no_key='popup_target_step',
							step_id_key='popup_target_step_id',
						)
						if target_idx is not None:
							next_i = target_idx
					elif on_match_action == 'press_button':
						btn_id_raw = str(cfg.get('popup_next_button_id', '') or '').strip()
						btn_id = _normalize_session_element_id(btn_id_raw)
						if not btn_id:
							return JsonResponse({'ok': False, 'error': 'Popup sonrası basılacak buton ID boş.', 'logs': logs, 'failed_at': i}, status=400)
						btn = service._wait_for_element(service.session, btn_id, timeout_sec=8)
						if not btn:
							return JsonResponse({'ok': False, 'error': f'Popup sonrası buton bulunamadı: {btn_id}', 'logs': logs, 'failed_at': i}, status=404)
						try:
							btn.press()
						except Exception as ex_btn:
							return JsonResponse({'ok': False, 'error': f'Popup sonrası butona basılamadı ({btn_id}): {ex_btn}', 'logs': logs, 'failed_at': i}, status=500)
						service._wait_until_idle(service.session, timeout_sec=10)
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Popup sonrası butona basıldı: {btn_id}'})
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
								target_idx = _resolve_step_target_index(
									steps,
									cfg,
									step_no_key='timeout_target_step',
									step_id_key='timeout_target_step_id',
								)
								if target_idx is not None:
									next_i = target_idx
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, {target_idx + 1}. adıma dönüldü: {cfg.get("screen_title", "")}'})
								else:
									logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Ekran gelmedi, hedef adım bulunamadı: {cfg.get("screen_title", "")}'})
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
						preview = 'liste boÅŸ'
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

				elif step_type == SapProcessStep.TYPE_SHOW_MESSAGE:
					msg_title = str(cfg.get('title', '') or '').strip() or 'Bilgi'
					msg_body = str(cfg.get('message', '') or '').strip() or 'Devam etmek için Tamam butonuna basın.'
					overlay.push_log(f'Mesaj gösteriliyor: {msg_title}')
					msg_ok, msg_err = overlay.show_message(msg_title, msg_body)
					if not msg_ok:
						return JsonResponse({'ok': False, 'error': msg_err, 'logs': logs, 'failed_at': i}, status=500)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'Mesaj gösterildi ve onaylandı: {msg_title}'})

				elif step_type == SapProcessStep.TYPE_EXCEL_LOOP_NEXT:
					advanced, excel_msg, target_idx = _advance_excel_loop_runtime(steps, runtime_state, cfg)
					# Yeni satıra geçildiğinde doldurma geçmişini sıfırla
					runtime_state['_current_row_filled'] = []
					if advanced:
						next_i = target_idx
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': excel_msg})
					else:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': excel_msg})

				elif step_type == SapProcessStep.TYPE_EXCEL_ROW_LOG:
					row_status = str(cfg.get('status', '') or 'ok').strip().lower() or 'ok'
					row_reason = _resolve_placeholders(str(cfg.get('reason', '') or '').strip(), runtime_state)
					row_entry = {
						'cari': str(runtime_state.get('loop_value', '') or ''),
						'excel_row': (runtime_state.get('excel_loop_index', 0) or 0) + 1,
						'status': row_status,
						'reason': row_reason,
						'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
						'filled_data': list(runtime_state.get('_current_row_filled') or []),
					}
					runtime_state.setdefault('row_results', []).append(row_entry)
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True,
						'msg': f'Satır sonucu yazıldı → Cari: {row_entry["cari"]}, Satır: {row_entry["excel_row"]}, Durum: {row_status.upper()}, Neden: {row_reason or "-"}'})
					overlay.push_log(f'Satır kaydedildi: {row_entry["cari"]} / {row_entry["excel_row"]} → {row_status.upper()}')

				elif step_type == SapProcessStep.TYPE_SEND_REPORT_MAIL:
					row_results = runtime_state.get('row_results', [])
					output_dir = str(cfg.get('output_dir', '') or '').strip()
					stamp_now = datetime.now().strftime('%Y%m%d_%H%M%S')
					output_path = None
					if output_dir:
						import os as _os_r
						_os_r.makedirs(output_dir, exist_ok=True)
						output_path = _os_r.path.join(output_dir, f'rapor_{stamp_now}.xlsx')
					try:
						xlsx_path = _generate_row_report_xlsx(row_results, output_path=output_path)
					except Exception as _xe:
						err_msg = f'Rapor xlsx üretilemedi: {_xe}'
						if continue_on_error:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': err_msg})
						else:
							return JsonResponse({'ok': False, 'error': err_msg, 'logs': logs, 'failed_at': i}, status=500)
					else:
						logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True,
							'msg': f'Rapor xlsx oluşturuldu: {xlsx_path} ({len(row_results)} satır)'})
						overlay.push_log(f'Rapor oluÅŸturuldu: {xlsx_path}')
						runtime_state['last_report_xlsx'] = xlsx_path

						mail_id = cfg.get('mail_account_id')
						if mail_id:
							_mail_acc = MailAccount.objects.filter(pk=mail_id, is_active=True).first()
							if _mail_acc:
								ok_count = sum(1 for r in row_results if str(r.get('status', '')).lower() == 'ok')
								err_count = sum(1 for r in row_results if str(r.get('status', '')).lower() == 'error')
								skip_count = sum(1 for r in row_results if str(r.get('status', '')).lower() == 'skip')
								_to = str(cfg.get('to', '') or '').strip() or _mail_acc.email
								_subj = _resolve_placeholders(str(cfg.get('subject', '') or '').strip(), runtime_state) \
									or f'Saggio RPA Raporu – {stamp_now}'
								_body_tpl = str(cfg.get('body', '') or '').strip() or (
									f'Merhaba,\n\nSüreç tamamlandı.\n\nToplam satır: {len(row_results)}\n'
									f'Başarılı: {ok_count}\nHatalı: {err_count}\nAtlandı: {skip_count}\n\n'
									f'Rapor ektedir.\n\nZaman: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
								)
								_body = _resolve_placeholders(_body_tpl, runtime_state)
								mail_ok, mail_msg = _send_mail_message(_mail_acc, _to, _subj, _body, attachment_path=xlsx_path)
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': mail_ok,
									'msg': f'Rapor maili → {"Gönderildi" if mail_ok else "Hata"}: {mail_msg}'})
								overlay.push_log(f'Rapor maili: {"Gönderildi" if mail_ok else "HATA – " + mail_msg}')
							else:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False,
									'msg': f'Mail hesabı bulunamadı (id={mail_id})'})

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
									
										# Column 2 ve 3'ten deÄŸerleri al
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

				elif step_type == SapProcessStep.TYPE_IF_ELSE:
					condition_type = str(cfg.get('condition_type', 'element_value') or 'element_value').strip()

					if condition_type == 'popup_exists':
						# ── Popup varlık / içerik kontrolü ──────────────────────────
						ok, payload = _ensure_session_ready()
						if not ok:
							# Oturum yoksa popup da yok
							popup_title, popup_text_raw = None, None
						else:
							popup_title, popup_text_raw = None, None
							try:
								children = getattr(service.session, 'Children', None)
								count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
								for _pidx in range(1, count):
									_wnd = None
									try:
										_wnd = children(_pidx)
									except Exception:
										try:
											_wnd = children.Item(_pidx)
										except Exception:
											pass
									if _wnd is None:
										continue
									_pid = _normalize_session_element_id(str(getattr(_wnd, 'Id', '') or '').strip())
									popup_title = str(getattr(_wnd, 'Text', '') or '').strip()
									_lt = _collect_popup_text_legacy(service.session, _pid or 'wnd[1]', limit=120)
									_mt = _collect_popup_message_text(service.session, _pid or 'wnd[1]', limit=80)
									popup_text_raw = ' | '.join(p for p in [_lt, _mt] if p)
									break  # İlk popup yeterli
							except Exception as _pe:
								overlay.push_log(f'IF/ELSE popup okuma hatası: {_pe}')

						popup_full = ' '.join(p for p in [popup_title, popup_text_raw] if p).strip()

						if _as_bool(cfg.get('save_popup_text', False)):
							runtime_state['last_popup_text'] = popup_full

						target_idx = None
						base_msg = ''
						if popup_full:
							# Kural listesini tara: ilk eşleşen kazanır
							rules = cfg.get('popup_rules') or []
							if isinstance(rules, str):
								try:
									import json as _json
									rules = _json.loads(rules)
								except Exception:
									rules = []
							matched_rule = None
							for _rule in (rules or []):
								kw = str(_rule.get('keyword', '') or '').strip()
								if not kw or kw.casefold() in popup_full.casefold():
									matched_rule = _rule
									break
							if matched_rule:
								target_idx = _resolve_rule_target_index(steps, matched_rule)
								rule_label = str(matched_rule.get('label', '') or matched_rule.get('keyword', '') or '?')
								base_msg = f'IF/ELSE Popup: "{popup_title or "?"}" → kural eşleşti: {rule_label}'
							else:
								target_idx = _resolve_step_target_index(
									steps,
									cfg,
									step_no_key='popup_nomatch_step_no',
									step_id_key='popup_nomatch_step_id',
								)
								base_msg = f'IF/ELSE Popup: açık popup var ama kural eşleşmedi ("{popup_title or "?"}")'
						else:
							target_idx = _resolve_step_target_index(
								steps,
								cfg,
								step_no_key='no_popup_step_no',
								step_id_key='no_popup_step_id',
							)
							base_msg = 'IF/ELSE Popup: Açık popup penceresi bulunamadı'

						if target_idx is None:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True,
								'msg': f'{base_msg} | hedef tanımsız, sonraki adıma geçildi'})
						else:
							next_i = target_idx
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True,
								'msg': f'{base_msg} | hedef adım: {target_idx + 1}'})
						overlay.push_log(base_msg)

					elif condition_type == 'status_message':
						ok, payload = _ensure_session_ready()
						if not ok:
							return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

						s_ok, s_text, s_type, s_err = _read_sap_statusbar(service.session)
						if not s_ok:
							msg = f'IF/ELSE status bar okunamadı: {s_err}'
							if continue_on_error:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
							else:
								return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
							continue

						runtime_state['last_status_text'] = s_text
						runtime_state['last_status_type'] = s_type

						status_category = str(cfg.get('status_category', 'any') or 'any').strip().casefold()
						needle = str(cfg.get('status_text_contains', '') or '').strip().casefold()
						msg_fold = str(s_text or '').casefold()

						cat_ok = True
						if status_category == 'positive':
							cat_ok = (s_type in ('S',))
						elif status_category == 'negative':
							cat_ok = (s_type in ('E', 'A'))
						elif status_category == 'info':
							cat_ok = (s_type in ('W', 'I'))

						text_ok = (not needle) or (needle in msg_fold)
						matched = bool(cat_ok and text_ok)

						if matched:
							target_idx = _resolve_step_target_index(
								steps,
								cfg,
								step_no_key='status_match_step_no',
								step_id_key='status_match_step_id',
							)
							base_msg = f'IF/ELSE Status: [{s_type or "?"}] {s_text} | eÅŸleÅŸti'
						else:
							target_idx = _resolve_step_target_index(
								steps,
								cfg,
								step_no_key='status_nomatch_step_no',
								step_id_key='status_nomatch_step_id',
							)
							base_msg = f'IF/ELSE Status: [{s_type or "?"}] {s_text} | eÅŸleÅŸmedi'

						if target_idx is None:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{base_msg} | hedef tanımsız, sonraki adıma geçildi'})
						else:
							next_i = target_idx
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{base_msg} | hedef adım: {target_idx + 1}'})
						overlay.push_log(base_msg)

					else:
						# ── Mevcut: SAP alan değeri sayısal karşılaştırması ─────────
						ok, payload = _ensure_session_ready()
						if not ok:
							return JsonResponse({'ok': False, 'error': payload, 'logs': logs, 'failed_at': i}, status=500)

						element_id = str(cfg.get('element_id', '') or '').strip()
						if not element_id:
							msg = 'IF/ELSE için element_id zorunlu.'
							if continue_on_error:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
							else:
								return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
							continue

						try:
							threshold = _parse_decimal_text(cfg.get('threshold', '1'))
						except Exception:
							threshold = Decimal('1')

						read_ok, raw_value, read_err = _read_sap_element_text(service.session, element_id)
						if not read_ok:
							msg = f'IF/ELSE alan okuma hatasi: {read_err}'
							if continue_on_error:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
							else:
								return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
							continue

						try:
							numeric_value = _parse_decimal_text(raw_value)
						except Exception as parse_ex:
							msg = f'IF/ELSE sayi parse hatasi ({raw_value}): {parse_ex}'
							if continue_on_error:
								logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': False, 'msg': f'Hata (devam): {msg}'})
							else:
								return JsonResponse({'ok': False, 'error': msg, 'logs': logs, 'failed_at': i}, status=400)
							continue

						abs_value = abs(numeric_value)
						if abs_value > threshold:
							branch = 'gt'
							target_idx = _resolve_step_target_index(steps, cfg, step_no_key='gt_step_no', step_id_key='gt_step_id')
						elif abs_value < threshold:
							branch = 'lt'
							target_idx = _resolve_step_target_index(steps, cfg, step_no_key='lt_step_no', step_id_key='lt_step_id')
						else:
							branch = 'eq'
							target_idx = _resolve_step_target_index(steps, cfg, step_no_key='eq_step_no', step_id_key='eq_step_id')

						branch_map = {'gt': '>', 'lt': '<', 'eq': '='}
						base_msg = f'IF/ELSE: {element_id}={raw_value} | |deger|={abs_value} {branch_map.get(branch, "=")} {threshold}'
						if target_idx is None:
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{base_msg} | hedef tanimsiz, sonraki adima gecildi'})
						else:
							next_i = target_idx
							logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': f'{base_msg} | hedef adim: {target_idx + 1}'})

				elif step_type == SapProcessStep.TYPE_IF_END:
					logs.append({'step': i + 1, 'type': step_type, 'label': step_name, 'ok': True, 'msg': 'IF bloğu kapatıldı'})

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

			if proc.office_express_auto_close and not skip_step_end_auto_close and step_type not in (
				SapProcessStep.TYPE_WINDOWS_DIALOG_ACTION,
				SapProcessStep.TYPE_WINDOWS_SCAN_DIALOGS,
				SapProcessStep.TYPE_CONVERT_SAP_EXPORT,
			):
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
		# BitiÅŸ bildirimi
		_send_end_notify_once()
		return JsonResponse({'ok': True, 'logs': logs, 'ran_until': upto_index, 'connection_template': conn.get('template_name', '')})
	finally:
		try:
			overlay.close()
		except Exception:
			pass
		try:
			_runtime_finish(process_id)
		except Exception:
			pass
		# Tüm SAP ekranlarını kapat ve oturumu sonlandır
		try:
			if 'service' in locals() and service is not None:
				service.close_all_sap_windows()
		except Exception:
			pass

