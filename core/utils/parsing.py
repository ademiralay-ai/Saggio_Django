"""Pure parsing helpers used across the SAP runtime and views.

Originally lived in ``core/views.py``. These helpers are stateless and only
depend on the standard library plus ``Decimal``.
"""
from __future__ import annotations

import json
import re
import re as _re  # backwards-compat alias for callers that referenced ``_re``
from decimal import Decimal


# ─── SAP element id ──────────────────────────────────────────────────────────

def _normalize_session_element_id(element_id):
	"""'/app/con[0]/ses[0]/wnd[0]/...' → 'wnd[0]/...'  (veya zaten kısa ise olduğu gibi)."""
	eid = str(element_id or '').strip()
	# /app/con[N]/ses[N]/ önekini at
	eid = _re.sub(r'^/?app/con\[\d+\]/ses\[\d+\]/', '', eid)
	eid = eid.lstrip('/')
	return eid


def _parse_toolbar_context_command(raw_value):
	"""
	SAP buton alanından context-toolbar komutu ayrıştırır.
	Desteklenen formatlar:
	- ctxbtn:wnd[0]/.../shell|&MB_EXPORT
	- ctxbtn:wnd[0]/.../shell|&MB_EXPORT|&PC
	- ctxitem:wnd[0]/.../shell|&PC
	- session.findById("wnd[0]/.../shell").pressToolbarContextButton "&MB_EXPORT"
	- session.findById("wnd[0]/.../shell").pressToolbarContextButton "&MB_EXPORT".selectContextMenuItem "&PC"
	- session.findById("wnd[0]/.../shell").selectContextMenuItem "&PC"
	"""
	raw = str(raw_value or '').strip()
	if not raw:
		return None

	low = raw.casefold()
	if low.startswith('ctxbtn:') and '|' in raw:
		payload = raw.split(':', 1)[1]
		parts = payload.split('|')
		if len(parts) < 2:
			return None
		shell_raw = parts[0]
		cmd_raw = parts[1]
		menu_raw = parts[2] if len(parts) > 2 else ''
		shell_id = _normalize_session_element_id(shell_raw)
		command = str(cmd_raw or '').strip()
		menu_item = str(menu_raw or '').strip()
		if shell_id and command:
			return {
				'shell_id': shell_id,
				'command': command,
				'menu_item': menu_item,
				'raw': f'ctxbtn:{shell_id}|{command}' + (f'|{menu_item}' if menu_item else ''),
			}
		return None

	if low.startswith('ctxitem:') and '|' in raw:
		payload = raw.split(':', 1)[1]
		parts = payload.split('|')
		if len(parts) < 2:
			return None
		shell_raw = parts[0]
		menu_raw = parts[1]
		shell_id = _normalize_session_element_id(shell_raw)
		menu_item = str(menu_raw or '').strip()
		if shell_id and menu_item:
			return {
				'shell_id': shell_id,
				'command': '',
				'menu_item': menu_item,
				'raw': f'ctxitem:{shell_id}|{menu_item}',
			}
		return None

	m = _re.search(
		r'session\.findById\(\s*["\']([^"\']+)["\']\s*\)\s*\.\s*pressToolbarContextButton\s*["\']([^"\']+)["\'](?:\s*\.\s*selectContextMenuItem\s*["\']([^"\']+)["\'])?',
		raw,
		flags=_re.IGNORECASE,
	)
	if m:
		shell_id = _normalize_session_element_id(m.group(1))
		command = str(m.group(2) or '').strip()
		menu_item = str(m.group(3) or '').strip()
		if shell_id and command:
			return {
				'shell_id': shell_id,
				'command': command,
				'menu_item': menu_item,
				'raw': f'ctxbtn:{shell_id}|{command}' + (f'|{menu_item}' if menu_item else ''),
			}

	m2 = _re.search(
		r'session\.findById\(\s*["\']([^"\']+)["\']\s*\)\s*\.\s*selectContextMenuItem\s*["\']([^"\']+)["\']',
		raw,
		flags=_re.IGNORECASE,
	)
	if m2:
		shell_id = _normalize_session_element_id(m2.group(1))
		menu_item = str(m2.group(2) or '').strip()
		if shell_id and menu_item:
			return {
				'shell_id': shell_id,
				'command': '',
				'menu_item': menu_item,
				'raw': f'ctxitem:{shell_id}|{menu_item}',
			}

	return None


# ─── SAP menu helpers ────────────────────────────────────────────────────────

def _is_menu_target(node, raw_id=''):
	"""SAP menü öğesi (GuiMenu / mbar/menu[..]) mi? press() yerine select() ile çalışır."""
	nid = str(raw_id or '').casefold()
	if '/mbar/' in nid or '/menu[' in nid:
		return True
	try:
		ntype = str(getattr(node, 'Type', '') or '').casefold()
	except Exception:
		ntype = ''
	if not ntype:
		return False
	return ('menu' in ntype) and ('menubar' not in ntype)


def _invoke_button_or_menu(node, raw_id=''):
	"""Hedef GuiMenu ise select(), aksi halde press() çağırır."""
	if _is_menu_target(node, raw_id):
		node.select()
	else:
		node.press()


# ─── Loop / boolean / decimal ───────────────────────────────────────────────

def _parse_loop_values(raw):
	"""Virgül / noktalı virgül / satır sonu ile verilen döngü değerlerini normalize eder."""
	text = str(raw or '').strip()
	if not text:
		return []
	parts = _re.split(r'[\n,;]+', text)
	return [p.strip() for p in parts if str(p).strip()]


def _as_bool(value, default=False):
	if value is None:
		return bool(default)
	if isinstance(value, bool):
		return value
	text = str(value).strip().casefold()
	if not text:
		return bool(default)
	return text in ('1', 'true', 'evet', 'yes', 'on')


def _parse_decimal_text(text):
	raw = str(text or '').strip()
	if not raw:
		raise ValueError('Bos deger')

	clean = raw.replace('\u00a0', '').replace(' ', '')
	if not _re.search(r'\d', clean):
		raise ValueError(f'Sayisal deger bulunamadi: {raw}')

	filtered = ''.join(ch for ch in clean if (ch.isdigit() or ch in ',.-+'))
	if not filtered:
		raise ValueError(f'Sayisal deger ayristirilamadi: {raw}')

	# SAP trailing-minus desteği: "1.234,56-" → negatif
	trailing_negative = False
	if filtered.endswith('-'):
		trailing_negative = True
		filtered = filtered[:-1]

	sign = ''
	if filtered.startswith(('+', '-')):
		sign = filtered[0]
		filtered = filtered[1:]
	elif trailing_negative:
		sign = '-'

	if not filtered or not _re.search(r'\d', filtered):
		raise ValueError(f'Sayisal deger ayristirilamadi: {raw}')

	last_dot = filtered.rfind('.')
	last_comma = filtered.rfind(',')
	if last_dot >= 0 and last_comma >= 0:
		dec_sep = '.' if last_dot > last_comma else ','
	elif last_comma >= 0:
		dec_sep = ','
	elif last_dot >= 0:
		dec_sep = '.'
	else:
		dec_sep = None

	if dec_sep == ',':
		canon = filtered.replace('.', '').replace(',', '.')
	elif dec_sep == '.':
		canon = filtered.replace(',', '')
	else:
		canon = _re.sub(r'\D+', '', filtered)

	canon = f'{sign}{canon}'
	if not _re.fullmatch(r'[+-]?\d+(?:\.\d+)?', canon):
		raise ValueError(f'Sayisal deger parse edilemedi: {raw}')
	return Decimal(canon)


# ─── Step / rule index resolution ───────────────────────────────────────────

def _resolve_step_no_to_index(raw_step_no, steps_len):
	try:
		step_no = int(raw_step_no)
	except (TypeError, ValueError):
		return None
	if step_no < 1 or step_no > steps_len:
		return None
	return step_no - 1


def _resolve_step_target_index(steps, cfg, *, step_no_key, step_id_key=None):
	"""Hedef adımı önce step_id ile, yoksa step_no ile çözer."""
	if not isinstance(steps, list) or not isinstance(cfg, dict):
		return None

	if step_id_key:
		raw_id = cfg.get(step_id_key)
		step_id = str(raw_id or '').strip()
		if step_id:
			for idx, st in enumerate(steps):
				if not isinstance(st, dict):
					continue
				st_id = str(st.get('id') or '').strip()
				if st_id and st_id == step_id:
					return idx
			# Builder kaydında adımlar yeniden üretilebildiği için ID stale kalabilir.
			# Bu durumda step_no varsa ona düşmek çalışma akışını korur.
			return _resolve_step_no_to_index(cfg.get(step_no_key), len(steps))

	return _resolve_step_no_to_index(cfg.get(step_no_key), len(steps))


def _resolve_rule_target_index(steps, rule):
	"""if_else popup/status kurallarındaki hedefi çözer (step_id öncelikli)."""
	if not isinstance(steps, list) or not isinstance(rule, dict):
		return None
	raw_id = rule.get('step_id')
	step_id = str(raw_id or '').strip()
	if step_id:
		for idx, st in enumerate(steps):
			if not isinstance(st, dict):
				continue
			st_id = str(st.get('id') or '').strip()
			if st_id and st_id == step_id:
				return idx
		# Restore/clone sonrası ID stale kalabiliyor; mevcut step_no varsa ona düş.
		return _resolve_step_no_to_index(rule.get('step_no'), len(steps))
	return _resolve_step_no_to_index(rule.get('step_no'), len(steps))


# ─── Misc text / id helpers ─────────────────────────────────────────────────

def _normalize_match_text(value):
	return ' '.join(str(value or '').strip().casefold().split())


def _normalize_allowed_user_ids(text):
	"""Serbest metni (satır/virgül/boşluk ayrılmış) numerik user ID set'ine çevirir."""
	if not text:
		return set()
	out = set()
	for chunk in str(text).replace(',', '\n').replace(';', '\n').split('\n'):
		token = chunk.strip()
		if not token:
			continue
		# Sadece rakamları al (negatif chat_id de olabilir, başında '-')
		sign = ''
		if token.startswith('-'):
			sign = '-'
			token = token[1:]
		digits = ''.join(c for c in token if c.isdigit())
		if digits:
			try:
				out.add(int(sign + digits))
			except ValueError:
				pass
	return out


def _safe_release_version(version):
	return re.sub(r'[^0-9A-Za-z._-]+', '_', str(version or '')).strip('_') or 'release'


# ─── Telegram error extraction ──────────────────────────────────────────────

def _extract_telegram_http_error(err):
	"""Telegram HTTPError gövdesindeki açıklamayı çıkarıp okunur bir mesaj döndürür."""
	status = getattr(err, 'code', 'unknown')
	description = ''

	try:
		raw = err.read()
		if raw:
			payload = json.loads(raw.decode('utf-8', errors='replace') or '{}')
			description = str(payload.get('description') or '').strip()
	except Exception:
		pass

	if description:
		return f'HTTP {status}: {description}'

	reason = str(getattr(err, 'reason', '') or '').strip()
	if reason:
		return f'HTTP {status}: {reason}'

	return f'HTTP {status}'
