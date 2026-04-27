from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_sapprocess_office_express_auto_close_and_step_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='sapprocess',
            name='mail_notifications_enabled',
            field=models.BooleanField(default=True, help_text='Süreç bildirimlerinde mail gönder'),
        ),
        migrations.AddField(
            model_name='sapprocess',
            name='telegram_notifications_enabled',
            field=models.BooleanField(default=True, help_text='Süreç bildirimlerinde Telegram mesajı gönder'),
        ),
        migrations.AddField(
            model_name='sapprocess',
            name='telegram_voice_enabled',
            field=models.BooleanField(default=True, help_text='Telegram bildirimi yanında sesli mesaj da gönder'),
        ),
    ]
