"""Robot agent authentication, job serialization, release package paths.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.http import JsonResponse

from ..models import RobotAgent, RobotAgentEvent
from ..utils.parsing import _safe_release_version


def _authenticate_agent(request, body):
	agent_code = str(
		body.get('agent_code')
		or request.headers.get('X-Agent-Code')
		or ''
	).strip()
	token = str(
		body.get('token')
		or request.headers.get('X-Agent-Token')
		or ''
	).strip()

	if not agent_code or not token:
		return None, JsonResponse({'ok': False, 'error': 'agent_code ve token gerekli.'}, status=401)

	agent = RobotAgent.objects.filter(code=agent_code, is_enabled=True).first()
	if not agent:
		return None, JsonResponse({'ok': False, 'error': 'Ajan bulunamadı veya pasif.'}, status=404)

	if not agent.verify_token(token):
		return None, JsonResponse({'ok': False, 'error': 'Token doğrulaması başarısız.'}, status=401)

	return agent, None


def _serialize_job(job):
	return {
		'job_id': job.pk,
		'command_type': job.command_type,
		'sap_process_id': job.sap_process_id,
		'priority': job.priority,
		'payload': job.payload or {},
		'created_at': job.created_at.isoformat() if job.created_at else None,
	}


def _package_zip_path(version):
	safe_version = _safe_release_version(version)
	package_dir = os.path.join(str(settings.MEDIA_ROOT), 'robot_agent', 'packages')
	os.makedirs(package_dir, exist_ok=True)
	file_name = f'SaggioRobotAgentPackage_{safe_version}.zip'
	full_path = os.path.join(package_dir, file_name)
	return full_path, file_name


def _create_agent_event(agent, level, message, *, job=None, extra=None):
	level_norm = str(level or 'info').strip().lower()
	if level_norm not in {'info', 'warning', 'error'}:
		level_norm = 'info'
	RobotAgentEvent.objects.create(
		agent=agent,
		job=job,
		level=level_norm,
		message=str(message or '').strip()[:2000],
		extra=extra if isinstance(extra, dict) else {},
	)

