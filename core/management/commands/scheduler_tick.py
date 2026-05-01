from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...api.scheduler_api import dispatch_due_schedules


class Command(BaseCommand):
    help = 'Periyodik scheduler planlarini kontrol eder ve vakti gelenleri kuyruga dispatch eder.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Tek sefer kontrol et ve cik')
        parser.add_argument('--interval-seconds', type=int, default=60, help='Loop modunda kontrol araligi (sn)')

    def handle(self, *args, **options):
        once = bool(options.get('once'))
        interval_seconds = max(5, int(options.get('interval_seconds') or 60))

        def run_once():
            now = timezone.now()
            items = dispatch_due_schedules(now, reason='tick-run')
            self.stdout.write(self.style.SUCCESS(f"[{timezone.localtime(now)}] dispatched={len(items)}"))

        if once:
            run_once()
            return

        self.stdout.write(self.style.WARNING(f'Scheduler tick loop basladi. interval={interval_seconds}s'))
        while True:
            run_once()
            time.sleep(interval_seconds)
