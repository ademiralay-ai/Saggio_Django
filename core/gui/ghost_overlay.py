"""Saggio "Hayalet Ekran" — masaüstünde SAP süreç ilerlemesini gösteren Tk overlay.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import os
import socket
import time
from datetime import datetime

try:
	import tkinter as tk
except Exception:  # pragma: no cover
	tk = None

from ..utils.runtime_state import (
	_runtime_set_controls,
	_runtime_set_step,
	_runtime_push_log,
)
from .blocking_dialog import _show_blocking_message_dialog


class _GhostOverlayWindow:
	"""Süreç çalışırken masaüstünde üstte kalan basit durum penceresi."""
	def __init__(self, enabled, process_name, process_id=None, agent_info=None):
		self.enabled = bool(enabled)
		self.process_name = str(process_name or '').strip() or 'SAP Süreci'
		self.process_id = int(process_id) if process_id is not None else None
		self.pc_name = os.environ.get('COMPUTERNAME') or socket.gethostname() or 'Bilinmeyen'
		self.agent_info = agent_info or {}
		self.root = None
		self.header_title = None
		self.header_subtitle = None
		self.status_badge = None
		self.step_label = None
		self.log_text = None
		self.log_scroll = None
		self.pause_btn = None
		self.stop_btn = None
		self.minimize_btn = None
		self.settings_btn = None
		self._settings_win = None
		self._alpha_val = 0.97
		self.logs = []
		self.current_step = ''
		self.paused = False
		self.stop_requested = False
		self.logs_collapsed = False
		self._expanded_geometry = ''
		if not self.enabled or tk is None:
			self.enabled = False
			return
		try:
			self.root = tk.Tk()
			self.root.title('Saggio Hayalet Ekran')
			self.root.attributes('-topmost', True)
			self.root.attributes('-alpha', self._alpha_val)
			self.root.config(bg='#0f172a')
			# Pencere X butonuna tıklanırsa süreç durdurma talebi olarak ele al;
			# pencereyi yok etme — runtime cleanup ana akışta yapılacak.
			try:
				self.root.protocol('WM_DELETE_WINDOW', self._on_window_close)
			except Exception:
				pass
			screen_w = self.root.winfo_screenwidth()
			x = max(20, screen_w - 580)
			self.root.geometry(f'550x360+{x}+24')
			self.root.minsize(520, 320)
			self.root.maxsize(720, 720)
			self.root.resizable(True, True)

			container = tk.Frame(self.root, bg='#0f172a', bd=0, highlightthickness=1, highlightbackground='#334155')
			container.pack(expand=True, fill='both', padx=8, pady=8)

			header = tk.Frame(container, bg='#0f172a')
			header.pack(fill='x', padx=14, pady=(14, 8))

			self.header_title = tk.Label(
				header,
				text='SAGGIO HAYALET EKRAN',
				font=('Consolas', 12, 'bold'),
				fg='#e2e8f0',
				bg='#0f172a',
				anchor='w',
			)
			self.header_title.pack(fill='x')

			self.header_subtitle = tk.Label(
				header,
				text='',
				font=('Consolas', 9),
				fg='#94a3b8',
				bg='#0f172a',
				anchor='w',
			)
			self.header_subtitle.pack(fill='x', pady=(4, 0))

			status_wrap = tk.Frame(container, bg='#0f172a')
			status_wrap.pack(fill='x', padx=14, pady=(0, 10))

			self.status_badge = tk.Label(
				status_wrap,
				text='',
				font=('Consolas', 9, 'bold'),
				fg='white',
				bg='#1d4ed8',
				padx=10,
				pady=4,
			)
			self.status_badge.pack(side='left')

			self.step_label = tk.Label(
				status_wrap,
				text='',
				font=('Consolas', 9),
				fg='#cbd5e1',
				bg='#0f172a',
				anchor='w',
				justify='left',
			)
			self.step_label.pack(side='left', fill='x', expand=True, padx=(10, 0))

			btn_wrap = tk.Frame(container, bg='#0f172a')
			btn_wrap.pack(fill='x', padx=14, pady=(0, 10))
			self.minimize_btn = tk.Button(
				btn_wrap,
				text='Logu Gizle',
				font=('Consolas', 10, 'bold'),
				bg='#334155',
				fg='white',
				activebackground='#334155',
				activeforeground='white',
				relief='flat',
				bd=0,
				padx=10,
				pady=6,
				command=self.toggle_logs,
			)
			self.minimize_btn.pack(side='left', padx=(0, 6))

			self.pause_btn = tk.Button(
				btn_wrap,
				text='Duraklat',
				font=('Consolas', 10, 'bold'),
				bg='#1d4ed8',
				fg='white',
				activebackground='#1d4ed8',
				activeforeground='white',
				relief='flat',
				bd=0,
				padx=12,
				pady=6,
				command=self.toggle_pause,
			)
			self.pause_btn.pack(side='left', fill='x', expand=True, padx=(0, 6))
			self.stop_btn = tk.Button(
				btn_wrap,
				text='Durdur',
				font=('Consolas', 10, 'bold'),
				bg='#da3633',
				fg='white',
				activebackground='#da3633',
				activeforeground='white',
				relief='flat',
				bd=0,
				padx=12,
				pady=6,
				command=self.request_stop,
			)
			self.stop_btn.pack(side='left', fill='x', expand=True)

			self.settings_btn = tk.Button(
				btn_wrap,
				text='⚙',
				font=('Consolas', 11, 'bold'),
				bg='#475569',
				fg='white',
				activebackground='#475569',
				activeforeground='white',
				relief='flat',
				bd=0,
				padx=10,
				pady=6,
				command=self.open_settings,
			)
			self.settings_btn.pack(side='left', padx=(6, 0))

			log_card = tk.Frame(container, bg='#111827', bd=0, highlightthickness=1, highlightbackground='#334155')
			log_card.pack(expand=True, fill='both', padx=14, pady=(0, 14))

			log_head = tk.Label(
				log_card,
				text='Akış Logları',
				font=('Consolas', 10, 'bold'),
				fg='#e2e8f0',
				bg='#111827',
				anchor='w',
				padx=12,
				pady=10,
			)
			log_head.pack(fill='x')

			log_wrap = tk.Frame(log_card, bg='#111827')
			log_wrap.pack(expand=True, fill='both', padx=10, pady=(0, 10))
			self.log_text = tk.Text(
				log_wrap,
				font=('Consolas', 9),
				fg='#cbd5e1',
				bg='#111827',
				insertbackground='#cbd5e1',
				relief='flat',
				borderwidth=0,
				highlightthickness=0,
				padx=2,
				pady=2,
				wrap='word',
			)
			self.log_scroll = tk.Scrollbar(log_wrap, orient='vertical', command=self.log_text.yview)
			self.log_text.configure(yscrollcommand=self.log_scroll.set)
			self.log_text.pack(side='left', expand=True, fill='both')
			self.log_scroll.pack(side='right', fill='y')
			self.log_text.tag_configure('ok', foreground='#22c55e')
			self.log_text.tag_configure('warn', foreground='#f59e0b')
			self.log_text.tag_configure('err', foreground='#ef4444')
			self.log_text.tag_configure('info', foreground='#cbd5e1')
			self.log_text.configure(state='disabled')
			self._render()
		except Exception:
			self.enabled = False
			self.root = None
			self.header_title = None
			self.header_subtitle = None
			self.status_badge = None
			self.step_label = None

	def _render(self):
		if not self.enabled or self.root is None or self.header_title is None:
			return
		if not self._root_alive():
			# Tk root harici olarak yok edildi (kullanıcı pencereyi kapattı vb.).
			# Stop talebi olarak işaretle ve sessizce çık.
			self.enabled = False
			self.stop_requested = True
			if self.process_id is not None:
				try:
					_runtime_set_controls(self.process_id, paused=False, stop_requested=True)
				except Exception:
					pass
			return
		try:
			stamp = datetime.now().strftime('%H:%M:%S')
			status_text = 'Durduruldu' if self.stop_requested else ('Duraklatıldı' if self.paused else 'Çalışıyor')
			status_colors = {
				'Çalışıyor': '#1d4ed8',
				'Duraklatıldı': '#c2410c',
				'Durduruldu': '#b91c1c',
			}
			parts = [f'Süreç: {self.process_name}', f'PC: {self.pc_name}']
			if self.agent_info.get('job_id'):
				parts.append(f'İş: #{self.agent_info["job_id"]}')
			if self.agent_info.get('agent_code'):
				parts.append(f'Ajan: {self.agent_info["agent_code"]}')
			if self.agent_info.get('agent_ip'):
				parts.append(f'IP: {self.agent_info["agent_ip"]}')
			parts.append(f'Güncelleme: {stamp}')
			self.header_subtitle.config(text='   |   '.join(parts))
			if self.status_badge is not None:
				self.status_badge.config(text=status_text, bg=status_colors.get(status_text, '#1d4ed8'))
			if self.step_label is not None:
				self.step_label.config(text=f'Adım: {self.current_step or "-"}')
			if self.log_text is not None:
				self.log_text.configure(state='normal')
				self.log_text.delete('1.0', 'end')
				log_lines = self.logs[-200:] if self.logs else ['Hazır']
				for line in log_lines:
					log_tag = self._log_tag_for_line(line)
					self.log_text.insert('end', f'• {line}\n', log_tag)
				self.log_text.see('end')
				self.log_text.configure(state='disabled')
			if self.pause_btn is not None:
				self.pause_btn.config(text='Devam Et' if self.paused else 'Duraklat')
			if self.minimize_btn is not None:
				self.minimize_btn.config(text='Logu Göster' if self.logs_collapsed else 'Logu Gizle')
			self.root.update_idletasks()
			self.root.update()
		except Exception:
			pass

	def _log_tag_for_line(self, line):
		text = str(line or '').casefold()
		if any(k in text for k in ('hata', 'başarısız', 'basarisiz', 'error', 'failed', 'bulunamadı', 'bulunamadi')):
			return 'err'
		if any(k in text for k in ('uyarı', 'uyari', 'atlandı', 'atlandi', 'timeout', 'geçersiz', 'gecersiz')):
			return 'warn'
		if any(k in text for k in ('tamamlandı', 'tamamlandi', 'gönderildi', 'gonderildi', 'uygulandı', 'uygulandi', 'basıldı', 'basildi')):
			return 'ok'
		return 'info'

	def toggle_logs(self):
		if not self.enabled or self.root is None:
			return
		self.logs_collapsed = not self.logs_collapsed
		try:
			if self.logs_collapsed:
				self._expanded_geometry = self.root.winfo_geometry()
				self.root.geometry('550x170')
			else:
				if self._expanded_geometry:
					self.root.geometry(self._expanded_geometry)
				else:
					self.root.geometry('550x360')
		except Exception:
			pass
		self._render()

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
			return bool(self.stop_requested)
		if not self._root_alive():
			# Pencere harici olarak kapatıldıysa stop sayılır.
			self.enabled = False
			self.stop_requested = True
			return True
		self._render()
		return bool(self.stop_requested)

	def wait_if_paused(self):
		if not self.enabled:
			return bool(self.stop_requested)
		while self.paused and not self.stop_requested:
			if not self._root_alive():
				self.enabled = False
				self.stop_requested = True
				return True
			try:
				self._render()
				time.sleep(0.15)
			except Exception:
				break
		return bool(self.stop_requested)

	def _root_alive(self):
		"""Tk root hâlâ geçerli mi (kullanıcı X ile kapatmadı mı)?"""
		if self.root is None:
			return False
		try:
			return bool(self.root.winfo_exists())
		except Exception:
			return False

	def _on_window_close(self):
		"""Kullanıcı pencerenin X butonuna bastığında: durdurma talebi tetikle.
		Pencereyi burada yok etme; ana akış cleanup'ı sağlasın."""
		try:
			self.stop_requested = True
			self.paused = False
			if self.process_id is not None:
				try:
					_runtime_set_controls(self.process_id, paused=False, stop_requested=True)
				except Exception:
					pass
				try:
					_runtime_push_log(self.process_id, 'Hayalet ekran kullanıcı tarafından kapatıldı; durdurma istendi.')
				except Exception:
					pass
		except Exception:
			pass

	def set_step(self, step_no, total_steps, step_name):
		if self.process_id is not None:
			_runtime_set_step(self.process_id, step_no, total_steps, step_name)
		if not self.enabled:
			return
		self.current_step = f'{step_no}/{total_steps} - {step_name}'
		self._render()

	def _stamp_log_message(self, msg):
		"""Log mesajını üretildiği anın saatiyle etiketle."""
		text = str(msg or '').strip()
		if not text:
			return ''
		stamp = datetime.now().strftime('%H:%M:%S')
		return f'[{stamp}] {text}'

	def push_log(self, text):
		msg = str(text or '').strip()
		if msg:
			msg = self._stamp_log_message(msg)
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
		self.header_title = None
		self.header_subtitle = None
		self.status_badge = None
		self.step_label = None
		self.log_text = None
		self.log_scroll = None
		self.pause_btn = None
		self.stop_btn = None
		self.minimize_btn = None
		self.settings_btn = None
		try:
			if self._settings_win is not None:
				self._settings_win.destroy()
		except Exception:
			pass
		self._settings_win = None

	def open_settings(self):
		if not self.enabled or self.root is None:
			return
		try:
			if self._settings_win is not None and self._settings_win.winfo_exists():
				self._settings_win.focus_force()
				return
		except Exception:
			pass

		win = tk.Toplevel(self.root)
		self._settings_win = win
		win.title('Ayarlar')
		win.attributes('-topmost', True)
		win.config(bg='#0f172a')
		win.geometry('320x160')
		win.resizable(False, False)

		tk.Label(win, text='Şeffaflık Ayarları', font=('Consolas', 11, 'bold'),
			fg='#e2e8f0', bg='#0f172a').pack(anchor='w', padx=16, pady=(14, 6))

		slider_frame = tk.Frame(win, bg='#0f172a')
		slider_frame.pack(fill='x', padx=16)

		tk.Label(slider_frame, text='Opaklık:', font=('Consolas', 9),
			fg='#94a3b8', bg='#0f172a').pack(side='left')

		alpha_var = tk.DoubleVar(value=self._alpha_val)

		pct_lbl = tk.Label(slider_frame, text=f'{int(self._alpha_val * 100)}%',
			font=('Consolas', 9, 'bold'), fg='#e2e8f0', bg='#0f172a', width=5)
		pct_lbl.pack(side='right')

		def _on_alpha(val):
			v = round(float(val), 2)
			self._alpha_val = v
			try:
				self.root.attributes('-alpha', v)
			except Exception:
				pass
			pct_lbl.config(text=f'{int(v * 100)}%')

		scale = tk.Scale(win, from_=0.20, to=1.0, resolution=0.01, orient='horizontal',
			variable=alpha_var, command=_on_alpha,
			bg='#0f172a', fg='#e2e8f0', troughcolor='#334155',
			highlightthickness=0, bd=0, sliderlength=18, length=260)
		scale.pack(padx=16, pady=(4, 0))

		tk.Button(win, text='Kapat', font=('Consolas', 10, 'bold'),
			bg='#334155', fg='white', activebackground='#334155', activeforeground='white',
			relief='flat', bd=0, padx=12, pady=5,
			command=win.destroy).pack(pady=(10, 0))

	def __del__(self):
		self.close()

	def show_message(self, title, message):
		msg_title = str(title or '').strip() or 'Bilgi'
		msg_body = str(message or '').strip() or 'Devam etmek için Tamam butonuna basın.'
		if not self.enabled or self.root is None or tk is None:
			return _show_blocking_message_dialog(msg_title, msg_body)

		closed = {'done': False}
		win = None

		def _finish():
			closed['done'] = True
			try:
				if win is not None:
					win.grab_release()
			except Exception:
				pass
			try:
				if win is not None:
					win.destroy()
			except Exception:
				pass

		try:
			win = tk.Toplevel(self.root)
			win.title(msg_title)
			win.attributes('-topmost', True)
			win.transient(self.root)
			win.configure(bg='#0f172a')
			win.resizable(False, False)
			win.protocol('WM_DELETE_WINDOW', _finish)

			title_lbl = tk.Label(win, text=msg_title, font=('Consolas', 11, 'bold'), fg='#e2e8f0', bg='#0f172a', anchor='w', justify='left')
			title_lbl.pack(fill='x', padx=16, pady=(14, 8))

			body_lbl = tk.Label(win, text=msg_body, font=('Consolas', 10), fg='#cbd5e1', bg='#0f172a', justify='left', anchor='w', wraplength=420)
			body_lbl.pack(fill='both', expand=True, padx=16, pady=(0, 12))

			ok_btn = tk.Button(win, text='Tamam', font=('Consolas', 10, 'bold'), bg='#1d4ed8', fg='white', activebackground='#1d4ed8', activeforeground='white', relief='flat', command=_finish)
			ok_btn.pack(pady=(0, 14), ipadx=18, ipady=2)

			win.update_idletasks()
			width = max(360, win.winfo_reqwidth())
			height = max(170, win.winfo_reqheight())
			screen_w = win.winfo_screenwidth()
			screen_h = win.winfo_screenheight()
			x = max(40, int((screen_w - width) / 2))
			y = max(40, int((screen_h - height) / 2))
			win.geometry(f'{width}x{height}+{x}+{y}')
			win.grab_set()
			ok_btn.focus_set()

			while not closed['done']:
				try:
					self._render()
					win.update_idletasks()
					win.update()
				except Exception:
					break
				time.sleep(0.05)
			return True, ''
		except Exception as ex:
			try:
				if win is not None:
					win.destroy()
			except Exception:
				pass
			return _show_blocking_message_dialog(msg_title, msg_body, ex)
