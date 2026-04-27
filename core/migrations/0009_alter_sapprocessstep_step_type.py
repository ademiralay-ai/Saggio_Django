from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_sapprocess_ghost_overlay_enabled'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sapprocessstep',
            name='step_type',
            field=models.CharField(
                choices=[
                    ('sap_fill', 'SAP Ekranı Doldur (Şablon)'),
                    ('sap_run', 'F8 – Çalıştır'),
                    ('sap_wait', 'Ekranı Bekle'),
                    ('sap_scan', 'Derin Tarama'),
                    ('sap_action', 'Aksiyon Yap'),
                    ('sap_popup_decide', 'Popup Karar Ver'),
                    ('sap_press_button', 'SAP Butonuna Bas'),
                    ('sap_select_row', 'Satır Seç (Grid)'),
                    ('ftp_list', 'FTP Listele'),
                    ('ftp_download', 'FTP İndir'),
                    ('ftp_upload', 'FTP Yükle'),
                    ('sap_close', 'SAP Kapat'),
                    ('loop_next', 'Döngü – Sonraki Kayıt'),
                    ('if_else', 'IF / ELSE'),
                    ('loop_generic', 'Döngü (Generic)'),
                    ('py_script', 'Python Script Çalıştır'),
                ],
                max_length=50,
            ),
        ),
    ]
