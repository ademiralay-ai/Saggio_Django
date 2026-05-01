from __future__ import annotations

import json
from calendar import monthrange
from datetime import datetime, time, timedelta
from typing import Any

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ..models import PeriodicProcessSchedule, RobotAgent, RobotJob, SapProcess


def _json_body(request) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        body = json.loads(request.body.decode('utf-8'))
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _parse_weekdays(raw: str) -> list[int]:
    out: list[int] = []
    for part in str(raw or '').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
        except ValueError:
            continue
        if 0 <= v <= 6 and v not in out:
            out.append(v)
    return sorted(out)


def _compute_next_run(schedule: PeriodicProcessSchedule, base_dt: datetime | None = None) -> datetime | None:
    now = base_dt or timezone.localtime(timezone.now())

    def _as_time(value: Any, default: time) -> time:
        if isinstance(value, time):
            return value
        raw = str(value or '').strip()
        if not raw:
            return default
        try:
            hh, mm = raw.split(':', 1)
            return datetime.strptime(f"{int(hh):02d}:{int(mm):02d}", '%H:%M').time()
        except Exception:
            return default

    if schedule.frequency == 'interval':
        interval = max(1, int(schedule.interval_minutes or 0))
        anchor = schedule.last_run_at or now
        anchor = timezone.localtime(anchor) if timezone.is_aware(anchor) else anchor
        next_dt = anchor + timedelta(minutes=interval)
        while next_dt <= now:
            next_dt += timedelta(minutes=interval)
        return next_dt

    if schedule.frequency == 'daily':
        run_time = _as_time(schedule.run_time, now.time().replace(second=0, microsecond=0))
        candidate = now.replace(hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if schedule.frequency == 'weekly':
        run_time = _as_time(schedule.run_time, now.time().replace(second=0, microsecond=0))
        weekdays = _parse_weekdays(schedule.weekdays) or [now.weekday()]
        for i in range(0, 15):
            d = now + timedelta(days=i)
            if d.weekday() in weekdays:
                candidate = d.replace(hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)
                if candidate > now:
                    return candidate
        return None

    if schedule.frequency == 'monthly':
        run_time = _as_time(schedule.run_time, now.time().replace(second=0, microsecond=0))
        dom = int(schedule.day_of_month or now.day)
        dom = max(1, min(31, dom))

        year = now.year
        month = now.month
        for _ in range(0, 14):
            max_day = monthrange(year, month)[1]
            day = min(dom, max_day)
            candidate = now.replace(year=year, month=month, day=day, hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)
            if candidate > now:
                return candidate
            month += 1
            if month > 12:
                month = 1
                year += 1
        return None

    return None


def _serialize_schedule(s: PeriodicProcessSchedule) -> dict[str, Any]:
    return {
        'id': s.id,
        'name': s.name,
        'frequency': s.frequency,
        'interval_minutes': s.interval_minutes,
        'run_time': s.run_time.strftime('%H:%M') if s.run_time else '',
        'weekdays': s.weekdays,
        'day_of_month': s.day_of_month,
        'enabled': s.enabled,
        'priority': s.priority,
        'payload': s.payload or {},
        'maintenance_window_start': s.maintenance_window_start.strftime('%H:%M') if s.maintenance_window_start else '',
        'maintenance_window_end': s.maintenance_window_end.strftime('%H:%M') if s.maintenance_window_end else '',
        'prevent_overlap': bool(s.prevent_overlap),
        'overlap_buffer_minutes': int(s.overlap_buffer_minutes or 0),
        'note': s.note or '',
        'sap_process_id': s.sap_process_id,
        'sap_process_name': s.sap_process.name if s.sap_process_id else '',
        'target_agent_id': s.target_agent_id,
        'target_agent_code': s.target_agent.code if s.target_agent_id else '',
        'last_run_at': s.last_run_at.isoformat() if s.last_run_at else None,
        'next_run_at': s.next_run_at.isoformat() if s.next_run_at else None,
        'created_at': s.created_at.isoformat() if s.created_at else None,
    }


def _dispatch_schedule_job(schedule: PeriodicProcessSchedule, reason: str) -> RobotJob:
    payload = dict(schedule.payload or {})
    payload['scheduler'] = {
        'schedule_id': schedule.id,
        'schedule_name': schedule.name,
        'reason': reason,
    }
    return RobotJob.objects.create(
        command_type='run_sap_process',
        sap_process=schedule.sap_process,
        target_agent=schedule.target_agent,
        status='queued',
        priority=schedule.priority,
        payload=payload,
        requested_by='scheduler',
    )


def _is_in_maintenance_window(schedule: PeriodicProcessSchedule, now_local: datetime) -> bool:
    start = schedule.maintenance_window_start
    end = schedule.maintenance_window_end
    if not start or not end:
        return True

    now_t = now_local.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= now_t <= end
    # geceyi geçen pencere (örn 22:00-06:00)
    return now_t >= start or now_t <= end


def _has_active_overlap(schedule: PeriodicProcessSchedule, now: datetime) -> bool:
    if not schedule.prevent_overlap:
        return False

    active = RobotJob.objects.filter(status__in=['queued', 'dispatched', 'running'])
    active = active.filter(sap_process=schedule.sap_process)
    if schedule.target_agent_id:
        active = active.filter(target_agent=schedule.target_agent)

    if schedule.overlap_buffer_minutes and schedule.overlap_buffer_minutes > 0:
        threshold = now - timedelta(minutes=int(schedule.overlap_buffer_minutes))
        active = active.filter(created_at__gte=threshold)

    return active.exists()


def _validate_overlap_at_save(schedule: PeriodicProcessSchedule, candidate_next: datetime | None) -> None:
    if not schedule.prevent_overlap or not candidate_next:
        return

    buffer_minutes = max(0, int(schedule.overlap_buffer_minutes or 0))
    low = candidate_next - timedelta(minutes=buffer_minutes)
    high = candidate_next + timedelta(minutes=buffer_minutes)

    qs = PeriodicProcessSchedule.objects.filter(enabled=True, prevent_overlap=True, sap_process=schedule.sap_process)
    if schedule.target_agent_id:
        qs = qs.filter(target_agent=schedule.target_agent)
    else:
        qs = qs.filter(target_agent__isnull=True)

    if schedule.pk:
        qs = qs.exclude(pk=schedule.pk)

    for other in qs:
        if not other.next_run_at:
            continue
        if low <= other.next_run_at <= high:
            raise ValueError(
                f"Çakışma: '{other.name}' ile yakın zamanda tetikleniyor (±{buffer_minutes} dk)."
            )


def _upsert_from_body(body: dict[str, Any], username: str) -> PeriodicProcessSchedule:
    sid = body.get('id')
    name = str(body.get('name') or '').strip()
    sap_process_id = int(body.get('sap_process_id') or 0)
    frequency = str(body.get('frequency') or 'daily').strip().lower()

    if not name:
        raise ValueError('Plan adı zorunlu.')
    if not sap_process_id:
        raise ValueError('Süreç seçimi zorunlu.')
    if frequency not in {'interval', 'daily', 'weekly', 'monthly'}:
        raise ValueError('Geçersiz frekans.')

    process = SapProcess.objects.filter(pk=sap_process_id).first()
    if not process:
        raise ValueError('Süreç bulunamadı.')

    target_agent = None
    if body.get('target_agent_id'):
        target_agent = RobotAgent.objects.filter(pk=int(body.get('target_agent_id'))).first()

    sched = PeriodicProcessSchedule.objects.filter(pk=sid).first() if sid else PeriodicProcessSchedule()
    if not sched:
        raise ValueError('Plan kaydı bulunamadı.')

    sched.name = name
    sched.sap_process = process
    sched.target_agent = target_agent
    sched.frequency = frequency
    sched.interval_minutes = int(body.get('interval_minutes') or 0) or None

    rt = str(body.get('run_time') or '').strip()
    if rt:
        try:
            hh, mm = rt.split(':', 1)
            sched.run_time = datetime.strptime(f"{int(hh):02d}:{int(mm):02d}", '%H:%M').time()
        except Exception:
            raise ValueError('Saat formatı HH:MM olmalı.')
    else:
        sched.run_time = None

    sched.weekdays = str(body.get('weekdays') or '').strip()
    sched.day_of_month = int(body.get('day_of_month') or 0) or None
    sched.priority = int(body.get('priority') or 300)
    sched.note = str(body.get('note') or '').strip()
    sched.payload = body.get('payload') if isinstance(body.get('payload'), dict) else {}
    sched.prevent_overlap = bool(body.get('prevent_overlap', True))
    sched.overlap_buffer_minutes = max(0, int(body.get('overlap_buffer_minutes') or 10))
    sched.enabled = bool(body.get('enabled', True))

    ws = str(body.get('maintenance_window_start') or '').strip()
    we = str(body.get('maintenance_window_end') or '').strip()
    if ws and we:
        try:
            sh, sm = ws.split(':', 1)
            eh, em = we.split(':', 1)
            sched.maintenance_window_start = datetime.strptime(f"{int(sh):02d}:{int(sm):02d}", '%H:%M').time()
            sched.maintenance_window_end = datetime.strptime(f"{int(eh):02d}:{int(em):02d}", '%H:%M').time()
        except Exception:
            raise ValueError('Bakım penceresi saat formatı HH:MM olmalı.')
    elif ws or we:
        raise ValueError('Bakım penceresi için başlangıç ve bitiş birlikte girilmeli.')
    else:
        sched.maintenance_window_start = None
        sched.maintenance_window_end = None

    if not sched.created_by:
        sched.created_by = username or 'admin'

    if sched.frequency == 'interval' and not sched.interval_minutes:
        raise ValueError('Interval için dakika değeri zorunlu.')
    if sched.frequency in {'daily', 'weekly', 'monthly'} and not sched.run_time:
        raise ValueError('Bu frekans için saat seçimi zorunlu.')
    if sched.frequency == 'weekly' and not _parse_weekdays(sched.weekdays):
        raise ValueError('Haftalık plan için en az bir gün seçmelisiniz.')
    if sched.frequency == 'monthly' and not sched.day_of_month:
        raise ValueError('Aylık plan için ayın günü gerekli.')

    now = timezone.localtime(timezone.now())
    sched.next_run_at = _compute_next_run(sched, now) if sched.enabled else None
    _validate_overlap_at_save(sched, sched.next_run_at)
    sched.save()
    return sched


def dispatch_due_schedules(now: datetime | None = None, reason: str = 'due-run') -> list[dict[str, int]]:
    now = now or timezone.now()
    due = PeriodicProcessSchedule.objects.select_related('sap_process', 'target_agent').filter(
        enabled=True,
        next_run_at__isnull=False,
        next_run_at__lte=now,
    ).order_by('next_run_at')

    dispatched: list[dict[str, int]] = []
    now_local = timezone.localtime(now)
    for sched in due:
        if not _is_in_maintenance_window(sched, now_local):
            sched.next_run_at = _compute_next_run(sched, now_local)
            sched.save(update_fields=['next_run_at', 'updated_at'])
            continue

        if _has_active_overlap(sched, now):
            sched.next_run_at = _compute_next_run(sched, now_local + timedelta(minutes=1))
            sched.save(update_fields=['next_run_at', 'updated_at'])
            continue

        job = _dispatch_schedule_job(sched, reason)
        sched.last_run_at = now
        sched.next_run_at = _compute_next_run(sched, now_local)
        sched.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])
        dispatched.append({'schedule_id': sched.id, 'job_id': job.pk})

    return dispatched


@require_GET
def scheduler_list(request):
    rows = list(PeriodicProcessSchedule.objects.select_related('sap_process', 'target_agent').all())
    total = len(rows)
    active = sum(1 for x in rows if x.enabled)
    due_now = sum(1 for x in rows if x.enabled and x.next_run_at and x.next_run_at <= timezone.now())

    recent_jobs_qs = RobotJob.objects.select_related('sap_process', 'target_agent').filter(
        requested_by='scheduler'
    ).order_by('-created_at')[:20]
    recent_jobs = [
        {
            'job_id': j.pk,
            'schedule_id': (j.payload or {}).get('scheduler', {}).get('schedule_id'),
            'schedule_name': (j.payload or {}).get('scheduler', {}).get('schedule_name', ''),
            'status': j.status,
            'sap_process_name': j.sap_process.name if j.sap_process_id else '-',
            'target_agent_code': j.target_agent.code if j.target_agent_id else 'any',
            'created_at': j.created_at.isoformat() if j.created_at else None,
            'finished_at': j.finished_at.isoformat() if j.finished_at else None,
            'message': j.result_message or '',
        }
        for j in recent_jobs_qs
    ]

    offline_threshold = timezone.now() - timedelta(seconds=30)
    online_agent_ids = set(
        RobotAgent.objects.filter(is_enabled=True, last_seen_at__gte=offline_threshold).values_list('pk', flat=True)
    )
    any_agent_online = bool(online_agent_ids)

    return JsonResponse({
        'ok': True,
        'items': [_serialize_schedule(x) for x in rows],
        'stats': {
            'total': total,
            'active': active,
            'due_now': due_now,
        },
        'recent_jobs': recent_jobs,
        'agent_status': {
            'any_online': any_agent_online,
            'online_ids': list(online_agent_ids),
        },
    })


@require_POST
def scheduler_save(request):
    body = _json_body(request)
    try:
        sched = _upsert_from_body(body, getattr(request.user, 'username', '') or 'admin')
        return JsonResponse({'ok': True, 'item': _serialize_schedule(sched)})
    except Exception as ex:
        return JsonResponse({'ok': False, 'error': str(ex)}, status=400)


@require_POST
def scheduler_toggle(request):
    body = _json_body(request)
    sid = int(body.get('id') or 0)
    if not sid:
        return JsonResponse({'ok': False, 'error': 'id zorunlu'}, status=400)
    sched = PeriodicProcessSchedule.objects.filter(pk=sid).first()
    if not sched:
        return JsonResponse({'ok': False, 'error': 'Kayıt bulunamadı'}, status=404)

    sched.enabled = bool(body.get('enabled', not sched.enabled))
    sched.next_run_at = _compute_next_run(sched, timezone.localtime(timezone.now())) if sched.enabled else None
    sched.save(update_fields=['enabled', 'next_run_at', 'updated_at'])
    return JsonResponse({'ok': True, 'item': _serialize_schedule(sched)})


@require_POST
def scheduler_delete(request):
    body = _json_body(request)
    sid = int(body.get('id') or 0)
    if not sid:
        return JsonResponse({'ok': False, 'error': 'id zorunlu'}, status=400)
    deleted, _ = PeriodicProcessSchedule.objects.filter(pk=sid).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@require_POST
def scheduler_run_now(request):
    body = _json_body(request)
    sid = int(body.get('id') or 0)
    if not sid:
        return JsonResponse({'ok': False, 'error': 'id zorunlu'}, status=400)
    sched = PeriodicProcessSchedule.objects.select_related('sap_process', 'target_agent').filter(pk=sid).first()
    if not sched:
        return JsonResponse({'ok': False, 'error': 'Kayıt bulunamadı'}, status=404)

    if not _is_in_maintenance_window(sched, timezone.localtime(timezone.now())):
        return JsonResponse({'ok': False, 'error': 'Plan bakım penceresi dışında.'}, status=400)
    if _has_active_overlap(sched, timezone.now()):
        return JsonResponse({'ok': False, 'error': 'Aynı süreç için aktif iş varken tetikleme engellendi.'}, status=400)

    # Agent online kontrolü — son 30 saniyede heartbeat atmamış mı?
    offline_threshold = timezone.now() - timedelta(seconds=30)
    if sched.target_agent_id:
        agent_online = RobotAgent.objects.filter(
            pk=sched.target_agent_id, is_enabled=True, last_seen_at__gte=offline_threshold
        ).exists()
    else:
        agent_online = RobotAgent.objects.filter(
            is_enabled=True, last_seen_at__gte=offline_threshold
        ).exists()

    if not agent_online:
        # Yine de kuyruğa al ama uyarıyla dön
        job = _dispatch_schedule_job(sched, 'manual-run')
        now = timezone.now()
        sched.last_run_at = now
        sched.next_run_at = _compute_next_run(sched, timezone.localtime(now)) if sched.enabled else None
        sched.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])
        return JsonResponse({
            'ok': True,
            'job_id': job.pk,
            'warning': 'agent_offline',
            'warning_msg': 'Robot agent şu an çevrimdışı. İş kuyruğa alındı, agent tekrar bağlandığında çalışacak.',
            'item': _serialize_schedule(sched),
        })

    job = _dispatch_schedule_job(sched, 'manual-run')
    now = timezone.now()
    sched.last_run_at = now
    sched.next_run_at = _compute_next_run(sched, timezone.localtime(now)) if sched.enabled else None
    sched.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])

    return JsonResponse({'ok': True, 'job_id': job.pk, 'item': _serialize_schedule(sched)})


@require_POST
def scheduler_dispatch_due(request):
    dispatched = dispatch_due_schedules(timezone.now(), reason='due-run')
    return JsonResponse({'ok': True, 'count': len(dispatched), 'items': dispatched})
