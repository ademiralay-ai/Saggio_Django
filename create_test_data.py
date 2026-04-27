"""
Create demo data for Django models (SQLite)
"""
import os
import sys
import django
from datetime import datetime, time

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, 'c:\\Util\\SaggioDjango')
django.setup()

from core.models import Robot, Process, Queue, Report, Schedule


def create_demo_data():
	print("🚀 Creating demo data for admin panel...\n")
	
	# Clear existing data
	Robot.objects.all().delete()
	Process.objects.all().delete()
	Queue.objects.all().delete()
	Report.objects.all().delete()
	Schedule.objects.all().delete()
	
	# Create Robots
	print("🤖 Creating robots...")
	robots_data = [
		{
			'robot_id': 'RPA-001-TR',
			'name': 'Fatura İşleme Bot',
			'status': 'online',
			'last_run': datetime.now(),
			'total_runs': 1542,
			'success_count': 1520,
			'error_count': 22,
			'version': '2.1.0'
		},
		{
			'robot_id': 'RPA-002-TR',
			'name': 'Muhasebe Entegrasyonu',
			'status': 'online',
			'last_run': datetime.now(),
			'total_runs': 892,
			'success_count': 875,
			'error_count': 17,
			'version': '1.8.5'
		},
		{
			'robot_id': 'RPA-003-TR',
			'name': 'Raporlama Sistemi',
			'status': 'offline',
			'total_runs': 456,
			'success_count': 450,
			'error_count': 6,
			'version': '1.5.2'
		},
	]
	
	for data in robots_data:
		robot = Robot.objects.create(**data)
		print(f"  ✓ Created: {robot.name}")
	
	# Create Processes
	print("\n⚙️ Creating processes...")
	processes_data = [
		{
			'process_id': 'P001',
			'name': 'Fatura Taraması',
			'status': 'running',
			'progress': 75,
			'total_items': 500,
			'processed': 375,
			'error_rate': '2.3%',
			'robot': 'RPA-001-TR'
		},
		{
			'process_id': 'P002',
			'name': 'Muhasebe Sınıflandırması',
			'status': 'completed',
			'progress': 100,
			'total_items': 250,
			'processed': 250,
			'error_rate': '0.8%',
			'robot': 'RPA-002-TR'
		},
		{
			'process_id': 'P003',
			'name': 'Yönetici Raporu Oluşturma',
			'status': 'pending',
			'progress': 0,
			'total_items': 100,
			'processed': 0,
			'error_rate': '0%',
			'robot': 'RPA-003-TR'
		},
		{
			'process_id': 'P004',
			'name': 'Vergi Hesaplaması',
			'status': 'running',
			'progress': 45,
			'total_items': 1200,
			'processed': 540,
			'error_rate': '1.5%',
			'robot': 'RPA-002-TR'
		},
	]
	
	for data in processes_data:
		process = Process.objects.create(**data)
		print(f"  ✓ Created: {process.name}")
	
	# Create Queue Items
	print("\n📋 Creating queue items...")
	queue_items = [
		{
			'queue_id': 'Q001',
			'queue_name': 'fatura_processing',
			'item_name': 'FATURA-2024-001',
			'priority': 'high',
			'status': 'processing'
		},
		{
			'queue_id': 'Q002',
			'queue_name': 'fatura_processing',
			'item_name': 'FATURA-2024-002',
			'priority': 'normal',
			'status': 'pending'
		},
		{
			'queue_id': 'Q003',
			'queue_name': 'fatura_processing',
			'item_name': 'FATURA-2024-003',
			'priority': 'low',
			'status': 'pending'
		},
		{
			'queue_id': 'Q004',
			'queue_name': 'muhasebe_queue',
			'item_name': 'MUH-2024-156',
			'priority': 'urgent',
			'status': 'pending'
		},
	]
	
	for data in queue_items:
		queue = Queue.objects.create(**data)
		print(f"  ✓ Created: {queue.item_name}")
	
	# Create Reports
	print("\n📊 Creating reports...")
	reports_data = [
		{
			'report_id': 'RPT-001',
			'title': 'Aylık Operasyon Raporu',
			'report_type': 'monthly',
			'description': 'Ocak 2024 periyodu için operasyon özeti',
			'content': {'month': 'January 2024', 'total_processes': 45, 'success_rate': 98.5}
		},
		{
			'report_id': 'RPT-002',
			'title': 'Robot Performans Analizi',
			'report_type': 'performance',
			'description': 'Son 7 gün için robot performans istatistikleri',
			'content': {'period': 'Last 7 days', 'cpu_usage': '45%', 'memory_usage': '62%', 'uptime': '99.8%'}
		},
		{
			'report_id': 'RPT-003',
			'title': 'Haftalık Özeti',
			'report_type': 'weekly',
			'description': 'Haftanın özeti raporu',
			'content': {'week': 'Week 15', 'total_processes': 12, 'completed': 11, 'failed': 1}
		},
	]
	
	for data in reports_data:
		report = Report.objects.create(**data)
		print(f"  ✓ Created: {report.title}")
	
	# Create Schedules
	print("\n⏰ Creating schedules...")
	schedules_data = [
		{
			'schedule_id': 'SCH-001',
			'name': 'Günlük Fatura İşleme',
			'robot': 'RPA-001-TR',
			'frequency': 'daily',
			'time': time(9, 0),
			'enabled': True
		},
		{
			'schedule_id': 'SCH-002',
			'name': 'Haftalık Muhasebe Kapanışı',
			'robot': 'RPA-002-TR',
			'frequency': 'weekly',
			'day': 'Cuma',
			'time': time(17, 0),
			'enabled': True
		},
		{
			'schedule_id': 'SCH-003',
			'name': 'Aylık Denetim Raporu',
			'robot': 'RPA-003-TR',
			'frequency': 'monthly',
			'day': 'Ayın Son Günü',
			'time': time(18, 30),
			'enabled': True
		},
		{
			'schedule_id': 'SCH-004',
			'name': 'Saatlik İstatistik Güncellemesi',
			'robot': 'RPA-001-TR',
			'frequency': 'hourly',
			'time': time(0, 0),
			'enabled': False
		},
	]
	
	for data in schedules_data:
		schedule = Schedule.objects.create(**data)
		print(f"  ✓ Created: {schedule.name}")
	
	print("\n✅ Demo data created successfully!\n")
	print("📊 Summary:")
	print(f"   - Robots: {Robot.objects.count()}")
	print(f"   - Processes: {Process.objects.count()}")
	print(f"   - Queue Items: {Queue.objects.count()}")
	print(f"   - Reports: {Report.objects.count()}")
	print(f"   - Schedules: {Schedule.objects.count()}")
	print(f"\n🔗 Admin URL: http://127.0.0.1:8000/admin/")
	print(f"📝 Login: superadmin / Saggio@12345")


if __name__ == '__main__':
	create_demo_data()
