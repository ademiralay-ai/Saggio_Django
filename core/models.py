from django.db import models
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

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
	allowed_user_ids = models.TextField(
		blank=True,
		help_text='İzinli Telegram numerik user ID\'leri. Her satıra bir ID veya virgülle ayrılmış. Boş bırakılırsa kimse butonları kullanamaz (kapalı bot).'
	)
	webhook_secret = models.CharField(
		max_length=64, blank=True,
		help_text='Telegram webhook URL\'inde kullanılan rastgele güvenlik anahtarı. Boş bırakılırsa otomatik üretilir.'
	)
	webhook_registered_url = models.CharField(
		max_length=500, blank=True,
		help_text='Telegram tarafına en son kayıt edilen webhook URL\'i (bilgi amaçlı).'
	)
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
		if not self.webhook_secret:
			import secrets
			self.webhook_secret = secrets.token_urlsafe(32)
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
	sap_retry_enabled = models.BooleanField(default=True, help_text='SAP bağlantısı yoksa periyodik tekrar dene')
	sap_retry_interval_minutes = models.PositiveIntegerField(default=10, help_text='SAP bağlantı denemeleri arası bekleme (dakika)')
	sap_retry_max_duration_minutes = models.PositiveIntegerField(default=180, help_text='Toplam SAP bağlantı bekleme süresi (dakika). 0 = sınırsız')
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
	TYPE_SAP_KEY_PRESS = 'sap_key_press'
	TYPE_SAP_SELECT_OPTION = 'sap_select_option'
	TYPE_SAP_FILL_INPUT = 'sap_fill_input'
	TYPE_CONVERT_SAP_EXPORT = 'convert_sap_export'
	TYPE_WINDOWS_DIALOG_ACTION = 'windows_dialog_action'
	TYPE_WINDOWS_SCAN_DIALOGS = 'windows_scan_dialogs'
	TYPE_SAP_POPUP_DECIDE = 'sap_popup_decide'
	TYPE_SAP_BRANCH_NO_DATA_GUARD = 'sap_branch_no_data_guard'
	TYPE_SAP_PRESS_BUTTON = 'sap_press_button'
	TYPE_SAP_SELECT_ROW = 'sap_select_row'
	TYPE_FTP_LIST    = 'ftp_list'
	TYPE_FTP_DOWNLOAD = 'ftp_download'
	TYPE_FTP_UPLOAD  = 'ftp_upload'
	TYPE_SAP_CLOSE   = 'sap_close'
	TYPE_SHOW_MESSAGE = 'show_message'
	TYPE_EXCEL_LOOP_NEXT = 'excel_loop_next'
	TYPE_RUN_PROCESS = 'run_process'
	TYPE_LOOP_NEXT   = 'loop_next'
	TYPE_IF_ELSE     = 'if_else'
	TYPE_IF_END      = 'if_end'
	TYPE_LOOP_GENERIC = 'loop_generic'
	TYPE_PY_SCRIPT   = 'py_script'
	TYPE_EXCEL_ROW_LOG = 'excel_row_log'
	TYPE_SEND_REPORT_MAIL = 'send_report_mail'

	STEP_TYPE_CHOICES = [
		(TYPE_SAP_FILL,   'SAP Ekranı Doldur (Şablon)'),
		(TYPE_SAP_RUN,    'F8 – Çalıştır'),
		(TYPE_SAP_WAIT,   'Ekranı Bekle'),
		(TYPE_SAP_SCAN,   'Derin Tarama'),
		(TYPE_SAP_ACTION, 'Aksiyon Yap'),
		(TYPE_SAP_KEY_PRESS, 'Tuşa Bas (Klavye)'),
		(TYPE_SAP_SELECT_OPTION, 'Radio/Checkbox Seç'),
		(TYPE_SAP_FILL_INPUT, 'Input Doldur'),
		(TYPE_CONVERT_SAP_EXPORT, 'SAP Export Dönüştür (XLSX)'),
		(TYPE_WINDOWS_DIALOG_ACTION, 'Windows Popup İşle'),
		(TYPE_WINDOWS_SCAN_DIALOGS, 'Windows Popup Tanı (Diagnostic)'),
		(TYPE_SAP_POPUP_DECIDE, 'Popup Karar Ver'),
		(TYPE_SAP_BRANCH_NO_DATA_GUARD, 'Şube Veri Kontrolü (Grid Yoksa Sonraki Şube)'),
		(TYPE_SAP_PRESS_BUTTON, 'SAP Butonuna Bas'),
		(TYPE_SAP_SELECT_ROW, 'Satır Seç (Grid)'),
		(TYPE_FTP_LIST,   'FTP Listele'),
		(TYPE_FTP_DOWNLOAD, 'FTP İndir'),
		(TYPE_FTP_UPLOAD, 'FTP Yükle'),
		(TYPE_SAP_CLOSE,  'SAP Kapat'),
		(TYPE_SHOW_MESSAGE, 'Mesaj Göster'),
		(TYPE_EXCEL_LOOP_NEXT, 'Excel Satır Sonraki'),
		(TYPE_RUN_PROCESS, 'Süreç Çalıştır (Alt Süreç)'),
		(TYPE_LOOP_NEXT,  'Döngü – Sonraki Kayıt'),
		(TYPE_IF_ELSE, 'IF / ELSE'),
		(TYPE_IF_END, 'IF Sonu'),
		(TYPE_LOOP_GENERIC, 'Döngü (Generic)'),
		(TYPE_PY_SCRIPT, 'Python Script Çalıştır'),
		(TYPE_EXCEL_ROW_LOG, 'Satır Sonucu Yaz'),
		(TYPE_SEND_REPORT_MAIL, 'Rapor Oluştur ve Mail Gönder'),
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


class TelegramBotMenu(models.Model):
	"""Bot için tanımlanmış klavye menüsü"""
	bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE, related_name='menus')
	name = models.CharField(max_length=120)
	trigger_command = models.CharField(max_length=50, default='/start', help_text='Bu menüyü tetikleyen komut (örn. /start)')
	welcome_message = models.TextField(default='Merhaba! Ne yapmamı istersiniz?', help_text='Butonlarla birlikte gönderilecek karşılama mesajı')
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Telegram Bot Menüsü'
		verbose_name_plural = 'Telegram Bot Menüleri'
		ordering = ['bot', 'name']
		unique_together = [('bot', 'trigger_command')]

	def __str__(self):
		return f"{self.bot.name} – {self.name}"


class TelegramBotButton(models.Model):
	"""Bir bot menüsündeki tek buton — bir SAP sürecine bağlıdır"""
	menu = models.ForeignKey(TelegramBotMenu, on_delete=models.CASCADE, related_name='buttons')
	label = models.CharField(max_length=200)
	sap_process = models.ForeignKey(
		SapProcess, on_delete=models.SET_NULL, null=True, blank=True,
		related_name='telegram_buttons', help_text='Bu butona basınca tetiklenecek SAP süreci'
	)
	row = models.PositiveSmallIntegerField(default=0, help_text='Klavye satir numarasi (0dan baslar)')
	col = models.PositiveSmallIntegerField(default=0, help_text='Satır içi sıralama')

	class Meta:
		verbose_name = 'Telegram Bot Butonu'
		verbose_name_plural = 'Telegram Bot Butonları'
		ordering = ['row', 'col']

	def __str__(self):
		return f"{self.menu} → {self.label}"


class RobotAgent(models.Model):
	"""Sunucuya bağlanan Windows robot ajanı."""
	STATUS_CHOICES = [
		('offline', 'Offline'),
		('online', 'Online'),
		('busy', 'Mesgul'),
		('maintenance', 'Bakim'),
	]

	code = models.CharField(max_length=80, unique=True, help_text='Ajanin sabit kimligi (robot-01 gibi)')
	name = models.CharField(max_length=180)
	token_hash = models.CharField(max_length=255, help_text='Ajan kimlik dogrulama token hash degeri')
	is_enabled = models.BooleanField(default=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')
	machine_name = models.CharField(max_length=120, blank=True)
	host_name = models.CharField(max_length=180, blank=True)
	ip_address = models.CharField(max_length=64, blank=True)
	os_user = models.CharField(max_length=120, blank=True)
	agent_version = models.CharField(max_length=40, blank=True)
	desired_version = models.CharField(max_length=40, blank=True, help_text='Bu ajan için hedef EXE sürümü')
	capabilities = models.JSONField(default=dict, blank=True)
	last_seen_at = models.DateTimeField(null=True, blank=True)
	last_startup_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Robot Ajanı'
		verbose_name_plural = 'Robot Ajanları'
		ordering = ['code']

	def __str__(self):
		return f"{self.code} - {self.name} ({self.status})"

	def set_token(self, raw_token):
		raw = str(raw_token or '').strip()
		if not raw:
			raise ValueError('Token boş olamaz.')
		self.token_hash = make_password(raw)

	def verify_token(self, raw_token):
		raw = str(raw_token or '').strip()
		if not raw:
			return False
		return check_password(raw, self.token_hash)

	def mark_seen(self, startup=False):
		now = timezone.now()
		self.last_seen_at = now
		if startup:
			self.last_startup_at = now


class RobotAgentRelease(models.Model):
	"""Robot ajan EXE sürüm yayın kaydı."""
	version = models.CharField(max_length=40, unique=True)
	release_notes = models.TextField(blank=True)
	download_url = models.CharField(max_length=600, blank=True)
	setup_file = models.CharField(max_length=500, blank=True, help_text='Sunucuda saklanan setup exe yolu')
	checksum_sha256 = models.CharField(max_length=128, blank=True)
	install_command = models.CharField(max_length=800, blank=True, help_text='Ajan güncelleme için çalıştırılacak komut şablonu')
	is_active = models.BooleanField(default=True)
	is_mandatory = models.BooleanField(default=False)
	created_by = models.CharField(max_length=120, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Robot Ajan Release'
		verbose_name_plural = 'Robot Ajan Release Kayıtları'
		ordering = ['-created_at']

	def __str__(self):
		return f"{self.version} ({'active' if self.is_active else 'passive'})"


class RobotAgentEvent(models.Model):
	"""Ajanlardan gelen operasyon log/event kayıtları."""
	LEVEL_CHOICES = [
		('info', 'Info'),
		('warning', 'Warning'),
		('error', 'Error'),
	]

	agent = models.ForeignKey(RobotAgent, on_delete=models.CASCADE, related_name='events')
	job = models.ForeignKey('RobotJob', on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
	level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='info')
	message = models.TextField()
	extra = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Robot Ajan Event'
		verbose_name_plural = 'Robot Ajan Event Kayıtları'
		ordering = ['-created_at']
		indexes = [
			models.Index(fields=['agent', 'created_at']),
			models.Index(fields=['level', 'created_at']),
		]

	def __str__(self):
		return f"{self.agent.code} [{self.level}] {self.message[:60]}"


class RobotJob(models.Model):
	"""Robot ajanlarına dağıtılan iş kuyruğu girdisi."""
	STATUS_CHOICES = [
		('queued', 'Kuyrukta'),
		('dispatched', 'Ajan Tarafinda Alindi'),
		('running', 'Calisiyor'),
		('succeeded', 'Basarili'),
		('failed', 'Basarisiz'),
		('canceled', 'Iptal'),
	]
	COMMAND_CHOICES = [
		('run_sap_process', 'SAP Süreci Çalıştır'),
		('run_command', 'Komut Çalıştır'),
	]

	command_type = models.CharField(max_length=40, choices=COMMAND_CHOICES, default='run_sap_process')
	sap_process = models.ForeignKey(SapProcess, on_delete=models.SET_NULL, null=True, blank=True, related_name='robot_jobs')
	target_agent = models.ForeignKey(RobotAgent, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
	priority = models.IntegerField(default=100)
	payload = models.JSONField(default=dict, blank=True)
	requested_by = models.CharField(max_length=120, blank=True)
	lease_expires_at = models.DateTimeField(null=True, blank=True)
	started_at = models.DateTimeField(null=True, blank=True)
	finished_at = models.DateTimeField(null=True, blank=True)
	last_heartbeat_at = models.DateTimeField(null=True, blank=True)
	result_message = models.TextField(blank=True)
	result_payload = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Robot İşi'
		verbose_name_plural = 'Robot İşleri'
		ordering = ['-priority', 'created_at']
		indexes = [
			models.Index(fields=['status', 'priority', 'created_at']),
			models.Index(fields=['target_agent', 'status']),
		]

	def __str__(self):
		target = self.target_agent.code if self.target_agent else 'any'
		return f"Job#{self.pk} {self.command_type} -> {target} ({self.status})"


class PeriodicProcessSchedule(models.Model):
	"""Periyodik SAP süreç tetikleme planı."""
	FREQUENCY_CHOICES = [
		('interval', 'Interval (dakika)'),
		('daily', 'Günlük'),
		('weekly', 'Haftalık'),
		('monthly', 'Aylık'),
	]

	name = models.CharField(max_length=180, unique=True)
	sap_process = models.ForeignKey(SapProcess, on_delete=models.CASCADE, related_name='periodic_schedules')
	target_agent = models.ForeignKey(RobotAgent, on_delete=models.SET_NULL, null=True, blank=True, related_name='periodic_schedules')
	frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='daily')
	interval_minutes = models.PositiveIntegerField(null=True, blank=True)
	run_time = models.TimeField(null=True, blank=True)
	weekdays = models.CharField(max_length=32, blank=True, help_text='0-6 arası haftanın günleri (virgülle), 0=Pazartesi')
	day_of_month = models.PositiveSmallIntegerField(null=True, blank=True)
	priority = models.IntegerField(default=300)
	payload = models.JSONField(default=dict, blank=True)
	maintenance_window_start = models.TimeField(null=True, blank=True)
	maintenance_window_end = models.TimeField(null=True, blank=True)
	prevent_overlap = models.BooleanField(default=True)
	overlap_buffer_minutes = models.PositiveIntegerField(default=10)
	enabled = models.BooleanField(default=True)
	note = models.CharField(max_length=300, blank=True)
	last_run_at = models.DateTimeField(null=True, blank=True)
	next_run_at = models.DateTimeField(null=True, blank=True)
	created_by = models.CharField(max_length=120, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Periyodik Süreç Planı'
		verbose_name_plural = 'Periyodik Süreç Planları'
		ordering = ['enabled', 'next_run_at', 'name']
		indexes = [
			models.Index(fields=['enabled', 'next_run_at']),
			models.Index(fields=['frequency']),
		]

	def __str__(self):
		return f"{self.name} [{self.frequency}]"
