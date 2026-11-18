from django.conf import settings
from django.db import models
from django.utils import timezone


def dashboard_device_defaults():
    return {
        'schemaVersion': 1,
        'virtualSwitchers': {
            'virtual1': {'outputs': [], 'previewSource': None, 'programTarget': None},
            'virtual2': {'outputs': [], 'previewSource': None, 'programTarget': None},
        },
        'customNames': {'primary': None, 'virtual1': None, 'virtual2': None},
        'minimumPrimaryDestinations': True,
        'preferences': {},
    }


class DashboardDeviceConfig(models.Model):
    """Persistent dashboard state keyed only by protocol WhoI device ID."""

    hardware_id = models.CharField(max_length=128, unique=True)
    identity_source = models.CharField(max_length=16, default='protocol')
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    display_name = models.CharField(max_length=128, blank=True, default='')
    model_name = models.CharField(max_length=128, blank=True, default='')
    revision = models.PositiveBigIntegerField(default=1)
    config = models.JSONField(default=dashboard_device_defaults)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dashboard device configuration'

    def __str__(self):
        return f'{self.display_name or self.hardware_id} (r{self.revision})'


class ATEMControlLog(models.Model):
    """Connect/disconnect audit trail. Drives the Connect page's
    "Recent ATEMs" quick-connect list. ``user`` is set when the host's ASGI
    stack authenticates (a hosting platform); standalone WebATEM has no
    users and leaves it empty."""

    LOG_TYPE_CHOICES = [
        ('connection', 'Connection'),
        ('disconnection', 'Disconnection'),
    ]

    date = models.DateTimeField('Date', default=timezone.now, db_index=True)
    type = models.CharField('Type', max_length=20, choices=LOG_TYPE_CHOICES, db_index=True)
    data = models.JSONField('Data', default=dict)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='webatem_atem_logs')

    class Meta:
        verbose_name = 'ATEM Control Log'
        verbose_name_plural = 'ATEM Control Logs'
        ordering = ['-date']
        indexes = [
            models.Index(fields=['type', '-date'], name='webatem_atem_type_date_idx'),
            models.Index(fields=['user', '-date'], name='webatem_atem_user_date_idx'),
        ]

    def __str__(self):
        ip_address = self.data.get('ip_address', 'Unknown')
        return f"{self.type} - {ip_address} - {self.date}"


def get_recent_atems(limit=5, user=None):
    """The last N unique ATEM IPs connected to, most recent first (one
    user's when ``user`` is given). Dicts with 'ip_address',
    'equipment_name', 'last_connected'."""
    qs = ATEMControlLog.objects.filter(type='connection')
    if user is not None:
        qs = qs.filter(user=user)
    seen_ips = {}
    for log in qs.order_by('-date')[:200]:
        ip_address = log.data.get('ip_address')
        if ip_address and ip_address not in seen_ips:
            seen_ips[ip_address] = {
                'ip_address': ip_address,
                'equipment_name': log.data.get('equipment_name'),
                'last_connected': log.date,
            }
            if len(seen_ips) >= limit:
                break
    return list(seen_ips.values())
