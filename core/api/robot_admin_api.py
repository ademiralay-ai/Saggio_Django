"""Robot admin endpoints (status, jobs, releases, builds, dispatch).

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
	RobotAgent,
	RobotAgentEvent,
	RobotAgentRelease,
	RobotJob,
	SapProcess,
)
from ..utils.http_utils import _read_json_body, _request_ip
from ..utils.parsing import _as_bool, _safe_release_version
from ..services.robot_release_service import (
	_serialize_job,
	_package_zip_path,
	_create_agent_event,
)


def robot_agent_status(request):
	rows = []
	for agent in RobotAgent.objects.all().order_by('code'):
		queued = RobotJob.objects.filter(status='queued').filter(
			Q(target_agent__isnull=True) | Q(target_agent=agent)
		).count()
		version_state = 'ok'
		if agent.desired_version and agent.agent_version and agent.desired_version != agent.agent_version:
			version_state = 'outdated'
		elif agent.desired_version and not agent.agent_version:
			version_state = 'unknown'
		rows.append({
			'code': agent.code,
			'name': agent.name,
			'status': agent.status,
			'is_enabled': agent.is_enabled,
			'agent_version': agent.agent_version,
			'desired_version': agent.desired_version,
			'version_state': version_state,
			'last_seen_at': agent.last_seen_at.isoformat() if agent.last_seen_at else None,
			'machine_name': agent.machine_name,
			'ip_address': agent.ip_address,
			'pending_jobs': queued,
		})
	return JsonResponse({'ok': True, 'agents': rows})


def robot_job_list(request):
	status_filter = str(request.GET.get('status') or '').strip().lower()
	agent_code_filter = str(request.GET.get('agent_code') or '').strip()
	search = str(request.GET.get('q') or '').strip()
	limit_param = request.GET.get('limit', 50)
	try:
		limit = max(1, min(200, int(limit_param)))
	except (TypeError, ValueError):
		limit = 50

	jobs_qs = RobotJob.objects.select_related('target_agent', 'sap_process').order_by('-created_at')
	if status_filter:
		jobs_qs = jobs_qs.filter(status=status_filter)
	if agent_code_filter:
		jobs_qs = jobs_qs.filter(target_agent__code=agent_code_filter)
	if search:
		jobs_qs = jobs_qs.filter(
			Q(result_message__icontains=search)
			| Q(command_type__icontains=search)
			| Q(target_agent__code__icontains=search)
			| Q(sap_process__name__icontains=search)
		)

	jobs = jobs_qs[:limit]
	rows = []
	for job in jobs:
		rows.append({
			'job_id': job.pk,
			'status': job.status,
			'command_type': job.command_type,
			'priority': job.priority,
			'target_agent_code': job.target_agent.code if job.target_agent else '',
			'target_agent_name': job.target_agent.name if job.target_agent else '',
			'target_agent_ip': job.target_agent.ip_address if job.target_agent else '',
			'sap_process_id': job.sap_process_id,
			'sap_process_name': job.sap_process.name if job.sap_process else '',
			'result_message': job.result_message or '',
			'result_payload': job.result_payload if isinstance(job.result_payload, dict) else {},
			'created_at': job.created_at.isoformat() if job.created_at else None,
			'started_at': job.started_at.isoformat() if job.started_at else None,
			'finished_at': job.finished_at.isoformat() if job.finished_at else None,
		})

	return JsonResponse({'ok': True, 'jobs': rows})


def robot_agent_event_list(request):
	agent_code = str(request.GET.get('agent_code') or '').strip()
	if not agent_code:
		return JsonResponse({'ok': False, 'error': 'agent_code gerekli.'}, status=400)
	limit_param = request.GET.get('limit', 50)
	try:
		limit = max(1, min(500, int(limit_param)))
	except (TypeError, ValueError):
		limit = 50
	agent = RobotAgent.objects.filter(code=agent_code).first()
	if not agent:
		return JsonResponse({'ok': False, 'error': 'Ajan bulunamadı.'}, status=404)
	rows = []
	events = RobotAgentEvent.objects.select_related('job').filter(agent=agent).order_by('-created_at')[:limit]
	for ev in events:
		rows.append({
			'id': ev.pk,
			'level': ev.level,
			'message': ev.message,
			'job_id': ev.job_id,
			'created_at': ev.created_at.isoformat() if ev.created_at else None,
		})
	return JsonResponse({'ok': True, 'events': rows})


def robot_release_list(request):
	releases = RobotAgentRelease.objects.all().order_by('-created_at')
	rows = []
	for rel in releases:
		download_path = ''
		if rel.setup_file:
			download_path = f"/api/robot-agent/releases/download/{rel.version}/"
		package_full_path, _ = _package_zip_path(rel.version)
		package_download_path = f"/api/robot-agent/releases/download-package/{rel.version}/" if os.path.exists(package_full_path) else ''
		rows.append({
			'version': rel.version,
			'release_notes': rel.release_notes,
			'download_url': rel.download_url,
			'setup_file': rel.setup_file,
			'download_path': download_path,
			'package_download_path': package_download_path,
			'checksum_sha256': rel.checksum_sha256,
			'install_command': rel.install_command,
			'is_active': rel.is_active,
			'is_mandatory': rel.is_mandatory,
			'created_by': rel.created_by,
			'created_at': rel.created_at.isoformat() if rel.created_at else None,
		})
	return JsonResponse({'ok': True, 'releases': rows})


@require_POST
def robot_release_save(request):
	if request.content_type and request.content_type.startswith('multipart/form-data'):
		body = request.POST
		setup_upload = request.FILES.get('setup_file')
	else:
		body = _read_json_body(request)
		if body is None:
			return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
		setup_upload = None

	version = str(body.get('version') or '').strip()
	if not version:
		return JsonResponse({'ok': False, 'error': 'version gerekli.'}, status=400)
	release, _ = RobotAgentRelease.objects.get_or_create(version=version)
	release.release_notes = str(body.get('release_notes') or '').strip()
	release.download_url = str(body.get('download_url') or '').strip()
	release.checksum_sha256 = str(body.get('checksum_sha256') or '').strip()
	release.install_command = str(body.get('install_command') or '').strip()
	release.is_active = _as_bool(body.get('is_active', True), True)
	release.is_mandatory = _as_bool(body.get('is_mandatory', False), False)
	created_by = str(body.get('created_by') or '').strip()
	if not created_by and getattr(request, 'user', None) and request.user.is_authenticated:
		created_by = str(request.user.get_username() or '').strip()
	release.created_by = created_by[:120]

	if setup_upload is not None:
		upload_name = str(getattr(setup_upload, 'name', '') or '').lower()
		if not upload_name.endswith('.exe'):
			return JsonResponse({'ok': False, 'error': 'Sadece .exe dosya yüklenebilir.'}, status=400)
		rel_dir = os.path.join(str(settings.MEDIA_ROOT), 'robot_agent', 'releases')
		os.makedirs(rel_dir, exist_ok=True)
		safe_version = re.sub(r'[^0-9A-Za-z._-]+', '_', version).strip('_') or 'release'
		file_name = f'robot-agent-{safe_version}.exe'
		full_path = os.path.join(rel_dir, file_name)
		with open(full_path, 'wb') as fp:
			for chunk in setup_upload.chunks():
				fp.write(chunk)
		release.setup_file = os.path.join('robot_agent', 'releases', file_name).replace('\\', '/')
		if not release.download_url:
			release.download_url = f"/api/robot-agent/releases/download/{version}/"

	release.save()
	return JsonResponse({'ok': True, 'version': release.version, 'download_url': release.download_url, 'setup_file': release.setup_file})


def robot_release_download(request, version):
	version_val = str(version or '').strip()
	release = RobotAgentRelease.objects.filter(version=version_val).first()
	if not release:
		return JsonResponse({'ok': False, 'error': 'Release bulunamadı.'}, status=404)
	if not release.setup_file:
		return JsonResponse({'ok': False, 'error': 'Bu release için setup dosyası yok.'}, status=404)
	full_path = os.path.join(str(settings.MEDIA_ROOT), release.setup_file)
	if not os.path.exists(full_path):
		return JsonResponse({'ok': False, 'error': 'Dosya bulunamadı.'}, status=404)
	with open(full_path, 'rb') as fp:
		content = fp.read()
	resp = HttpResponse(content, content_type='application/octet-stream')
	resp['Content-Disposition'] = f'attachment; filename="{os.path.basename(full_path)}"'
	return resp


def robot_release_download_package(request, version):
	version_val = str(version or '').strip()
	release = RobotAgentRelease.objects.filter(version=version_val).first()
	if not release:
		return JsonResponse({'ok': False, 'error': 'Release bulunamadı.'}, status=404)
	full_path, file_name = _package_zip_path(version_val)
	if not os.path.exists(full_path):
		return JsonResponse({'ok': False, 'error': 'Paket dosyası bulunamadı.'}, status=404)
	with open(full_path, 'rb') as fp:
		content = fp.read()
	resp = HttpResponse(content, content_type='application/zip')
	resp['Content-Disposition'] = f'attachment; filename="{file_name}"'
	return resp


@require_POST
def robot_release_deploy(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	version = str(body.get('version') or '').strip()
	if not version:
		return JsonResponse({'ok': False, 'error': 'version gerekli.'}, status=400)
	release = RobotAgentRelease.objects.filter(version=version).first()
	if not release:
		return JsonResponse({'ok': False, 'error': 'Release bulunamadı.'}, status=404)

	scope = str(body.get('scope') or 'outdated').strip().lower()
	agent_codes = body.get('agent_codes') if isinstance(body.get('agent_codes'), list) else []

	agents_qs = RobotAgent.objects.filter(is_enabled=True)
	if scope == 'single':
		if not agent_codes:
			return JsonResponse({'ok': False, 'error': 'single scope için agent_codes gerekli.'}, status=400)
		agents_qs = agents_qs.filter(code__in=[str(x).strip() for x in agent_codes if str(x).strip()])
	elif scope == 'all':
		pass
	else:
		agents_qs = agents_qs.exclude(agent_version=version)

	agents = list(agents_qs)
	if not agents:
		return JsonResponse({'ok': False, 'error': 'Dağıtıma uygun ajan bulunamadı.'}, status=400)

	default_download = release.download_url or f"/api/robot-agent/releases/download/{release.version}/"
	if default_download.startswith('/'):
		default_download = request.build_absolute_uri(default_download)
	default_cmd = release.install_command or 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=\"{download_url}\"; $v=\"{version}\"; $dst=\"C:/SaggioRobotAgent/agent-update-$v.exe\"; Invoke-WebRequest -Uri $u -OutFile $dst; Start-Process -FilePath $dst -ArgumentList \"/update\" -WindowStyle Hidden"'
	jobs = []
	for agent in agents:
		command = default_cmd.format(version=release.version, download_url=default_download)
		job = RobotJob.objects.create(
			command_type='run_command',
			target_agent=agent,
			status='queued',
			priority=300,
			requested_by=str(body.get('requested_by') or 'panel')[:120],
			payload={
				'command': command,
				'release_version': release.version,
				'download_url': default_download,
				'kind': 'agent_update',
			},
		)
		_create_agent_event(agent, 'info', f'Panelden update işi kuyruğa alındı: {release.version}', job=job)
		jobs.append(job.pk)

	return JsonResponse({'ok': True, 'jobs_created': len(jobs), 'job_ids': jobs, 'version': release.version})


@require_POST
def robot_build_setup_exe(request):
	body = _read_json_body(request)
	if body is None:
		body = {}

	version = str(body.get('version') or '').strip() or datetime.now().strftime('bootstrap-%Y%m%d-%H%M%S')
	force_rebuild = _as_bool(body.get('force_rebuild', False), False)

	safe_version = re.sub(r'[^0-9A-Za-z._-]+', '_', version).strip('_') or 'bootstrap'
	base_agent_dir = os.path.join(str(settings.BASE_DIR), 'robot_agent')
	service_script = os.path.join(base_agent_dir, 'robot_agent_service.py')
	runtime_script = os.path.join(base_agent_dir, 'agent_runtime.py')
	config_example = os.path.join(base_agent_dir, 'config.example.json')
	for required_path in (service_script, runtime_script, config_example):
		if not os.path.exists(required_path):
			return JsonResponse({'ok': False, 'error': f'Agent build dosyası bulunamadı: {required_path}'}, status=404)

	release_dir = os.path.join(str(settings.MEDIA_ROOT), 'robot_agent', 'releases')
	os.makedirs(release_dir, exist_ok=True)
	output_name = f'SaggioRobotAgentSetup_{safe_version}.exe'
	output_path = os.path.join(release_dir, output_name)
	rel_path = os.path.join('robot_agent', 'releases', output_name).replace('\\', '/')

	if os.path.exists(output_path) and not force_rebuild:
		release, _ = RobotAgentRelease.objects.get_or_create(version=version)
		release.setup_file = rel_path
		release.download_url = f'/api/robot-agent/releases/download/{version}/'
		if not release.install_command:
			release.install_command = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=\"{download_url}\"; $v=\"{version}\"; $dst=\"C:/SaggioRobotAgent/agent-update-$v.exe\"; Invoke-WebRequest -Uri $u -OutFile $dst; Start-Process -FilePath $dst -ArgumentList \"/update\" -WindowStyle Hidden"'
		release.is_active = True
		release.save()
		return JsonResponse({
			'ok': True,
			'built': False,
			'version': version,
			'download_url': release.download_url,
			'message': 'Var olan setup.exe kullanıldı.',
		})

	build_root = os.path.join(str(settings.MEDIA_ROOT), 'robot_agent', '_pyinstaller')
	work_dir = os.path.join(build_root, 'work', safe_version)
	dist_dir = os.path.join(build_root, 'dist', safe_version)
	spec_dir = os.path.join(build_root, 'spec', safe_version)
	src_dir = os.path.join(build_root, 'src', safe_version)
	os.makedirs(work_dir, exist_ok=True)
	os.makedirs(dist_dir, exist_ok=True)
	os.makedirs(spec_dir, exist_ok=True)
	os.makedirs(src_dir, exist_ok=True)

	try:
		pip_cmd = [sys.executable, '-m', 'pip', 'install', 'pyinstaller']
		pip_run = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=420, encoding='utf-8', errors='replace')
		if pip_run.returncode != 0:
			err = (pip_run.stderr or pip_run.stdout or 'pyinstaller kurulamadı')[-2000:]
			return JsonResponse({'ok': False, 'error': f'PyInstaller kurulum hatası: {err}'}, status=500)

		service_dist = os.path.join(dist_dir, 'service')
		service_work = os.path.join(work_dir, 'service')
		service_spec = os.path.join(spec_dir, 'service')
		installer_dist = os.path.join(dist_dir, 'setup')
		installer_work = os.path.join(work_dir, 'setup')
		installer_spec = os.path.join(spec_dir, 'setup')
		for p in (service_dist, service_work, service_spec, installer_dist, installer_work, installer_spec):
			os.makedirs(p, exist_ok=True)

		service_build_cmd = [
			sys.executable,
			'-m',
			'PyInstaller',
			'--noconfirm',
			'--clean',
			'--onefile',
			'--name',
			'SaggioRobotAgentService',
			service_script,
			'--distpath',
			service_dist,
			'--workpath',
			service_work,
			'--specpath',
			service_spec,
		]
		service_run = subprocess.run(service_build_cmd, capture_output=True, text=True, timeout=1800, encoding='utf-8', errors='replace')
		if service_run.returncode != 0:
			err = (service_run.stderr or service_run.stdout or 'service build başarısız')[-4000:]
			return JsonResponse({'ok': False, 'error': f'servis exe üretilemedi: {err}'}, status=500)

		service_exe = os.path.join(service_dist, 'SaggioRobotAgentService.exe')
		if not os.path.exists(service_exe):
			return JsonResponse({'ok': False, 'error': 'Servis exe dosyası bulunamadı.'}, status=500)

		installer_script = os.path.join(src_dir, 'setup_installer_entry.py')
		installer_code = f'''import os
import shutil
import subprocess
import sys

SERVICE_NAME = "SaggioRobotAgent"
BASE_DIR = r"C:/SaggioRobotAgent"
SERVICE_EXE_NAME = "SaggioRobotAgentService.exe"


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _payload_dir():
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(__file__)), "payload")


def install_or_update():
    os.makedirs(BASE_DIR, exist_ok=True)
    payload = _payload_dir()
    service_src = os.path.join(payload, SERVICE_EXE_NAME)
    config_src = os.path.join(payload, "config.example.json")
    if not os.path.exists(service_src):
        raise RuntimeError("Payload içinde service exe yok.")

    service_dst = os.path.join(BASE_DIR, SERVICE_EXE_NAME)
    config_dst = os.path.join(BASE_DIR, "config.json")
    config_example_dst = os.path.join(BASE_DIR, "config.example.json")

    _run([service_dst, "stop"])
    _run([service_dst, "remove"])

    shutil.copyfile(service_src, service_dst)
    if os.path.exists(config_src):
        shutil.copyfile(config_src, config_example_dst)
    if not os.path.exists(config_dst) and os.path.exists(config_src):
        shutil.copyfile(config_src, config_dst)

    install_run = _run([service_dst, "--startup", "auto", "install"])
    if install_run.returncode != 0:
        err = (install_run.stderr or install_run.stdout or "service install failed")[-2000:]
        raise RuntimeError(err)

    start_run = _run([service_dst, "start"])
    if start_run.returncode != 0:
        err = (start_run.stderr or start_run.stdout or "service start failed")[-2000:]
        raise RuntimeError(err)

    print("Saggio Robot Agent kuruldu/guncellendi. Version: {safe_version}")
    print("Config: C:/SaggioRobotAgent/config.json")


def main():
    try:
        install_or_update()
    except Exception as ex:
        print(f"[ERROR] {{ex}}")
        sys.exit(1)


if __name__ == "__main__":
    main()
'''
		with open(installer_script, 'w', encoding='utf-8') as fp:
			fp.write(installer_code)

		installer_build_cmd = [
			sys.executable,
			'-m',
			'PyInstaller',
			'--noconfirm',
			'--clean',
			'--onefile',
			'--name',
			'SaggioRobotAgentSetup',
			'--add-data',
			f'{service_exe}{os.pathsep}payload',
			'--add-data',
			f'{config_example}{os.pathsep}payload',
			installer_script,
			'--distpath',
			installer_dist,
			'--workpath',
			installer_work,
			'--specpath',
			installer_spec,
		]
		installer_run = subprocess.run(installer_build_cmd, capture_output=True, text=True, timeout=1800, encoding='utf-8', errors='replace')
		if installer_run.returncode != 0:
			err = (installer_run.stderr or installer_run.stdout or 'setup build başarısız')[-4000:]
			return JsonResponse({'ok': False, 'error': f'setup.exe üretilemedi: {err}'}, status=500)

		built_exe = os.path.join(installer_dist, 'SaggioRobotAgentSetup.exe')
		if not os.path.exists(built_exe):
			return JsonResponse({'ok': False, 'error': 'Build tamamlandı ama exe dosyası bulunamadı.'}, status=500)

		shutil.copyfile(built_exe, output_path)
		release, _ = RobotAgentRelease.objects.get_or_create(version=version)
		release.setup_file = rel_path
		release.download_url = f'/api/robot-agent/releases/download/{version}/'
		if not release.install_command:
			release.install_command = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=\"{download_url}\"; $v=\"{version}\"; $dst=\"C:/SaggioRobotAgent/agent-update-$v.exe\"; Invoke-WebRequest -Uri $u -OutFile $dst; Start-Process -FilePath $dst -ArgumentList \"/update\" -WindowStyle Hidden"'
		release.is_active = True
		release.created_by = 'panel-builder'
		release.save()

		return JsonResponse({
			'ok': True,
			'built': True,
			'version': version,
			'download_url': release.download_url,
			'message': 'setup.exe başarıyla üretildi.',
		})
	except subprocess.TimeoutExpired:
		return JsonResponse({'ok': False, 'error': 'setup.exe üretimi zaman aşımına uğradı.'}, status=500)


@require_POST
def robot_build_install_package(request):
	body = _read_json_body(request)
	if body is None:
		body = {}

	version = str(body.get('version') or '').strip() or datetime.now().strftime('bootstrap-%Y%m%d-%H%M%S')
	force_rebuild = _as_bool(body.get('force_rebuild', False), False)
	safe_version = _safe_release_version(version)

	base_agent_dir = os.path.join(str(settings.BASE_DIR), 'robot_agent')
	files_to_include = [
		('agent_runtime.py', 'agent_runtime.py'),
		('robot_agent_service.py', 'robot_agent_service.py'),
		('config.example.json', 'config.example.json'),
	]
	for src_name, _ in files_to_include:
		src_path = os.path.join(base_agent_dir, src_name)
		if not os.path.exists(src_path):
			return JsonResponse({'ok': False, 'error': f'Paket için gerekli dosya yok: {src_path}'}, status=404)

	zip_full_path, zip_file_name = _package_zip_path(version)
	if os.path.exists(zip_full_path) and not force_rebuild:
		release, _ = RobotAgentRelease.objects.get_or_create(version=version)
		release.is_active = True
		if not release.download_url:
			release.download_url = f'/api/robot-agent/releases/download-package/{version}/'
		release.save(update_fields=['is_active', 'download_url'])
		return JsonResponse({
			'ok': True,
			'built': False,
			'version': version,
			'package_url': f'/api/robot-agent/releases/download-package/{version}/',
			'message': 'Var olan kurulum paketi kullanıldı.',
		})

	install_ps1 = '''$ErrorActionPreference = "Stop"
$Base = "C:/SaggioRobotAgent"
$Venv = "$Base/.venv"
$TaskName = "SaggioRobotAgent"

New-Item -ItemType Directory -Force -Path $Base | Out-Null
Copy-Item -Force "$PSScriptRoot/agent_runtime.py" "$Base/agent_runtime.py"
Copy-Item -Force "$PSScriptRoot/robot_agent_service.py" "$Base/robot_agent_service.py"
if (Test-Path "$PSScriptRoot/update_agent.ps1") {
	Copy-Item -Force "$PSScriptRoot/update_agent.ps1" "$Base/update_agent.ps1"
}
if (-not (Test-Path "$Base/config.json") -and (Test-Path "$PSScriptRoot/config.example.json")) {
	Copy-Item -Force "$PSScriptRoot/config.example.json" "$Base/config.json"
}

if (-not (Test-Path $Venv)) {
	$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
	$pythonExe = Get-Command python -ErrorAction SilentlyContinue
	if ($pyLauncher) {
		& py -3.11 -m venv $Venv
		if (-not (Test-Path $Venv)) {
			& py -3 -m venv $Venv
		}
	} elseif ($pythonExe) {
		& python -m venv $Venv
	} else {
		throw "Python bulunamadı."
	}
}

& "$Venv/Scripts/pip.exe" install --upgrade pip
& "$Venv/Scripts/pip.exe" install requests

$PythonExe = "$Venv/Scripts/python.exe"
$ScriptPath = "$Base/agent_runtime.py"
$RunnerPath = "$Base/run_agent.ps1"
if (-not (Test-Path $PythonExe)) {
	throw "Python venv bulunamadı: $PythonExe"
}

$runnerContent = @"
$ErrorActionPreference = "Stop"
$Base = "C:/SaggioRobotAgent"
$env:SAGGIO_AGENT_CONFIG = "$Base/config.json"
& "$PythonExe" -u "$ScriptPath" *>> "$Base/agent_runner.log"
"@
Set-Content -Path $RunnerPath -Value $runnerContent -Encoding UTF8

try {
	Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch {
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $RunnerPath + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$userId = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).Name
try {
	$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
	Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
} catch {
	Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $userId -RunLevel Highest -Force | Out-Null
}
Start-ScheduledTask -TaskName $TaskName

Write-Host "Saggio Robot Agent kurulumu tamamlandı. (Task Scheduler)"
'''

	update_ps1 = '''param(
	[Parameter(Mandatory=$true)][string]$Version,
	[Parameter(Mandatory=$true)][string]$Url
)
$ErrorActionPreference = "Stop"
$Base = "C:/SaggioRobotAgent"
$Venv = "$Base/.venv"
$TaskName = "SaggioRobotAgent"
$TmpRoot = "$env:TEMP/SaggioRobotAgentUpdate"
$ZipPath = "$TmpRoot/agent-$Version.zip"
$ExtractPath = "$TmpRoot/extract-$Version"

New-Item -ItemType Directory -Force -Path $Base | Out-Null
New-Item -ItemType Directory -Force -Path $TmpRoot | Out-Null
if (Test-Path $ExtractPath) {
	Remove-Item -Recurse -Force $ExtractPath
}

Invoke-WebRequest -Uri $Url -OutFile $ZipPath
Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force

try {
	Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
} catch {
}

Copy-Item -Force "$ExtractPath/agent_runtime.py" "$Base/agent_runtime.py"
Copy-Item -Force "$ExtractPath/robot_agent_service.py" "$Base/robot_agent_service.py"
Copy-Item -Force "$ExtractPath/update_agent.ps1" "$Base/update_agent.ps1"
if (-not (Test-Path "$Base/config.json") -and (Test-Path "$ExtractPath/config.example.json")) {
	Copy-Item -Force "$ExtractPath/config.example.json" "$Base/config.json"
}

if (-not (Test-Path $Venv)) {
	$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
	$pythonExe = Get-Command python -ErrorAction SilentlyContinue
	if ($pyLauncher) {
		& py -3.11 -m venv $Venv
		if (-not (Test-Path $Venv)) {
			& py -3 -m venv $Venv
		}
	} elseif ($pythonExe) {
		& python -m venv $Venv
	} else {
		throw "Python bulunamadı."
	}
}

& "$Venv/Scripts/pip.exe" install --upgrade pip
& "$Venv/Scripts/pip.exe" install requests

$PythonExe = "$Venv/Scripts/python.exe"
$ScriptPath = "$Base/agent_runtime.py"
$RunnerPath = "$Base/run_agent.ps1"
if (-not (Test-Path $PythonExe)) {
	throw "Python venv bulunamadı: $PythonExe"
}

$runnerContent = @"
$ErrorActionPreference = "Stop"
$Base = "C:/SaggioRobotAgent"
$env:SAGGIO_AGENT_CONFIG = "$Base/config.json"
& "$PythonExe" -u "$ScriptPath" *>> "$Base/agent_runner.log"
"@
Set-Content -Path $RunnerPath -Value $runnerContent -Encoding UTF8

try {
	Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch {
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $RunnerPath + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$userId = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).Name
try {
	$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
	Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
} catch {
	Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $userId -RunLevel Highest -Force | Out-Null
}
Start-ScheduledTask -TaskName $TaskName

try {
	$cfgPath = "$Base/config.json"
	if (Test-Path $cfgPath) {
		$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
		$cfg.agent_version = $Version
		$cfg | ConvertTo-Json -Depth 20 | Set-Content -Path $cfgPath -Encoding UTF8
	}
} catch {
}

Write-Host "Ajan güncelleme tamamlandı. Version: $Version"
'''

	uninstall_ps1 = '''$ErrorActionPreference = "SilentlyContinue"
$Base = "C:/SaggioRobotAgent"
$TaskName = "SaggioRobotAgent"
try {
	Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
} catch {
}
try {
	Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch {
}
Write-Host "Saggio Robot Agent gorev kaldirma tamamlandi."
'''

	readme_txt = f'''Saggio Robot Agent Kurumsal Paket\n\nVersion: {safe_version}\n\nCrowdStrike Uyumlu Akis (EXE yok, servis yok):\n1) Zip'i robota çıkart\n2) Yönetici PowerShell aç\n3) install_agent.ps1 çalıştır\n\nKurulum modeli:\n- Ajan, Windows Task Scheduler üzerinden mevcut kullanıcı ile OnLogon tetiklenir.\n- SAP/GUI otomasyonu için robot kullanıcısının oturumu açık olmalıdır.\n\nGerekli ayar:\n- C:/SaggioRobotAgent/config.json içine server_base_url, agent_code, token değerlerini gir.\n\nMerkezi guncelleme:\n- Panelden deploy yapıldığında C:/SaggioRobotAgent/update_agent.ps1 çağrılır ve zip paketi indirip ajanı yeniler.\n'''

	tmp_root = os.path.join(str(settings.MEDIA_ROOT), 'robot_agent', '_tmp_pkg', safe_version)
	os.makedirs(tmp_root, exist_ok=True)
	for src_name, out_name in files_to_include:
		shutil.copyfile(os.path.join(base_agent_dir, src_name), os.path.join(tmp_root, out_name))
	with open(os.path.join(tmp_root, 'install_agent.ps1'), 'w', encoding='utf-8') as fp:
		fp.write(install_ps1)
	with open(os.path.join(tmp_root, 'update_agent.ps1'), 'w', encoding='utf-8') as fp:
		fp.write(update_ps1)
	with open(os.path.join(tmp_root, 'uninstall_agent.ps1'), 'w', encoding='utf-8') as fp:
		fp.write(uninstall_ps1)
	with open(os.path.join(tmp_root, 'README.txt'), 'w', encoding='utf-8') as fp:
		fp.write(readme_txt)

	os.makedirs(os.path.dirname(zip_full_path), exist_ok=True)
	with zipfile.ZipFile(zip_full_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
		for item in os.listdir(tmp_root):
			item_path = os.path.join(tmp_root, item)
			if os.path.isfile(item_path):
				zf.write(item_path, arcname=item)

	release, _ = RobotAgentRelease.objects.get_or_create(version=version)
	release.is_active = True
	release.download_url = f'/api/robot-agent/releases/download-package/{version}/'
	release.install_command = 'powershell -NoProfile -ExecutionPolicy Bypass -File C:/SaggioRobotAgent/update_agent.ps1 -Version "{version}" -Url "{download_url}"'
	if not release.release_notes:
		release.release_notes = 'Kurumsal kurulum paketi (zip + powershell) üretildi.'
	release.save()

	return JsonResponse({
		'ok': True,
		'built': True,
		'version': version,
		'package_url': f'/api/robot-agent/releases/download-package/{version}/',
		'file_name': zip_file_name,
		'message': 'Kurumsal kurulum paketi hazır.',
	})


@require_POST
def robot_set_desired_version(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
	version = str(body.get('version') or '').strip()
	if not version:
		return JsonResponse({'ok': False, 'error': 'version gerekli.'}, status=400)
	if not RobotAgentRelease.objects.filter(version=version).exists():
		return JsonResponse({'ok': False, 'error': 'Release bulunamadı.'}, status=404)
	agent_code = str(body.get('agent_code') or '').strip()
	if agent_code:
		agent = RobotAgent.objects.filter(code=agent_code).first()
		if not agent:
			return JsonResponse({'ok': False, 'error': 'Ajan bulunamadı.'}, status=404)
		agent.desired_version = version
		agent.save(update_fields=['desired_version', 'updated_at'])
		return JsonResponse({'ok': True, 'updated': 1, 'scope': 'single'})
	updated = RobotAgent.objects.update(desired_version=version, updated_at=timezone.now())
	return JsonResponse({'ok': True, 'updated': int(updated), 'scope': 'all'})


@require_POST
def robot_agent_upsert(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)
	code = str(body.get('code') or '').strip()
	name = str(body.get('name') or '').strip()
	if not code or not name:
		return JsonResponse({'ok': False, 'error': 'code ve name gerekli.'}, status=400)
	agent, created = RobotAgent.objects.get_or_create(
		code=code,
		defaults={
			'name': name,
			'token_hash': '',
			'is_enabled': True,
			'status': 'offline',
		},
	)
	agent.name = name[:180]
	agent.is_enabled = _as_bool(body.get('is_enabled', True), True)
	desired_version = str(body.get('desired_version') or '').strip()
	agent.desired_version = desired_version[:40] if desired_version else ''
	token = str(body.get('token') or '').strip()
	if token:
		agent.set_token(token)
	agent.save()

	if created:
		_create_agent_event(agent, 'info', 'Ajan panelden oluşturuldu.')
	elif token:
		_create_agent_event(agent, 'warning', 'Ajan token değeri panelden yenilendi.')

	return JsonResponse({'ok': True, 'created': created, 'code': agent.code})


@require_POST
def robot_agent_delete(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	code = str(body.get('code') or '').strip()
	if not code:
		return JsonResponse({'ok': False, 'error': 'code gerekli.'}, status=400)

	force = _as_bool(body.get('force', False), False)
	agent = RobotAgent.objects.filter(code=code).first()
	if not agent:
		return JsonResponse({'ok': False, 'error': 'Ajan bulunamadı.'}, status=404)

	active_jobs = RobotJob.objects.filter(target_agent=agent, status__in=['queued', 'dispatched', 'running']).count()
	if active_jobs > 0 and not force:
		return JsonResponse(
			{
				'ok': False,
				'error': f"Bu ajana bağlı {active_jobs} aktif iş var. Önce işleri temizleyin veya force=true ile tekrar deneyin.",
				'active_jobs': int(active_jobs),
			},
			status=409,
		)

	agent_id = agent.pk
	agent.delete()
	return JsonResponse({'ok': True, 'deleted': True, 'code': code, 'agent_id': agent_id})


@require_POST
def robot_cancel_job(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	job_id = body.get('job_id')
	if not job_id:
		return JsonResponse({'ok': False, 'error': 'job_id gerekli.'}, status=400)

	job = RobotJob.objects.filter(pk=job_id).first()
	if not job:
		return JsonResponse({'ok': False, 'error': 'İş bulunamadı.'}, status=404)

	if job.status in {'succeeded', 'failed', 'canceled'}:
		return JsonResponse({'ok': False, 'error': 'Tamamlanmış iş iptal edilemez.'}, status=400)

	job.status = 'canceled'
	job.finished_at = timezone.now()
	job.result_message = str(body.get('reason') or 'Kullanıcı tarafından iptal edildi.').strip()
	job.lease_expires_at = None
	job.save(update_fields=['status', 'finished_at', 'result_message', 'lease_expires_at', 'updated_at'])

	if job.target_agent_id:
		agent = job.target_agent
		active_count = RobotJob.objects.filter(target_agent=agent, status__in=['dispatched', 'running']).exclude(pk=job.pk).count()
		if active_count == 0:
			agent.status = 'online'
			agent.mark_seen(startup=False)
			agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

	return JsonResponse({'ok': True, 'job_id': job.pk, 'status': job.status})


@require_POST
def robot_dispatch_job(request):
	body = _read_json_body(request)
	if body is None:
		return JsonResponse({'ok': False, 'error': 'Geçersiz JSON.'}, status=400)

	command_type = str(body.get('command_type') or 'run_sap_process').strip()
	if command_type not in {'run_sap_process', 'run_command'}:
		return JsonResponse({'ok': False, 'error': 'Geçersiz command_type.'}, status=400)

	target_agent = None
	target_agent_code = str(body.get('target_agent_code') or '').strip()
	if target_agent_code:
		target_agent = RobotAgent.objects.filter(code=target_agent_code, is_enabled=True).first()
		if not target_agent:
			return JsonResponse({'ok': False, 'error': 'Hedef ajan bulunamadı veya pasif.'}, status=404)

	sap_process = None
	sap_process_id = body.get('sap_process_id')
	if command_type == 'run_sap_process':
		if not sap_process_id:
			return JsonResponse({'ok': False, 'error': 'run_sap_process için sap_process_id gerekli.'}, status=400)
		sap_process = SapProcess.objects.filter(pk=sap_process_id).first()
		if not sap_process:
			return JsonResponse({'ok': False, 'error': 'SAP süreç bulunamadı.'}, status=404)

	payload = body.get('payload') if isinstance(body.get('payload'), dict) else {}
	try:
		priority = int(body.get('priority', 100))
	except (TypeError, ValueError):
		priority = 100
	requested_by = str(body.get('requested_by') or '').strip()
	if not requested_by and getattr(request, 'user', None) and request.user.is_authenticated:
		requested_by = str(request.user.get_username() or '').strip()

	job = RobotJob.objects.create(
		command_type=command_type,
		sap_process=sap_process,
		target_agent=target_agent,
		payload=payload,
		priority=priority,
		status='queued',
		requested_by=requested_by[:120],
	)

	return JsonResponse({
		'ok': True,
		'job': {
			'job_id': job.pk,
			'status': job.status,
			'target_agent_code': target_agent.code if target_agent else '',
			'command_type': job.command_type,
			'sap_process_id': job.sap_process_id,
		}
	})
