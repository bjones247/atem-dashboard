from django.db import migrations, models
import atem_control.models


class Migration(migrations.Migration):

    dependencies = [
        ('webatem_atem', '0002_legacy_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='DashboardDeviceConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('hardware_id', models.CharField(max_length=128, unique=True)),
                ('identity_source', models.CharField(default='protocol', max_length=16)),
                ('last_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('display_name', models.CharField(blank=True, default='', max_length=128)),
                ('model_name', models.CharField(blank=True, default='', max_length=128)),
                ('revision', models.PositiveBigIntegerField(default=1)),
                ('config', models.JSONField(default=atem_control.models.dashboard_device_defaults)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Dashboard device configuration',
            },
        ),
    ]
