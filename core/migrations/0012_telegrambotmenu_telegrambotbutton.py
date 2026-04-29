import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_sapprocess_notification_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramBotMenu',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('trigger_command', models.CharField(default='/start', help_text='Bu menüyü tetikleyen komut (örn. /start)', max_length=50)),
                ('welcome_message', models.TextField(default='Merhaba! Ne yapmamı istersiniz?', help_text='Butonlarla birlikte gönderilecek karşılama mesajı')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('bot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='menus', to='core.telegrambot')),
            ],
            options={
                'verbose_name': 'Telegram Bot Menüsü',
                'verbose_name_plural': 'Telegram Bot Menüleri',
                'ordering': ['bot', 'name'],
                'unique_together': {('bot', 'trigger_command')},
            },
        ),
        migrations.CreateModel(
            name='TelegramBotButton',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(max_length=200)),
                ('row', models.PositiveSmallIntegerField(default=0, help_text='Klavye satir numarasi (0dan baslar)')),
                ('col', models.PositiveSmallIntegerField(default=0, help_text='Satır içi sıralama')),
                ('menu', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='buttons', to='core.telegrambotmenu')),
                ('sap_process', models.ForeignKey(blank=True, help_text='Bu butona basınca tetiklenecek SAP süreci', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='telegram_buttons', to='core.sapprocess')),
            ],
            options={
                'verbose_name': 'Telegram Bot Butonu',
                'verbose_name_plural': 'Telegram Bot Butonları',
                'ordering': ['row', 'col'],
            },
        ),
    ]
