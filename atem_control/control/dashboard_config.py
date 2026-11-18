"""Revisioned dashboard configuration keyed by the connected ATEM WhoI ID."""

import re

from django.db import IntegrityError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from atem_control.models import DashboardDeviceConfig, dashboard_device_defaults


class DashboardConfigError(ValueError):
    pass


def device_id_from_connection(connection):
    """Return the active connection's protocol-reported WhoI device ID.

    Never infer identity from the connection address, mDNS registry, device
    name, or model. Older firmware that omits WhoI can still be controlled,
    but cannot safely load or save persistent dashboard configuration.
    """
    if connection is None or not getattr(connection, 'is_ready', getattr(connection, 'is_connected', False)):
        raise DashboardConfigError('ATEM connection is not ready; device settings are unavailable.')
    mixerstate = getattr(connection, 'mixerstate', None)
    if not isinstance(mixerstate, dict):
        raise DashboardConfigError('Current ATEM state is unavailable; device settings are unavailable.')
    identity = mixerstate.get('device-identity')
    if identity is None or isinstance(identity, (list, tuple, dict)):
        raise DashboardConfigError('ATEM did not provide one unambiguous WhoI device ID; settings are not loaded.')
    return canonical_device_id(getattr(identity, 'device_id', None))


def canonical_device_id(value):
    """WhoI device_id is the switcher-specific 32-character hex identifier."""
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-fA-F]{32}', value) is None:
        raise DashboardConfigError(
            'This ATEM did not provide a valid WhoI device ID; dashboard settings cannot be persisted safely.')
    return value.lower()


def get_config_for_connection(connection, ip=None):
    return get_config(device_id_from_connection(connection), ip=ip)


def get_config(device_id, ip=None):
    hardware_id = canonical_device_id(device_id)
    try:
        with transaction.atomic():
            row, _created = DashboardDeviceConfig.objects.get_or_create(
                hardware_id=hardware_id,
                defaults={'identity_source': 'protocol', 'last_ip': ip,
                          'config': dashboard_device_defaults()},
            )
    except IntegrityError:
        # Another session may initialize the same device row concurrently.
        row = DashboardDeviceConfig.objects.get(hardware_id=hardware_id)
    if ip is not None and row.last_ip != ip:
        DashboardDeviceConfig.objects.filter(pk=row.pk).update(last_ip=ip)
        row.last_ip = ip
    config = row.config
    if isinstance(config, dict) and 'customNames' not in config:
        # Additive schema evolution for configurations initialized by the
        # earlier 3A draft, without rewriting or bumping their stored revision
        # on a read.
        config = {**config, 'customNames': dashboard_device_defaults()['customNames']}
    return {'deviceId': row.hardware_id, 'revision': row.revision, 'config': config}


def _validate_config(config):
    if not isinstance(config, dict) or config.get('schemaVersion') != 1:
        raise DashboardConfigError('Unsupported dashboard configuration schema.')
    groups = config.get('virtualSwitchers')
    if not isinstance(groups, dict) or set(groups) != {'virtual1', 'virtual2'}:
        raise DashboardConfigError('Both virtual switcher configurations are required.')
    all_outputs = []
    for group_id in ('virtual1', 'virtual2'):
        group = groups[group_id]
        if not isinstance(group, dict) or not isinstance(group.get('outputs'), list):
            raise DashboardConfigError(f'{group_id} output assignments are malformed.')
        # Persisted destination integers remain zero-based AUX indices. The
        # projection maps them to the installation's physical OUT labels.
        outputs = group['outputs']
        if any(type(output) is not int or output < 0 for output in outputs):
            raise DashboardConfigError(f'{group_id} output assignments must be nonnegative channel IDs.')
        if len(outputs) != len(set(outputs)):
            raise DashboardConfigError(f'{group_id} contains duplicate output assignments.')
        all_outputs.extend(outputs)
        for field in ('previewSource', 'programTarget'):
            value = group.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise DashboardConfigError(f'{group_id} {field} must be a source ID or null.')
    if len(all_outputs) != len(set(all_outputs)):
        raise DashboardConfigError('A physical output cannot belong to both virtual switchers.')
    names = config.get('customNames')
    if not isinstance(names, dict) or set(names) != {'primary', 'virtual1', 'virtual2'}:
        raise DashboardConfigError('Custom names for all three switchers are required.')
    if any(value is not None and (not isinstance(value, str) or len(value) > 128)
           for value in names.values()):
        raise DashboardConfigError('Custom switcher names must be at most 128 characters or null.')
    if type(config.get('minimumPrimaryDestinations')) is not bool:
        raise DashboardConfigError('Minimum Primary destination policy must be boolean.')
    if not isinstance(config.get('preferences'), dict):
        raise DashboardConfigError('Dashboard preferences must be an object.')


def update_config(device_id, expected_revision, config, ip=None):
    hardware_id = canonical_device_id(device_id)
    _validate_config(config)
    if type(expected_revision) is not int or expected_revision < 1:
        raise DashboardConfigError('A valid configuration revision is required.')
    with transaction.atomic():
        updates = {'config': config, 'revision': F('revision') + 1,
                   'updated_at': timezone.now()}
        if ip is not None:
            updates['last_ip'] = ip
        changed = DashboardDeviceConfig.objects.filter(
            hardware_id=hardware_id, revision=expected_revision).update(**updates)
        if changed == 0:
            row = DashboardDeviceConfig.objects.filter(hardware_id=hardware_id).first()
            if row is None:
                raise DashboardConfigError('Load the device configuration before updating it.')
            raise DashboardConfigError(
                f'Stale configuration revision {expected_revision}; current revision is {row.revision}.')
        row = DashboardDeviceConfig.objects.get(hardware_id=hardware_id)
    return {'deviceId': hardware_id, 'revision': row.revision, 'config': row.config}


def update_config_for_connection(connection, expected_revision, config, ip=None):
    device_id = device_id_from_connection(connection)
    from atem_control.control.dashboard_switching import state_is_fresh
    from atem_control.control.dashboard_ownership import validate_config_against_state

    conflicts = validate_config_against_state(
        connection.mixerstate, config, state_fresh=state_is_fresh(connection))
    if conflicts:
        labels = sorted({item.get('reason') or
                         f"{item['type']}:{('OUT ' + str(item['outputId'])) if item.get('outputId') else item.get('sourceId', '')}"
                         for item in conflicts})
        raise DashboardConfigError('Configuration conflicts with discovered ATEM state: ' + ', '.join(labels))
    return update_config(device_id, expected_revision, config, ip=ip)


def identity_snapshot(connection):
    """Non-throwing protocol identity for state projection; never uses mDNS."""
    try:
        return {'hardware_id': device_id_from_connection(connection), 'source': 'protocol'}
    except DashboardConfigError as error:
        return {'hardware_id': None, 'source': None, 'reason': str(error)}
