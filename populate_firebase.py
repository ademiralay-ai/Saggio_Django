"""
Test script to populate Firebase with demo data for RPA dashboard
"""
import os
import sys
import django
from datetime import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, 'c:\\Util\\SaggioDjango')
django.setup()

from core.firebase_service import RobotService, ProcessService, QueueService, ReportService, ScheduleService

def populate_demo_data():
    print("🚀 Populating Firebase with demo data...")
    
    # Demo Robots
    robots_data = {
        'RPA-001-TR': {
            'name': 'Fatura İşleme Bot',
            'status': 'online',
            'last_run': datetime.now().isoformat(),
            'total_runs': 1542,
            'success_count': 1520,
            'error_count': 22,
            'version': '2.1.0'
        },
        'RPA-002-TR': {
            'name': 'Muhasebe Entegrasyonu',
            'status': 'online',
            'last_run': datetime.now().isoformat(),
            'total_runs': 892,
            'success_count': 875,
            'error_count': 17,
            'version': '1.8.5'
        },
        'RPA-003-TR': {
            'name': 'Raporlama Sistemi',
            'status': 'offline',
            'last_run': '2024-01-15T14:30:00',
            'total_runs': 456,
            'success_count': 450,
            'error_count': 6,
            'version': '1.5.2'
        }
    }
    
    for robot_id, data in robots_data.items():
        RobotService.create_robot(robot_id, data)
        print(f"  ✓ Created robot: {robot_id}")
    
    # Demo Processes
    processes_data = {
        'P001': {
            'name': 'Fatura Taraması',
            'status': 'running',
            'progress': 75,
            'total_items': 500,
            'processed': 375,
            'error_rate': '2.3%',
            'robot': 'RPA-001-TR'
        },
        'P002': {
            'name': 'Muhasebe Sınıflandırması',
            'status': 'completed',
            'progress': 100,
            'total_items': 250,
            'processed': 250,
            'error_rate': '0.8%',
            'robot': 'RPA-002-TR'
        },
        'P003': {
            'name': 'Yönetici Raporu Oluşturma',
            'status': 'pending',
            'progress': 0,
            'total_items': 100,
            'processed': 0,
            'error_rate': '0%',
            'robot': 'RPA-003-TR'
        }
    }
    
    for process_id, data in processes_data.items():
        ProcessService.create_process(process_id, data)
        print(f"  ✓ Created process: {process_id}")
    
    # Demo Queues
    queue_items = [
        {'name': 'FATURA-2024-001', 'priority': 'high', 'created_at': datetime.now().isoformat()},
        {'name': 'FATURA-2024-002', 'priority': 'normal', 'created_at': datetime.now().isoformat()},
        {'name': 'FATURA-2024-003', 'priority': 'low', 'created_at': datetime.now().isoformat()},
    ]
    
    for item in queue_items:
        QueueService.add_to_queue('fatura_processing', item)
        print(f"  ✓ Added to queue: {item['name']}")
    
    # Demo Reports
    reports_data = {
        'RPT-001': {
            'title': 'Aylık Operasyon Raporu',
            'month': 'January 2024',
            'total_processes': 45,
            'success_rate': '98.5%',
            'average_runtime': '2h 15m'
        },
        'RPT-002': {
            'title': 'Robot Performans Analizi',
            'period': 'Last 7 days',
            'cpu_usage': '45%',
            'memory_usage': '62%',
            'uptime': '99.8%'
        }
    }
    
    for report_id, data in reports_data.items():
        ReportService.create_report(report_id, data)
        print(f"  ✓ Created report: {report_id}")
    
    # Demo Schedules
    schedules_data = {
        'SCH-001': {
            'name': 'Günlük Fatura İşleme',
            'frequency': 'daily',
            'time': '09:00',
            'robot': 'RPA-001-TR'
        },
        'SCH-002': {
            'name': 'Haftalık Muhasebe Kapanışı',
            'frequency': 'weekly',
            'day': 'Friday',
            'time': '17:00',
            'robot': 'RPA-002-TR'
        }
    }
    
    for schedule_id, data in schedules_data.items():
        ScheduleService.create_schedule(schedule_id, data)
        print(f"  ✓ Created schedule: {schedule_id}")
    
    print("\n✅ Demo data successfully populated to Firebase!")

if __name__ == '__main__':
    populate_demo_data()
