"""Placeholder substitution for SAP runtime messages.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations


def _resolve_placeholders(text, runtime_state):
	"""runtime_state değerlerini metindeki {cari}, {excel_satir} vb. yer tutuculara yazar."""
	if not text:
		return text
	text = text.replace('{cari}', str(runtime_state.get('loop_value', '') or ''))
	text = text.replace('{excel_satir}', str((runtime_state.get('excel_loop_index', 0) or 0) + 1))
	text = text.replace('{excel_index}', str(runtime_state.get('excel_loop_index', 0) or 0))
	text = text.replace('{loop_index}', str(runtime_state.get('loop_index', 0) or 0))
	text = text.replace('{popup_text}', str(runtime_state.get('last_popup_text', '') or ''))
	text = text.replace('{status_text}', str(runtime_state.get('last_status_text', '') or ''))
	text = text.replace('{status_type}', str(runtime_state.get('last_status_type', '') or ''))
	return text
