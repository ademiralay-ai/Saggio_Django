from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_alter_sapprocessstep_step_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='sapprocess',
            name='office_express_auto_close',
            field=models.BooleanField(default=True, help_text='Ofis Ekspres popup geldiğinde otomatik kapat'),
        ),
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
                    ('sap_branch_no_data_guard', 'Şube Veri Kontrolü (Grid Yoksa Sonraki Şube)'),
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
