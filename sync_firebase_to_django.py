"""
Sync Firebase data to Django models for admin panel visibility
"""
import os
import sys
import django
from datetime import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, 'c:\\Util\\SaggioDjango')
django.setup()

from core.firebase_service import (
	RobotService, ProcessService, QueueService, 
	ReportService, ScheduleService
)
from core.models import Robot, Process, Queue, Report, Schedule


def sync_robots():
	"""Sync robots from Firebase to Django models"""
	print("🤖 Syncing robots...")
	firebase_robots = RobotService.get_all_robots() or {}
	
	for robot_id, data in firebase_robots.items():
		if isinstance(data, dict):
			obj, created = Robot.objects.update_or_create(
				robot_id=robot_id,
				defaults={
					'name': data.get('name', 'Unknown'),
					'status': data.get('status', 'offline'),
					'last_run': data.get('last_run'),
					'total_runs': data.get('total_runs', 0),
					'success_count': data.get('success_count', 0),
					'error_count': data.get('error_count', 0),
					'version': data.get('version', '1.0.0'),
				}
			)
			action = "✓ Created" if created else "✓ Updated"
			print(f"  {action}: {robot_id}")
	
	print(f"  Total robots synced: {Robot.objects.count()}\n")


def sync_processes():
	"""Sync processes from Firebase to Django models"""
	print("⚙️ Syncing processes...")
	firebase_processes = ProcessService.get_all_processes() or {}
	
	for process_id, data in firebase_processes.items():
		if isinstance(data, dict):
			obj, created = Process.objects.update_or_create(
				process_id=process_id,
				defaults={
					'name': data.get('name', 'Unknown'),
					'status': data.get('status', 'pending'),
					'progress': data.get('progress', 0),
					'total_items': data.get('total_items', 0),
					'processed': data.get('processed', 0),
					'error_rate': data.get('error_rate', '0%'),
					'robot': data.get('robot'),
				}
			)
			action = "✓ Created" if created else "✓ Updated"
			print(f"  {action}: {process_id}")
	
	print(f"  Total processes synced: {Process.objects.count()}\n")


def sync_queues():
	"""Sync queue items from Firebase to Django models"""
	print("📋 Syncing queue items...")
	firebase_queues = QueueService.get_all_queues() or {}
	
	counter = 0
	for queue_name, items in firebase_queues.items():
		if isinstance(items, dict):
			for item_key, item_data in items.items():
				if isinstance(item_data, dict):
					queue_id = f"{queue_name}_{item_key}"
					obj, created = Queue.objects.update_or_create(
						queue_id=queue_id,
						defaults={
							'queue_name': queue_name,
							'item_name': item_data.get('name', item_data.get('data', {}).get('name', 'Unknown')),
							'priority': item_data.get('priority', 'normal'),
							'status': item_data.get('status', 'pending'),
						}
					)
					counter += 1
	
	print(f"  Total queue items synced: {Queue.objects.count()}\n")


def sync_reports():
	"""Sync reports from Firebase to Django models"""
	print("📊 Syncing reports...")
	firebase_reports = ReportService.get_all_reports() or {}
	
	for report_id, data in firebase_reports.items():
		if isinstance(data, dict):
			obj, created = Report.objects.update_or_create(
				report_id=report_id,
				defaults={
					'title': data.get('title', 'Unknown'),
					'description': data.get('description', ''),
					'report_type': data.get('report_type', 'monthly'),
					'content': data.get('content'),
				}
			)
			action = "✓ Created" if created else "✓ Updated"
			print(f"  {action}: {report_id}")
	
	print(f"  Total reports synced: {Report.objects.count()}\n")


def sync_schedules():
	"""Sync schedules from Firebase to Django models"""
	print("⏰ Syncing schedules...")
	firebase_schedules = ScheduleService.get_all_schedules() or {}
	
	for schedule_id, data in firebase_schedules.items():
		if isinstance(data, dict):
			try:
				from datetime import time
				time_obj = time.fromisoformat(data.get('time', '09:00')) if data.get('time') else None
			except:
				time_obj = None
			
			obj, created = Schedule.objects.update_or_create(
				schedule_id=schedule_id,
				defaults={
					'name': data.get('name', 'Unknown'),
					'robot': data.get('robot', ''),
					'frequency': data.get('frequency', 'daily'),
					'time': time_obj,
					'day': data.get('day'),
					'enabled': data.get('enabled', True),
				}
			)
			action = "✓ Created" if created else "✓ Updated"
			print(f"  {action}: {schedule_id}")
	
	print(f"  Total schedules synced: {Schedule.objects.count()}\n")


def main():
	print("🔄 Starting Firebase to Django sync...\n")
	
	try:
		sync_robots()
		sync_processes()
		sync_queues()
		sync_reports()
		sync_schedules()
		
		print("✅ Sync completed successfully!")
		print(f"\nSummary:")
		print(f"  - Robots: {Robot.objects.count()}")
		print(f"  - Processes: {Process.objects.count()}")
		print(f"  - Queue Items: {Queue.objects.count()}")
		print(f"  - Reports: {Report.objects.count()}")
		print(f"  - Schedules: {Schedule.objects.count()}")
		
	except Exception as e:
		print(f"❌ Sync error: {e}")
		import traceback
		traceback.print_exc()


if __name__ == '__main__':
	main()
