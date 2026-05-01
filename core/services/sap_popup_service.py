"""SAP popup window helpers: text collection, button matching, Office Express auto-close.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import re
import time

from ..utils.parsing import _normalize_session_element_id
from .sap_runtime_service import _iter_children


def _close_office_express_popups(service):
	"""Açık SAP popup'larında Ofis Ekspres mesajı varsa otomatik kapatır."""
	closed = 0
	try:
		session = getattr(service, 'session', None)
		if session is None:
			return 0
		deadline = time.time() + 2.0
		max_pass = 3
		pass_no = 0
		while pass_no < max_pass and time.time() < deadline:
			pass_no += 1
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



def _has_popup_window(session):
	try:
		children = getattr(session, 'Children', None)
		count = int(getattr(children, 'Count', 0) or 0) if children is not None else 0
		return count > 1
	except Exception:
		return False



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


