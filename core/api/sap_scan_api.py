"""SAP scan JSON endpoints (popups, buttons, selectables, inputs, dialogs, screens, grids).

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ..models import SapProcess
from ..sap_service import SAPScanService
from ..sap_popup_utils import collect_popup_controls
from ..windows_dialog_utils import scan_visible_dialogs
from ..utils.parsing import _normalize_session_element_id
from ..services.sap_runtime_service import (
	_iter_children,
	_extract_runtime_steps,
	_resolve_connection_from_steps,
)
from ..services.sap_popup_service import (
	_collect_node_text,
	_collect_popup_message_text,
	_collect_popup_text_legacy,
)


@require_POST
def _sap_process_scan_popups_impl(request, process_id):
	"""Açık SAP popup pencerelerini ve içeriklerindeki buton/radio alanlarını tarar."""
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

			buttons, radios, inputs = collect_popup_controls(wnd, _normalize_session_element_id, _iter_children)

			popups.append({
				'id': popup_id,
				'title': title,
				'text': text,
				'buttons': buttons,
				'radios': radios,
				'inputs': inputs,
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
	seen_ctx_specs = set()

	def _collect_buttons(node):
		stack = [node] if node is not None else []
		while stack:
			current = stack.pop(0)
			try:
				node_id = str(getattr(current, 'Id', '') or '').strip()
				node_type = str(getattr(current, 'Type', '') or '').strip()
				norm_id = _normalize_session_element_id(node_id)
				lower_type = node_type.casefold()
				lower_id = norm_id.casefold()
				is_button = ('button' in lower_type) or ('/btn[' in lower_id)
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

				# SAP menü öğeleri (GuiMenu) — wnd[0]/mbar/menu[..] yolları
				is_menu_node = (
					('/mbar/' in lower_id or '/menu[' in lower_id)
					or (('menu' in lower_type) and ('menubar' not in lower_type))
				)
				if is_menu_node and norm_id and norm_id not in seen_ids:
					name = str(getattr(current, 'Name', '') or '').strip()
					text = str(getattr(current, 'Text', '') or '').strip()
					try:
						_kids = getattr(current, 'Children', None)
						_kid_count = int(getattr(_kids, 'Count', 0) or 0) if _kids is not None else 0
					except Exception:
						_kid_count = 0
					is_leaf = (_kid_count == 0)
					label_prefix = 'Menü Öğe' if is_leaf else 'Menü Grubu'
					display = text or name or 'Menü'
					seen_ids.add(norm_id)
					buttons.append({
						'id': norm_id,
						'type': node_type or 'GuiMenu',
						'name': name,
						'text': text,
						'label': f'{label_prefix}: {display} [{norm_id}]',
					})

				# GuiShell üzerindeki context-toolbar komutları (örn: &MB_EXPORT)
				is_shell = ('shell' in lower_type) or norm_id.casefold().endswith('/shell')
				if is_shell and norm_id:
					ctx_spec = f'ctxbtn:{norm_id}|&MB_EXPORT'
					if ctx_spec not in seen_ctx_specs:
						seen_ctx_specs.add(ctx_spec)
						buttons.append({
							'id': ctx_spec,
							'type': f'{node_type}:ContextToolbar',
							'name': '&MB_EXPORT',
							'text': 'Toolbar Context: Disa Aktar',
							'label': f'Toolbar Context: Disa Aktar (&MB_EXPORT) [{norm_id}]',
						})
					ctx_spec_pc = f'ctxbtn:{norm_id}|&MB_EXPORT|&PC'
					if ctx_spec_pc not in seen_ctx_specs:
						seen_ctx_specs.add(ctx_spec_pc)
						buttons.append({
							'id': ctx_spec_pc,
							'type': f'{node_type}:ContextToolbar',
							'name': '&MB_EXPORT -> &PC',
							'text': 'Toolbar Context: Disa Aktar > PC',
							'label': f'Toolbar Context: Disa Aktar -> PC (&MB_EXPORT -> &PC) [{norm_id}]',
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
def sap_process_scan_selectables(request, process_id):
	"""Açık SAP ekranındaki radio/checkbox elementlerini tarar (wnd[0]+popup)."""
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

	items = []
	seen_ids = set()

	def _collect(node):
		stack = [node] if node is not None else []
		while stack:
			current = stack.pop(0)
			try:
				node_id = str(getattr(current, 'Id', '') or '').strip()
				node_type = str(getattr(current, 'Type', '') or '').strip()
				norm_id = _normalize_session_element_id(node_id)
				lower_type = node_type.casefold()
				lower_id = norm_id.casefold()
				is_radio = ('radiobutton' in lower_type) or ('/rad' in lower_id)
				is_checkbox = ('checkbox' in lower_type) or ('/chk' in lower_id)
				if (is_radio or is_checkbox) and norm_id and norm_id not in seen_ids:
					seen_ids.add(norm_id)
					text = str(getattr(current, 'Text', '') or '').strip()
					name = str(getattr(current, 'Name', '') or '').strip()
					kind = 'radio' if is_radio else 'checkbox'
					window_hint = 'wnd[1]' if 'wnd[1]' in norm_id else 'wnd[0]'
					label_text = text or name or node_type or 'Secim Alani'
					items.append({
						'id': norm_id,
						'type': node_type,
						'kind': kind,
						'window': window_hint,
						'text': text,
						'name': name,
						'label': f'{label_text} ({kind}) [{norm_id}]',
					})
			except Exception:
				pass
			stack.extend(_iter_children(current))

	try:
		children = getattr(session, 'Children', None)
		wnd_count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		if wnd_count == 0:
			_collect(session)
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
					_collect(wnd)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Secilebilir alan tarama hatası: {ex}'}, status=500)

	items.sort(key=lambda x: x['id'])
	return JsonResponse({'ok': True, 'controls': items, 'count': len(items)})


@require_POST
def sap_process_scan_inputs(request, process_id):
	"""Açık SAP ekranındaki input alanlarını tarar (wnd[0]+popup)."""
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

	items = []
	seen_ids = set()

	def _collect(node):
		stack = [node] if node is not None else []
		while stack:
			current = stack.pop(0)
			try:
				node_id = str(getattr(current, 'Id', '') or '').strip()
				node_type = str(getattr(current, 'Type', '') or '').strip()
				norm_id = _normalize_session_element_id(node_id)
				lower_type = node_type.casefold()
				lower_id = norm_id.casefold()
				is_input = (
					'/txt' in lower_id
					or '/ctxt' in lower_id
					or '/pwd' in lower_id
					or '/okcd' in lower_id
					or 'textfield' in lower_type
					or 'textbox' in lower_type
					or 'inputfield' in lower_type
					or 'okcodefield' in lower_type
					or 'passwordfield' in lower_type
					or 'combobox' in lower_type
				)
				if is_input and norm_id and norm_id not in seen_ids:
					seen_ids.add(norm_id)
					text = str(getattr(current, 'Text', '') or '').strip()
					name = str(getattr(current, 'Name', '') or '').strip()
					window_hint = 'wnd[1]' if 'wnd[1]' in norm_id else 'wnd[0]'
					label_text = name or text or node_type or 'Input Alani'
					items.append({
						'id': norm_id,
						'type': node_type,
						'window': window_hint,
						'text': text,
						'name': name,
						'label': f'{label_text} [{norm_id}]',
					})
			except Exception:
				pass
			stack.extend(_iter_children(current))

	try:
		children = getattr(session, 'Children', None)
		wnd_count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		if wnd_count == 0:
			_collect(session)
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
					_collect(wnd)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Input alan tarama hatası: {ex}'}, status=500)

	items.sort(key=lambda x: x['id'])
	return JsonResponse({'ok': True, 'controls': items, 'count': len(items)})


@require_POST
def sap_process_scan_windows_dialogs(request, process_id):
	"""Açık Windows diyaloglarını ve buton/checkbox kontrollerini tarar."""
	get_object_or_404(SapProcess, pk=process_id)
	try:
		body = json.loads(request.body) if request.body else {}
	except (json.JSONDecodeError, TypeError):
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	title_filter = str((body or {}).get('title_filter', '') or '').strip()
	try:
		dialogs = scan_visible_dialogs(title_filter=title_filter)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Windows popup tarama hatası: {ex}'}, status=500)

	return JsonResponse({'ok': True, 'dialogs': dialogs, 'count': len(dialogs)})


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


