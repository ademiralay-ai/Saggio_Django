"""Tkinter blocking message dialog used as a fallback when no overlay is active.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

try:
	import tkinter as tk
except Exception:  # pragma: no cover - Tk yok ise modül yine de yüklenebilir
	tk = None

try:
	from tkinter import messagebox as tk_messagebox
except Exception:
	tk_messagebox = None


def _show_blocking_message_dialog(title, message, first_error=None):
	msg_title = str(title or '').strip() or 'Bilgi'
	msg_body = str(message or '').strip() or 'Devam etmek için Tamam butonuna basın.'
	if tk is None:
		if first_error is not None:
			return False, f'Mesaj penceresi açılamadı: {first_error}'
		return False, 'Mesaj penceresi için tkinter kullanılamıyor.'

	root = None
	try:
		if tk_messagebox is not None:
			root = tk.Tk()
			root.withdraw()
			try:
				root.attributes('-topmost', True)
			except Exception:
				pass
			tk_messagebox.showinfo(msg_title, msg_body, parent=root)
			return True, ''
		return False, 'Mesaj kutusu aracı kullanılamıyor.'
	except Exception as ex:
		base = first_error or ex
		return False, f'Mesaj penceresi açılamadı: {base}'
	finally:
		if root is not None:
			try:
				root.destroy()
			except Exception:
				pass
