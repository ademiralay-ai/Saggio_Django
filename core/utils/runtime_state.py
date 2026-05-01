"""In-memory runtime state for SAP processes.

Originally lived in ``core/views.py``. Provides a thread-safe per-process
state dictionary used by the SAP runtime (current step, pause/stop flags,
log buffer, etc.) and by the runtime status APIs.
"""
from __future__ import annotations

import threading
from datetime import datetime


_PROCESS_RUNTIME: dict = {}
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
		logs.append({
			'step': int(state.get('current_step', 0) or 0),
			'msg': msg,
		})
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
