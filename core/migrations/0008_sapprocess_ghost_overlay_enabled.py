from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_alter_sapprocessstep_step_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='sapprocess',
            name='ghost_overlay_enabled',
            field=models.BooleanField(default=True, help_text='Calistirma sirasinda hayalet log overlay goster'),
        ),
    ]
