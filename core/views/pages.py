"""Static / dashboard / section page renderers (HTML).

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..firebase_service import (
	ProcessService,
	QueueService,
	ReportService,
	RobotService,
	ScheduleService,
)
from ..models import RobotAgent, RobotAgentRelease, SapProcess


ALLOWED_HELP_MEDIA_EXTENSIONS = {'.gif', '.mp4', '.png', '.jpg', '.jpeg', '.webp'}


def get_dashboard_stats():
	"""Fetch dashboard statistics from Firebase"""
	robots = RobotService.get_all_robots() or {}
	processes = ProcessService.get_all_processes() or {}
	
	total_robots = len(robots)
	online_robots = sum(1 for r in robots.values() if isinstance(r, dict) and r.get('status') == 'online')
	total_processes = len(processes)
	
	return {
		'total_robots': total_robots or 5,
		'online_robots': online_robots or 5,
		'total_processes': total_processes or 12,
		'success_rate': '98.2%',
	}


def dashboard(request):
	stats = get_dashboard_stats()
	robots_data = RobotService.get_all_robots() or {}
	processes_data = ProcessService.get_all_processes() or {}
	
	return render(
		request,
		'core/dashboard.html',
		{
			'page_title': 'Dashboard',
			'page_subtitle': 'Robot operasyon merkezi',
			'stats': stats,
			'robots': robots_data,
			'processes': processes_data,
		},
	)


def help_center(request):
	return render(
		request,
		'core/help_center.html',
		{
			'page_title': 'Yardim Merkezi',
			'page_subtitle': 'Sifirdan basla: ekranlar, surecler, robot ajani ve teknik detaylar',
		},
	)


@staff_member_required
@require_POST
def help_media_upload(request):
	files = request.FILES.getlist('media_files')
	if not files:
		return JsonResponse({'ok': False, 'error': 'Yuklenecek dosya bulunamadi.'}, status=400)

	base_dir = Path(__file__).resolve().parent.parent
	upload_dir = base_dir / 'static' / 'core' / 'help_media'
	upload_dir.mkdir(parents=True, exist_ok=True)

	uploaded = []
	rejected = []

	for f in files:
		name = Path(f.name).name
		ext = Path(name).suffix.lower()
		if ext not in ALLOWED_HELP_MEDIA_EXTENSIONS:
			rejected.append({'name': name, 'reason': 'Desteklenmeyen uzanti'})
			continue

		target = upload_dir / name
		with target.open('wb+') as dest:
			for chunk in f.chunks():
				dest.write(chunk)
		uploaded.append(name)

	if not uploaded:
		return JsonResponse({'ok': False, 'error': 'Gecerli dosya yuklenemedi.', 'rejected': rejected}, status=400)

	return JsonResponse({'ok': True, 'uploaded': uploaded, 'rejected': rejected})


def robots(request):
	robots_data = RobotService.get_all_robots() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Robotlar',
			'page_subtitle': 'Robot envanteri ve canli durum takibi',
			'section_type': 'robots',
			'data': robots_data,
		},
	)


def processes(request):
	processes_data = ProcessService.get_all_processes() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Surecler',
			'page_subtitle': 'Süreç performansı ve hata analizi',
			'section_type': 'processes',
			'data': processes_data,
		},
	)


def queues(request):
	queues_data = QueueService.get_all_queues() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Kuyruk Yonetimi',
			'page_subtitle': 'Is kuyruklari, onceliklendirme ve SLA takibi',
			'section_type': 'queues',
			'data': queues_data,
		},
	)


def scheduler(request):
	agents = list(RobotAgent.objects.all().order_by('code').values('id', 'code', 'name'))
	processes = list(SapProcess.objects.all().order_by('name').values('id', 'name'))

	return render(
		request,
		'core/scheduler.html',
		{
			'page_title': 'Scheduler',
			'page_subtitle': 'Periyodik süreçleri planla, izle ve tek tık tetikle',
			'agents_json': json.dumps(agents, ensure_ascii=False),
			'processes_json': json.dumps(processes, ensure_ascii=False),
		},
	)


def reports(request):
	reports_data = ReportService.get_all_reports() or {}
	
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Raporlar',
			'page_subtitle': 'Operasyon raporlari ve KPI ozetleri',
			'section_type': 'reports',
			'data': reports_data,
		},
	)


def settings_page(request):
	return render(
		request,
		'core/section.html',
		{
			'page_title': 'Ayarlar',
			'page_subtitle': 'Sistem konfigrasyonlari ve entegrasyonlar',
			'section_type': 'settings',
		},
	)


def robot_control_center(request):
	"""Robot ajanları ve iş kuyruğunu yönetmek için operasyon ekranı."""
	agents = list(RobotAgent.objects.all().order_by('code').values('code', 'name'))
	processes = list(SapProcess.objects.all().order_by('name').values('id', 'name'))
	releases = list(
		RobotAgentRelease.objects.all().order_by('-created_at').values(
			'version', 'is_active', 'is_mandatory', 'download_url', 'setup_file', 'install_command', 'created_at'
		)
	)
	return render(
		request,
		'core/robot_control_center.html',
		{
			'current': 'robot_control_center',
			'page_title': 'Robot Operasyon Merkezi',
			'page_subtitle': 'Ajan durumlarını izle, kuyruk işlerini yönet ve yeni iş ata',
			'agents_json': json.dumps(agents, ensure_ascii=False),
			'processes_json': json.dumps(processes, ensure_ascii=False),
			'releases_json': json.dumps(releases, ensure_ascii=False, default=str),
		},
	)
