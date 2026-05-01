"""Robot agent client endpoints (called by the agent runtime).

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import RobotAgent, RobotAgentRelease, RobotJob, SapProcess
from ..utils.http_utils import _read_json_body, _request_ip
from ..utils.parsing import _as_bool, _safe_release_version
from ..services.robot_release_service import (
	_authenticate_agent,
	_serialize_job,
	_create_agent_event,
)


@csrf_exempt
@require_POST
def agent_register(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	agent.name = str(body.get('name') or agent.name or agent.code).strip()[:180]
	agent.machine_name = str(body.get('machine_name') or '').strip()[:120]
	agent.host_name = str(body.get('host_name') or request.get_host() or '').strip()[:180]
	agent.os_user = str(body.get('os_user') or '').strip()[:120]
	agent.agent_version = str(body.get('agent_version') or '').strip()[:40]
	agent.ip_address = _request_ip(request)[:64]
	capabilities = body.get('capabilities')
	if isinstance(capabilities, dict):
		agent.capabilities = capabilities
	agent.status = 'online'
	agent.mark_seen(startup=True)
	agent.save()

	pending = RobotJob.objects.filter(status='queued').filter(
		Q(target_agent__isnull=True) | Q(target_agent=agent)
	).count()
	return JsonResponse({
		'ok': True,
		'agent': {
			'code': agent.code,
			'name': agent.name,
			'status': agent.status,
			'last_seen_at': agent.last_seen_at.isoformat() if agent.last_seen_at else None,
		},
		'pending_jobs': pending,
	})


@csrf_exempt
@require_POST
def agent_heartbeat(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	if agent.status != 'busy':
		agent.status = 'online'
	agent_version = str(body.get('agent_version') or '').strip()
	if agent_version:
		agent.agent_version = agent_version[:40]
	agent.ip_address = _request_ip(request)[:64]
	agent.mark_seen(startup=False)
	agent.save(update_fields=['status', 'agent_version', 'ip_address', 'last_seen_at', 'updated_at'])

	return JsonResponse({
		'ok': True,
		'server_time': timezone.now().isoformat(),
		'agent_status': agent.status,
		'desired_version': agent.desired_version,
	})


@csrf_exempt
@require_POST
def agent_check_update(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	current_version = str(body.get('current_version') or agent.agent_version or '').strip()
	if current_version:
		agent.agent_version = current_version[:40]

	latest = RobotAgentRelease.objects.filter(is_active=True).order_by('-created_at').first()
	desired = str(agent.desired_version or '').strip() or (latest.version if latest else '')
	available = bool(desired and current_version and desired != current_version)

	agent.mark_seen(startup=False)
	agent.save(update_fields=['agent_version', 'last_seen_at', 'updated_at'])

	result = {
		'ok': True,
		'agent_code': agent.code,
		'current_version': current_version,
		'desired_version': desired,
		'update_available': available,
	}
	if latest:
		release_download_url = latest.download_url or f"/api/robot-agent/releases/download/{latest.version}/"
		result['release'] = {
			'version': latest.version,
			'download_url': release_download_url,
			'checksum_sha256': latest.checksum_sha256,
			'is_mandatory': bool(latest.is_mandatory),
			'release_notes': latest.release_notes,
		}
	return JsonResponse(result)


@csrf_exempt
@require_POST
def agent_log_event(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	message = str(body.get('message') or '').strip()
	if not message:
		return JsonResponse({'ok': False, 'error': 'message gerekli.'}, status=400)

	level = str(body.get('level') or 'info').strip().lower()
	job_id = body.get('job_id')
	job = None
	if job_id:
		job = RobotJob.objects.filter(pk=job_id).first()

	_create_agent_event(agent, level, message, job=job, extra=body.get('extra'))
	agent.mark_seen(startup=False)
	agent.save(update_fields=['last_seen_at', 'updated_at'])
	return JsonResponse({'ok': True})


@csrf_exempt
@require_POST
def agent_pull_job(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	now = timezone.now()
	with transaction.atomic():
		job = RobotJob.objects.select_for_update().filter(
			status='queued'
		).filter(
			Q(target_agent__isnull=True) | Q(target_agent=agent)
		).order_by('-priority', 'created_at').first()

		if not job:
			agent.mark_seen(startup=False)
			if agent.status != 'busy':
				agent.status = 'online'
			agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])
			return JsonResponse({'ok': True, 'job': None})

		if not job.started_at:
			job.started_at = now
		job.target_agent = agent
		job.status = 'dispatched'
		job.last_heartbeat_at = now
		job.lease_expires_at = now + timedelta(minutes=10)
		job.save(update_fields=['target_agent', 'status', 'started_at', 'last_heartbeat_at', 'lease_expires_at', 'updated_at'])

	agent.status = 'busy'
	agent.mark_seen(startup=False)
	agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

	return JsonResponse({'ok': True, 'job': _serialize_job(job)})


@csrf_exempt
@require_POST
def agent_job_update(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	job_id = body.get('job_id')
	status_value = str(body.get('status') or '').strip().lower()
	if not job_id or status_value not in {'running', 'succeeded', 'failed', 'canceled'}:
		return JsonResponse({'ok': False, 'error': 'job_id ve geçerli status gerekli.'}, status=400)

	job = RobotJob.objects.filter(pk=job_id, target_agent=agent).first()
	if not job:
		return JsonResponse({'ok': False, 'error': 'İş bulunamadı veya ajan yetkisiz.'}, status=404)

	now = timezone.now()
	job.status = status_value
	job.last_heartbeat_at = now
	if status_value == 'running' and not job.started_at:
		job.started_at = now

	if status_value in {'succeeded', 'failed', 'canceled'}:
		job.finished_at = now
		job.lease_expires_at = None
		agent.status = 'online'
	else:
		agent.status = 'busy'

	result_message = body.get('result_message')
	if result_message is not None:
		job.result_message = str(result_message)
	result_payload = body.get('result_payload')
	if isinstance(result_payload, dict):
		job.result_payload = result_payload

	job.save()
	agent.mark_seen(startup=False)
	agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

	return JsonResponse({'ok': True})


@csrf_exempt
@require_POST
def agent_process_definition(request):
	"""Ajanın ilgili SAP sürecini (adımlar + runtime config) çekmesi için endpoint.

	Body: { agent_code, token, sap_process_id }
	Cevap: { ok, process: { id, name, ghost_overlay_enabled, office_express_auto_close,
	         telegram_notifications_enabled, telegram_voice_enabled,
	         mail_notifications_enabled, sap_retry_enabled,
	         sap_retry_interval_minutes, sap_retry_max_duration_minutes,
	         flow_config, steps: [ { id, order, step_type, label, config } ] } }
	"""
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	sap_process_id = body.get('sap_process_id')
	try:
		sap_process_id = int(sap_process_id)
	except (TypeError, ValueError):
		return JsonResponse({'ok': False, 'error': 'sap_process_id gerekli (int).'}, status=400)

	proc = SapProcess.objects.filter(pk=sap_process_id).first()
	if not proc:
		return JsonResponse({'ok': False, 'error': 'SAP süreç bulunamadı.'}, status=404)

	steps = list(proc.steps.all().order_by('order', 'pk').values(
		'id', 'order', 'step_type', 'label', 'config'
	))

	agent.mark_seen(startup=False)
	agent.save(update_fields=['last_seen_at', 'updated_at'])

	return JsonResponse({
		'ok': True,
		'process': {
			'id': proc.pk,
			'name': proc.name,
			'description': proc.description,
			'ghost_overlay_enabled': proc.ghost_overlay_enabled,
			'office_express_auto_close': proc.office_express_auto_close,
			'telegram_notifications_enabled': proc.telegram_notifications_enabled,
			'telegram_voice_enabled': proc.telegram_voice_enabled,
			'mail_notifications_enabled': proc.mail_notifications_enabled,
			'sap_retry_enabled': proc.sap_retry_enabled,
			'sap_retry_interval_minutes': proc.sap_retry_interval_minutes,
			'sap_retry_max_duration_minutes': proc.sap_retry_max_duration_minutes,
			'flow_config': proc.flow_config or {},
			'steps': steps,
		},
	})


@csrf_exempt
@require_POST
def agent_run_process(request):
	"""Ajan adına gerçek SAP sürecini bu makinede async olarak başlat.

	Aynı makinede çalışan Django + agent senaryosu (Step 3 - aşama 1).
	Mevcut `sap_process_run_preview` altyapısını async_mode=True ile çağırır.
	"""
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	sap_process_id = body.get('sap_process_id')
	try:
		sap_process_id = int(sap_process_id)
	except (TypeError, ValueError):
		return JsonResponse({'ok': False, 'error': 'sap_process_id gerekli (int).'}, status=400)

	proc = SapProcess.objects.filter(pk=sap_process_id).first()
	if not proc:
		return JsonResponse({'ok': False, 'error': 'SAP süreç bulunamadı.'}, status=404)

	# Lokal import (circular import'dan kaçınmak için).
	from .sap_runtime_api import sap_process_run_preview
	from django.http import HttpRequest

	# Çalışan/takılı durumu temizlemek için _force_reset.
	child_req = HttpRequest()
	child_req.method = 'POST'
	child_req.META = dict(request.META or {})
	child_req.user = getattr(request, 'user', None)
	payload = {
		'async_mode': True,
		'_force_reset': True,
		'_triggered_by_agent': agent.code,
		'_triggered_by_agent_ip': _request_ip(request),
		'_job_id': int(body.get('_job_id')) if body.get('_job_id') else None,
	}
	child_req._body = json.dumps(payload).encode('utf-8')

	try:
		resp = sap_process_run_preview(child_req, sap_process_id)
	except Exception as ex:
		return JsonResponse({'ok': False, 'error': f'Süreç başlatılamadı: {ex}'}, status=500)

	# resp bir JsonResponse — content'i tekrar parse edelim.
	try:
		data = json.loads(resp.content.decode('utf-8'))
	except Exception:
		data = {'ok': True, 'started': True}

	agent.mark_seen(startup=False)
	agent.save(update_fields=['last_seen_at', 'updated_at'])

	return JsonResponse({'ok': bool(data.get('ok', True)), 'started': bool(data.get('started', True)), 'error': data.get('error')})


@csrf_exempt
@require_POST
def agent_run_process_status(request):
	"""Ajanın çalıştırdığı sürecin canlı durumunu döndürür.

	Body: { agent_code, token, sap_process_id }
	"""
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	agent, err = _authenticate_agent(request, body)
	if err:
		return err

	sap_process_id = body.get('sap_process_id')
	try:
		sap_process_id = int(sap_process_id)
	except (TypeError, ValueError):
		return JsonResponse({'ok': False, 'error': 'sap_process_id gerekli (int).'}, status=400)

	from ..utils.runtime_state import _runtime_get
	state = _runtime_get(sap_process_id)
	if state is None:
		state = {
			'running': False,
			'paused': False,
			'stop_requested': False,
			'current_step': 0,
			'total_steps': 0,
			'step_name': '',
			'logs': [],
		}

	return JsonResponse({'ok': True, 'state': state})


