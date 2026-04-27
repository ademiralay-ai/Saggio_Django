from django.db import models

from .security_utils import decrypt_secret, encrypt_secret


class Robot(models.Model):
	"""RPA Robot Model"""
	robot_id = models.CharField(max_length=50, unique=True, primary_key=True)
	name = models.CharField(max_length=200)
	status = models.CharField(
		max_length=20,
		choices=[('online', 'Online'), ('offline', 'Offline'), ('maintenance', 'Bakım')],
		default='offline'
	)
	last_run = models.DateTimeField(null=True, blank=True)
	total_runs = models.IntegerField(default=0)
	success_count = models.IntegerField(default=0)
	error_count = models.IntegerField(default=0)
	version = models.CharField(max_length=20)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Robot'
		verbose_name_plural = 'Robotlar'
		ordering = ['name']

	def __str__(self):
		return f"{self.name} ({self.status})"


class Process(models.Model):
	"""RPA Process Model"""
	STATUS_CHOICES = [
		('pending', 'Bekleniyor'),
		('running', 'Çalışıyor'),
		('completed', 'Tamamlandı'),
		('failed', 'Başarısız'),
		('paused', 'Duraklatıldı'),
	]

	process_id = models.CharField(max_length=50, unique=True, primary_key=True)
	name = models.CharField(max_length=200)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
	progress = models.IntegerField(default=0, help_text='0-100 arası yüzde')
	total_items = models.IntegerField(default=0)
	processed = models.IntegerField(default=0)
	error_rate = models.CharField(max_length=10, default='0%')
	robot = models.CharField(max_length=50, null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Süreç'
		verbose_name_plural = 'Süreçler'
		ordering = ['-updated_at']

	def __str__(self):
		return f"{self.name} - {self.get_status_display()}"


class Queue(models.Model):
	"""RPA Queue Item Model"""
	PRIORITY_CHOICES = [
		('low', 'Düşük'),
		('normal', 'Normal'),
		('high', 'Yüksek'),
		('urgent', 'Acil'),
	]

	queue_id = models.CharField(max_length=50, unique=True, primary_key=True)
	queue_name = models.CharField(max_length=100)
	item_name = models.CharField(max_length=200)
	priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
	status = models.CharField(
		max_length=20,
		choices=[('pending', 'Bekleniyor'), ('processing', 'İşleniyor'), ('completed', 'Tamamlandı')],
		default='pending'
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Kuyruk'
		verbose_name_plural = 'Kuyruk Öğeleri'
		ordering = ['-priority', 'created_at']

	def __str__(self):
		return f"{self.item_name} ({self.get_priority_display()})"


class Report(models.Model):
	"""RPA Report Model"""
	report_id = models.CharField(max_length=50, unique=True, primary_key=True)
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	report_type = models.CharField(max_length=50, choices=[
		('monthly', 'Aylık'),
		('weekly', 'Haftalık'),
		('daily', 'Günlük'),
		('performance', 'Performans'),
		('audit', 'Denetim'),
	])
	content = models.JSONField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Rapor'
		verbose_name_plural = 'Raporlar'
		ordering = ['-created_at']

	def __str__(self):
		return f"{self.title} ({self.get_report_type_display()})"


class Schedule(models.Model):
	"""RPA Schedule Model"""
	FREQUENCY_CHOICES = [
		('once', 'Bir Kez'),
		('hourly', 'Saatlik'),
		('daily', 'Günlük'),
		('weekly', 'Haftalık'),
		('monthly', 'Aylık'),
	]

	schedule_id = models.CharField(max_length=50, unique=True, primary_key=True)
	name = models.CharField(max_length=200)
	robot = models.CharField(max_length=50)
	frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
	time = models.TimeField()
	day = models.CharField(max_length=20, null=True, blank=True, help_text='Haftalık/Aylık için')
	enabled = models.BooleanField(default=True)
	last_run = models.DateTimeField(null=True, blank=True)
	next_run = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Zamanlama'
		verbose_name_plural = 'Zamanlamalar'
		ordering = ['name']

	def __str__(self):
		return f"{self.name} ({self.get_frequency_display()})"


class TelegramBot(models.Model):
	"""Telegram bot configuration"""
	PARSE_MODE_CHOICES = [
		('', 'Yok'),
		('HTML', 'HTML'),
		('Markdown', 'Markdown'),
		('MarkdownV2', 'MarkdownV2'),
	]

	name = models.CharField(max_length=120, unique=True)
	bot_username = models.CharField(max_length=120, blank=True)
	bot_token = models.CharField(max_length=255)
	default_parse_mode = models.CharField(max_length=20, choices=PARSE_MODE_CHOICES, blank=True, default='')
	description = models.TextField(blank=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Telegram Botu'
		verbose_name_plural = 'Telegram Botlari'
		ordering = ['name']

	def __str__(self):
		return self.name

	def save(self, *args, **kwargs):
		self.bot_token = encrypt_secret(self.bot_token)
		super().save(*args, **kwargs)

	def get_bot_token(self):
		return decrypt_secret(self.bot_token)

	@property
	def bot_token_masked(self):
		raw = self.get_bot_token()
		if not raw:
			return '********'
		if len(raw) <= 8:
			return '*' * len(raw)
		return f"{raw[:4]}{'*' * (len(raw) - 8)}{raw[-4:]}"


class TelegramGroup(models.Model):
	"""Telegram group/channel configuration"""
	name = models.CharField(max_length=120, unique=True)
	chat_id = models.CharField(max_length=80, unique=True)
	owners = models.CharField(max_length=255, blank=True, help_text='Surec sahibi kisiler veya ekip adlari')
	description = models.TextField(blank=True)
	default_bot = models.ForeignKey(TelegramBot, on_delete=models.SET_NULL, null=True, blank=True, related_name='groups')
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Telegram Grubu'
		verbose_name_plural = 'Telegram Gruplari'
		ordering = ['name']

	def __str__(self):
		return f"{self.name} ({self.chat_id})"


class MailAccount(models.Model):
	"""SMTP mail account configuration"""
	name = models.CharField(max_length=120, unique=True)
	email = models.EmailField(unique=True)
	from_name = models.CharField(max_length=120, blank=True)
	smtp_host = models.CharField(max_length=120)
	smtp_port = models.PositiveIntegerField(default=587)
	smtp_username = models.CharField(max_length=150)
	smtp_password = models.CharField(max_length=255)
	use_tls = models.BooleanField(default=True)
	use_ssl = models.BooleanField(default=False)
	is_active = models.BooleanField(default=True)
	description = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Mail Hesabi'
		verbose_name_plural = 'Mail Hesaplari'
		ordering = ['name']

	def __str__(self):
		return f"{self.name} <{self.email}>"

	def save(self, *args, **kwargs):
		self.smtp_password = encrypt_secret(self.smtp_password)
		super().save(*args, **kwargs)

	def get_smtp_password(self):
		return decrypt_secret(self.smtp_password)

	@property
	def smtp_password_masked(self):
		raw = self.get_smtp_password()
		if not raw:
			return '********'
		if len(raw) <= 6:
			return '*' * len(raw)
		return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


class FTPAccount(models.Model):
	"""FTP/SFTP connection configuration"""
	PROTOCOL_CHOICES = [
		('sftp', 'SFTP'),
		('ftp', 'FTP'),
		('ftps', 'FTPS'),
	]

	name = models.CharField(max_length=120, unique=True)
	protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default='sftp')
	host = models.CharField(max_length=180)
	port = models.PositiveIntegerField(default=22)
	username = models.CharField(max_length=150)
	password = models.CharField(max_length=255)
	remote_base_path = models.CharField(max_length=255, blank=True)
	is_active = models.BooleanField(default=True)
	description = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'FTP Hesabi'
		verbose_name_plural = 'FTP Hesaplari'
		ordering = ['name']

	def __str__(self):
		return f"{self.name} ({self.protocol.upper()})"

	def save(self, *args, **kwargs):
		self.password = encrypt_secret(self.password)
		super().save(*args, **kwargs)

	def get_password(self):
		return decrypt_secret(self.password)

	@property
	def password_masked(self):
		raw = self.get_password()
		if not raw:
			return '********'
		if len(raw) <= 6:
			return '*' * len(raw)
		return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


class SapProcess(models.Model):
	"""SAP otomasyon süreci tanımı (adım listesi ile birlikte)"""
	name = models.CharField(max_length=200, unique=True)
	description = models.TextField(blank=True)
	flow_config = models.JSONField(default=dict, blank=True, help_text='Canvas layout: nodes ve connections')
	ghost_overlay_enabled = models.BooleanField(default=True, help_text='Calistirma sirasinda hayalet log overlay goster')
	office_express_auto_close = models.BooleanField(default=True, help_text='Ofis Ekspres popup geldiğinde otomatik kapat')
	telegram_notifications_enabled = models.BooleanField(default=True, help_text='Süreç bildirimlerinde Telegram mesajı gönder')
	telegram_voice_enabled = models.BooleanField(default=True, help_text='Telegram bildirimi yanında sesli mesaj da gönder')
	mail_notifications_enabled = models.BooleanField(default=True, help_text='Süreç bildirimlerinde mail gönder')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'SAP Süreci'
		verbose_name_plural = 'SAP Süreçleri'
		ordering = ['name']

	def __str__(self):
		return self.name


class SapProcessStep(models.Model):
	"""SAP sürecindeki tek bir adım"""

	TYPE_SAP_FILL    = 'sap_fill'
	TYPE_SAP_RUN     = 'sap_run'
	TYPE_SAP_WAIT    = 'sap_wait'
	TYPE_SAP_SCAN    = 'sap_scan'
	TYPE_SAP_ACTION  = 'sap_action'
	TYPE_SAP_POPUP_DECIDE = 'sap_popup_decide'
	TYPE_SAP_BRANCH_NO_DATA_GUARD = 'sap_branch_no_data_guard'
	TYPE_SAP_PRESS_BUTTON = 'sap_press_button'
	TYPE_SAP_SELECT_ROW = 'sap_select_row'
	TYPE_FTP_LIST    = 'ftp_list'
	TYPE_FTP_DOWNLOAD = 'ftp_download'
	TYPE_FTP_UPLOAD  = 'ftp_upload'
	TYPE_SAP_CLOSE   = 'sap_close'
	TYPE_RUN_PROCESS = 'run_process'
	TYPE_LOOP_NEXT   = 'loop_next'
	TYPE_IF_ELSE     = 'if_else'
	TYPE_LOOP_GENERIC = 'loop_generic'
	TYPE_PY_SCRIPT   = 'py_script'

	STEP_TYPE_CHOICES = [
		(TYPE_SAP_FILL,   'SAP Ekranı Doldur (Şablon)'),
		(TYPE_SAP_RUN,    'F8 – Çalıştır'),
		(TYPE_SAP_WAIT,   'Ekranı Bekle'),
		(TYPE_SAP_SCAN,   'Derin Tarama'),
		(TYPE_SAP_ACTION, 'Aksiyon Yap'),
		(TYPE_SAP_POPUP_DECIDE, 'Popup Karar Ver'),
		(TYPE_SAP_BRANCH_NO_DATA_GUARD, 'Şube Veri Kontrolü (Grid Yoksa Sonraki Şube)'),
		(TYPE_SAP_PRESS_BUTTON, 'SAP Butonuna Bas'),
		(TYPE_SAP_SELECT_ROW, 'Satır Seç (Grid)'),
		(TYPE_FTP_LIST,   'FTP Listele'),
		(TYPE_FTP_DOWNLOAD, 'FTP İndir'),
		(TYPE_FTP_UPLOAD, 'FTP Yükle'),
		(TYPE_SAP_CLOSE,  'SAP Kapat'),
		(TYPE_RUN_PROCESS, 'Süreç Çalıştır (Alt Süreç)'),
		(TYPE_LOOP_NEXT,  'Döngü – Sonraki Kayıt'),
		(TYPE_IF_ELSE, 'IF / ELSE'),
		(TYPE_LOOP_GENERIC, 'Döngü (Generic)'),
		(TYPE_PY_SCRIPT, 'Python Script Çalıştır'),
	]

	process   = models.ForeignKey(SapProcess, on_delete=models.CASCADE, related_name='steps')
	order     = models.PositiveIntegerField(default=0)
	step_type = models.CharField(max_length=50, choices=STEP_TYPE_CHOICES)
	label     = models.CharField(max_length=300, blank=True)
	config    = models.JSONField(default=dict, blank=True)

	class Meta:
		verbose_name = 'SAP Adımı'
		verbose_name_plural = 'SAP Adımları'
		ordering = ['order']

	def __str__(self):
		return f"{self.process.name} – {self.order}. {self.get_step_type_display()}"
