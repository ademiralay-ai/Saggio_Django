"""SAP runtime helpers: element read, statusbar, hotkey, loop advancement, action builder.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import os
import time

from ..models import SapProcessStep
from ..firebase_service import SAPTemplateService
from ..sap_keyboard_utils import build_sendkeys_from_config
from ..utils.parsing import (
	_normalize_session_element_id,
	_parse_loop_values,
	_resolve_step_target_index,
)
from ..utils.date_utils import _calc_dynamic_date
from .excel_service import (
	_reset_excel_cursors,
	_get_excel_cursor_index,
	_set_excel_cursor_index,
	_get_excel_total_data_rows,
)


def _read_sap_element_text(session, element_id):
	raw_id = str(element_id or '').strip()
	norm_id = _normalize_session_element_id(raw_id)
	if not norm_id:
		return False, '', 'Element ID bos.'

	elem = None
	for candidate in (norm_id, raw_id):
		if not candidate:
			continue
		try:
			elem = session.findById(candidate)
			if elem is not None:
				break
		except Exception:
			continue

	if elem is None:
		return False, '', f'Element bulunamadi: {norm_id}'

	for attr in ('Text', 'Value', 'Key'):
		try:
			val = getattr(elem, attr, None)
			if val is not None:
				text = str(val).strip()
				if text != '':
					return True, text, ''
		except Exception:
			pass

	try:
		selected = getattr(elem, 'Selected', None)
		if selected is not None:
			return True, ('1' if bool(selected) else '0'), ''
	except Exception:
		pass

	return False, '', f'Element degeri okunamadi: {norm_id}'



def _read_sap_statusbar(session):
	"""SAP alt durum çubuğundaki mesajı ve tipini okur (S/E/W/I/A)."""
	if session is None:
		return False, '', '', 'Session yok.'
	obj = None
	try:
		obj = session.findById('wnd[0]/sbar')
	except Exception:
		obj = None
	if obj is None:
		return False, '', '', 'Status bar bulunamadı (wnd[0]/sbar).'

	msg = ''
	for attr in ('Text', 'text', 'MessageText', 'Value'):
		try:
			v = getattr(obj, attr, None)
			if v is not None:
				t = str(v).strip()
				if t:
					msg = t
					break
		except Exception:
			pass

	msg_type = ''
	for attr in ('MessageType', 'messageType', 'Type'):
		try:
			v = getattr(obj, attr, None)
			if v is not None:
				t = str(v).strip().upper()
				if t:
					msg_type = t[0]
					break
		except Exception:
			pass

	return True, msg, msg_type, ''



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



def _send_sap_hotkey(service, combo_text='', key='', use_ctrl=False, use_alt=False, use_shift=False, use_win=False):
	"""SAP aktif pencereye klavye kombinasyonu gönderir.
	ESC/ENTER gibi saf VKey'ler için önce SAP sendVKey kullanılır; diğerleri WScript.Shell ile gönderilir."""
	if service is None or getattr(service, 'session', None) is None:
		return False, 'SAP session hazir degil.'

	# Sadece modifier'sız tek tuş ise VKey ile gönder (daha güvenilir)
	_no_modifier = not use_ctrl and not use_alt and not use_shift and not use_win
	_combo_clean = str(combo_text or '').strip().upper()
	_key_clean = str(key or '').strip().upper()
	_vkey_map = {'ENTER': 0, 'ESC': 12, 'ESCAPE': 12,
	             'F1': 112, 'F2': 113, 'F3': 114, 'F4': 115, 'F5': 5, 'F6': 6, 'F7': 7, 'F8': 8,
	             'F9': 9, 'F10': 10, 'F11': 11, 'F12': 99,
	             'F13': 14, 'F14': 15, 'F15': 16, 'F16': 17, 'F17': 18, 'F18': 19,
	             'F19': 20, 'F20': 21, 'F21': 22, 'F22': 23, 'F23': 24, 'F24': 25}

	effective_key = _key_clean
	if not _combo_clean and _no_modifier:
		vk = _vkey_map.get(effective_key)
		if vk is not None:
			try:
				wnd = service.session.findById('wnd[0]')
				try:
					wnd.setFocus()
				except Exception:
					pass
				service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
				wnd.sendVKey(vk)
				service._wait_until_idle(service.session, timeout_sec=5, stable_checks=1)
				return True, f'VKey({vk}) [{effective_key}]'
			except Exception as ex:
				return False, str(ex)

	send_keys = build_sendkeys_from_config(
		combo_text=combo_text,
		key=key,
		use_ctrl=use_ctrl,
		use_alt=use_alt,
		use_shift=use_shift,
		use_win=use_win,
	)
	if not send_keys:
		return False, 'Gonderilecek tus/kombinasyon bos.'

	try:
		wnd = service.session.findById('wnd[0]')
		try:
			wnd.setFocus()
		except Exception:
			pass
		service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
		import win32com.client
		shell = win32com.client.Dispatch('WScript.Shell')
		shell.SendKeys(send_keys)
		service._wait_until_idle(service.session, timeout_sec=5, stable_checks=1)
		return True, send_keys
	except Exception as ex:
		return False, str(ex)



def _extract_runtime_steps(body, proc):
	"""İstekte gelen steps varsa onu, yoksa DB steps'i kullan."""
	steps_data = body.get('steps')
	if isinstance(steps_data, list):
		clean = []
		for i, s in enumerate(steps_data):
			if not isinstance(s, dict):
				continue
			clean.append({
				'id': s.get('id'),
				'order': i,
				'step_type': str(s.get('step_type', '') or '').strip(),
				'label': str(s.get('label', '') or '').strip(),
				'config': s.get('config', {}) if isinstance(s.get('config'), dict) else {},
			})
		return clean

	return list(proc.steps.values('id', 'order', 'step_type', 'label', 'config').order_by('order'))



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
	_reset_excel_cursors(runtime_state)

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



def _advance_excel_loop_runtime(steps, runtime_state, cfg):
	excel_path = str(cfg.get('excel_file_path', '') or '').strip()
	sheet_name = str(cfg.get('excel_sheet_name', '') or '').strip()
	try:
		header_row = max(1, int(cfg.get('excel_header_row') or 1))
	except (TypeError, ValueError):
		header_row = 1

	if not excel_path and isinstance(steps, list):
		for cand in steps:
			if not isinstance(cand, dict):
				continue
			if str(cand.get('step_type', '') or '').strip() != SapProcessStep.TYPE_SAP_FILL_INPUT:
				continue
			ccfg = cand.get('config', {}) if isinstance(cand.get('config'), dict) else {}
			if str(ccfg.get('value_source', 'static') or 'static').strip() != 'excel_column':
				continue
			cand_path = str(ccfg.get('excel_file_path', '') or '').strip()
			if cand_path:
				excel_path = cand_path
				sheet_name = sheet_name or str(ccfg.get('excel_sheet_name', '') or '').strip()
				try:
					header_row = max(1, int(ccfg.get('excel_header_row') or header_row))
				except (TypeError, ValueError):
					pass
				break

	if not excel_path:
		return False, 'Excel dosya yolu boÅŸ.', None
	if not os.path.isfile(excel_path):
		return False, f'Excel dosyası bulunamadı: {excel_path}', None
	cfg_resolved = dict(cfg or {})
	cfg_resolved['excel_file_path'] = excel_path
	cfg_resolved['excel_sheet_name'] = sheet_name
	cfg_resolved['excel_header_row'] = header_row
	ok_count, total_rows, count_err = _get_excel_total_data_rows(excel_path, sheet_name, header_row, runtime_state=runtime_state, cfg=cfg_resolved)
	if not ok_count:
		return False, count_err, None
	if total_rows <= 0:
		return False, 'Excel veri satırı bulunamadı.', None

	current_idx = _get_excel_cursor_index(runtime_state, cfg_resolved)
	next_idx = current_idx + 1
	if next_idx >= total_rows:
		_set_excel_cursor_index(runtime_state, cfg_resolved, 0)
		runtime_state['excel_loop_index'] = 0
		return False, f'Excel satırları tamamlandı ({total_rows}/{total_rows})', None

	_set_excel_cursor_index(runtime_state, cfg_resolved, next_idx)
	runtime_state['excel_loop_index'] = next_idx
	target_idx = _resolve_step_target_index(
		steps,
		cfg,
		step_no_key='target_step_no',
		step_id_key='target_step_id',
	)
	if target_idx is None:
		return False, 'Excel satırı ilerletildi fakat hedef adım no geçersiz.', None
	msg = f'Excelde sonraki satıra geçildi: {next_idx + 1}/{total_rows} | adıma dön: {target_idx + 1}'
	return True, msg, target_idx


