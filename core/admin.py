from django.contrib import admin
from django.utils.html import format_html
from .models import MailAccount, Process, Queue, Report, Robot, RobotAgent, RobotAgentEvent, RobotAgentRelease, RobotJob, Schedule, TelegramBot, TelegramGroup


@admin.register(Robot)
class RobotAdmin(admin.ModelAdmin):
	list_display = ('robot_id', 'name', 'status_badge', 'total_runs', 'success_rate', 'version')
	list_filter = ('status', 'created_at')
	search_fields = ('name', 'robot_id')
	readonly_fields = ('created_at', 'updated_at')
	
	fieldsets = (
		('Temel Bilgiler', {
			'fields': ('robot_id', 'name', 'version', 'status')
		}),
		('İstatistikler', {
			'fields': ('total_runs', 'success_count', 'error_count', 'last_run')
		}),
		('Zaman Damgaları', {
			'fields': ('created_at', 'updated_at'),
			'classes': ('collapse',)
		}),
	)
	
	def status_badge(self, obj):
		colors = {
			'online': '#00f3ff',      # Neon cyan
			'offline': '#ff003c',      # Neon red
			'maintenance': '#ffaa00'   # Neon amber
		}
		color = colors.get(obj.status, '#ffffff')
		return format_html(
			'<span style="color: {}; font-weight: bold;">●</span> {}',
			color,
			obj.get_status_display() if hasattr(obj, 'get_status_display') else obj.status
		)
	status_badge.short_description = 'Durum'
	
	def success_rate(self, obj):
		if obj.total_runs == 0:
			return '—'
		rate = (obj.success_count / obj.total_runs) * 100
		return f'{rate:.1f}%'
	success_rate.short_description = 'Başarı Oranı'


@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
	list_display = ('process_id', 'name', 'status_colored', 'progress_bar', 'processed', 'total_items')
	list_filter = ('status', 'created_at')
	search_fields = ('name', 'process_id', 'robot')
	readonly_fields = ('created_at', 'updated_at', 'progress_display')
	
	fieldsets = (
		('Temel Bilgiler', {
			'fields': ('process_id', 'name', 'status', 'robot')
		}),
		('İlerleme', {
			'fields': ('progress_display', 'processed', 'total_items', 'error_rate')
		}),
		('Zaman Damgaları', {
			'fields': ('created_at', 'updated_at'),
			'classes': ('collapse',)
		}),
	)
	
	def status_colored(self, obj):
		colors = {
			'running': '#00f3ff',
			'completed': '#39ff14',
			'failed': '#ff003c',
			'pending': '#ffaa00',
			'paused': '#9d00ff'
		}
		color = colors.get(obj.status, '#ffffff')
		return format_html(
			'<span style="color: {}; font-weight: bold;">●</span> {}',
			color,
			obj.get_status_display()
		)
	status_colored.short_description = 'Durum'
	
	def progress_bar(self, obj):
		return format_html(
			'<div style="width: 100px; height: 20px; background: #1a1b20; border: 1px solid #00f3ff; border-radius: 3px; overflow: hidden;">'
			'<div style="width: {}%; height: 100%; background: linear-gradient(90deg, #00f3ff, #39ff14);"></div>'
			'</div> {}%',
			obj.progress, obj.progress
		)
	progress_bar.short_description = 'İlerleme'
	
	def progress_display(self, obj):
		return f'{obj.progress}%'
	progress_display.short_description = 'İlerleme Yüzdesi'


@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
	list_display = ('item_name', 'queue_name', 'priority_badge', 'status', 'created_at')
	list_filter = ('priority', 'status', 'queue_name', 'created_at')
	search_fields = ('item_name', 'queue_name')
	readonly_fields = ('created_at', 'updated_at')
	
	fieldsets = (
		('Kuyruk Bilgisi', {
			'fields': ('queue_id', 'queue_name', 'item_name', 'priority', 'status')
		}),
		('Zaman Damgaları', {
			'fields': ('created_at', 'updated_at'),
			'classes': ('collapse',)
		}),
	)
	
	def priority_badge(self, obj):
		colors = {
			'urgent': '#ff003c',
			'high': '#ffaa00',
			'normal': '#00f3ff',
			'low': '#9d00ff'
		}
		color = colors.get(obj.priority, '#ffffff')
		return format_html(
			'<span style="color: {}; font-weight: bold;">■</span> {}',
			color,
			obj.get_priority_display()
		)
	priority_badge.short_description = 'Öncelik'


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
	list_display = ('title', 'report_type_display', 'created_at')
	list_filter = ('report_type', 'created_at')
	search_fields = ('title', 'description')
	readonly_fields = ('created_at', 'updated_at')
	
	fieldsets = (
		('Rapor Bilgisi', {
			'fields': ('report_id', 'title', 'report_type', 'description')
		}),
		('İçerik', {
			'fields': ('content',),
			'classes': ('collapse',)
		}),
		('Zaman Damgaları', {
			'fields': ('created_at', 'updated_at'),
			'classes': ('collapse',)
		}),
	)
	
	def report_type_display(self, obj):
		return obj.get_report_type_display()
	report_type_display.short_description = 'Rapor Türü'


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
	list_display = ('name', 'robot', 'frequency_display', 'time', 'enabled_badge', 'next_run')
	list_filter = ('frequency', 'enabled', 'created_at')
	search_fields = ('name', 'robot')
	readonly_fields = ('created_at', 'updated_at', 'last_run')
	
	fieldsets = (
		('Zamanlama Bilgisi', {
			'fields': ('schedule_id', 'name', 'robot', 'enabled')
		}),
		('Zamanlama Parametreleri', {
			'fields': ('frequency', 'time', 'day')
		}),
		('Çalıştırma Geçmişi', {
			'fields': ('last_run', 'next_run'),
			'classes': ('collapse',)
		}),
		('Zaman Damgaları', {
			'fields': ('created_at', 'updated_at'),
			'classes': ('collapse',)
		}),
	)
	
	def frequency_display(self, obj):
		return obj.get_frequency_display()
	frequency_display.short_description = 'Sıklık'
	
	def enabled_badge(self, obj):
		color = '#39ff14' if obj.enabled else '#ff003c'
		status = 'Aktif' if obj.enabled else 'Pasif'
		return format_html(
			'<span style="color: {}; font-weight: bold;">●</span> {}',
			color,
			status
		)
	enabled_badge.short_description = 'Durum'


@admin.register(TelegramBot)
class TelegramBotAdmin(admin.ModelAdmin):
	list_display = ('name', 'bot_username', 'default_parse_mode', 'is_active', 'updated_at')
	list_filter = ('is_active', 'default_parse_mode')
	search_fields = ('name', 'bot_username')


@admin.register(TelegramGroup)
class TelegramGroupAdmin(admin.ModelAdmin):
	list_display = ('name', 'chat_id', 'default_bot', 'is_active', 'updated_at')
	list_filter = ('is_active',)
	search_fields = ('name', 'chat_id', 'owners')


@admin.register(MailAccount)
class MailAccountAdmin(admin.ModelAdmin):
	list_display = ('name', 'email', 'smtp_host', 'smtp_port', 'is_active', 'updated_at')
	list_filter = ('is_active', 'use_tls', 'use_ssl')
	search_fields = ('name', 'email', 'smtp_host')


@admin.register(RobotAgent)
class RobotAgentAdmin(admin.ModelAdmin):
	list_display = ('code', 'name', 'status', 'agent_version', 'desired_version', 'is_enabled', 'machine_name', 'ip_address', 'last_seen_at')
	list_filter = ('status', 'is_enabled', 'updated_at')
	search_fields = ('code', 'name', 'machine_name', 'host_name', 'ip_address')
	readonly_fields = ('created_at', 'updated_at', 'last_seen_at', 'last_startup_at', 'token_hash')


@admin.register(RobotJob)
class RobotJobAdmin(admin.ModelAdmin):
	list_display = ('id', 'command_type', 'sap_process', 'target_agent', 'status', 'priority', 'created_at', 'finished_at')
	list_filter = ('command_type', 'status', 'created_at', 'target_agent')
	search_fields = ('id', 'result_message', 'requested_by')
	readonly_fields = ('created_at', 'updated_at', 'started_at', 'finished_at', 'last_heartbeat_at')


@admin.register(RobotAgentRelease)
class RobotAgentReleaseAdmin(admin.ModelAdmin):
	list_display = ('version', 'is_active', 'is_mandatory', 'download_url', 'created_by', 'created_at')
	list_filter = ('is_active', 'is_mandatory', 'created_at')
	search_fields = ('version', 'download_url', 'created_by', 'release_notes')


@admin.register(RobotAgentEvent)
class RobotAgentEventAdmin(admin.ModelAdmin):
	list_display = ('id', 'agent', 'job', 'level', 'message_short', 'created_at')
	list_filter = ('level', 'created_at', 'agent')
	search_fields = ('message', 'agent__code', 'agent__name')
	readonly_fields = ('created_at',)

	def message_short(self, obj):
		msg = str(obj.message or '')
		return msg if len(msg) <= 90 else msg[:87] + '...'
	message_short.short_description = 'Mesaj'
