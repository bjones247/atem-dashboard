"""Offline tests for protocol-identity-scoped dashboard configuration."""

from copy import deepcopy
import time
from types import SimpleNamespace

import pytest

from atem_control.control import dashboard_config
from atem_control.models import DashboardDeviceConfig, dashboard_device_defaults


DEVICE_A = '7665f2ed6f4042e6bbcbbe17ef0143e7'
DEVICE_B = '0123456789abcdef0123456789abcdef'


class FakeConnection:
    """Weak-referenceable stand-in for WebATEM's pooled connection object."""


def connection(device_id=DEVICE_A, ip='192.168.1.12'):
    fake = FakeConnection()
    fake.is_ready = True
    fake.is_connected = True
    fake.protocol = SimpleNamespace(transport=SimpleNamespace(last_rx_monotonic=time.monotonic()))
    fake.mixerstate = {
        'device-identity': SimpleNamespace(device_id=device_id, ip=ip),
        'topology': SimpleNamespace(aux_outputs=6),
        'input-properties': {
            501: SimpleNamespace(index=501, name='Studio Input', short_name='STU',
                                 port_type=0, available_aux=True),
            502: SimpleNamespace(index=502, name='Studio Input 2', short_name='ST2',
                                 port_type=0, available_aux=True),
        },
        'aux-output-source': {i: SimpleNamespace(source=501) for i in range(6)},
    }
    return fake


def changed_config(source=501):
    config = deepcopy(dashboard_device_defaults())
    config['virtualSwitchers']['virtual1']['previewSource'] = source
    config['customNames']['virtual1'] = 'Studio Feed'
    return config


@pytest.mark.django_db
def test_config_is_saved_and_reloaded_by_protocol_switcher_id_across_ip_change():
    first = connection(ip='192.168.1.12')
    initial = dashboard_config.get_config_for_connection(first, ip='192.168.1.12')
    saved = dashboard_config.update_config_for_connection(
        first, initial['revision'], changed_config(), ip='192.168.1.12')

    reconnected = dashboard_config.get_config_for_connection(
        connection(ip='10.8.0.44'), ip='10.8.0.44')

    assert saved['deviceId'] == DEVICE_A
    assert reconnected['deviceId'] == DEVICE_A
    assert reconnected['revision'] == saved['revision']
    assert reconnected['config']['virtualSwitchers']['virtual1']['previewSource'] == 501
    assert reconnected['config']['customNames']['virtual1'] == 'Studio Feed'
    assert DashboardDeviceConfig.objects.get(hardware_id=DEVICE_A).last_ip == '10.8.0.44'
    assert DashboardDeviceConfig.objects.count() == 1


@pytest.mark.django_db
def test_different_switcher_gets_its_own_defaults_and_configuration():
    config_a = dashboard_config.get_config_for_connection(connection(DEVICE_A), ip='192.168.1.12')
    dashboard_config.update_config_for_connection(
        connection(DEVICE_A), config_a['revision'], changed_config(502), ip='192.168.1.12')

    config_b = dashboard_config.get_config_for_connection(connection(DEVICE_B), ip='192.168.1.12')

    assert config_b['deviceId'] == DEVICE_B
    assert config_b['revision'] == 1
    assert config_b['config']['virtualSwitchers']['virtual1']['previewSource'] is None
    assert DashboardDeviceConfig.objects.count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize('identity', [None, [], {}, SimpleNamespace(device_id='not-a-switcher-id')])
def test_missing_or_ambiguous_identity_never_falls_back_to_ip(identity):
    dashboard_config.get_config(DEVICE_A, ip='192.168.1.12')
    bad_connection = SimpleNamespace(
        is_ready=True,
        is_connected=True,
        mixerstate={} if identity is None else {'device-identity': identity},
    )

    with pytest.raises(dashboard_config.DashboardConfigError):
        dashboard_config.get_config_for_connection(bad_connection, ip='192.168.1.12')

    assert DashboardDeviceConfig.objects.count() == 1
    assert DashboardDeviceConfig.objects.get().hardware_id == DEVICE_A


@pytest.mark.django_db
def test_revision_compare_and_swap_rejects_second_session_stale_write():
    first = dashboard_config.get_config(DEVICE_A, ip='192.168.1.12')
    session_one_config = changed_config(601)
    session_two_config = changed_config(602)

    updated = dashboard_config.update_config(DEVICE_A, first['revision'], session_one_config)
    with pytest.raises(dashboard_config.DashboardConfigError, match='Stale configuration revision'):
        dashboard_config.update_config(DEVICE_A, first['revision'], session_two_config)

    current = dashboard_config.get_config(DEVICE_A)
    assert updated['revision'] == first['revision'] + 1
    assert current['revision'] == updated['revision']
    assert current['config']['virtualSwitchers']['virtual1']['previewSource'] == 601


@pytest.mark.django_db
def test_config_update_rejects_outputs_or_sources_missing_from_current_capabilities():
    initial = dashboard_config.get_config_for_connection(connection(), ip='192.168.1.12')
    proposed = changed_config(999)
    proposed['virtualSwitchers']['virtual2']['outputs'] = [9]

    with pytest.raises(dashboard_config.DashboardConfigError,
                       match='Configuration conflicts with discovered ATEM state'):
        dashboard_config.update_config_for_connection(
            connection(), initial['revision'], proposed, ip='192.168.1.12')

    current = dashboard_config.get_config_for_connection(connection(), ip='192.168.1.12')
    assert current['revision'] == initial['revision']
    assert current['config'] == initial['config']


def test_invalid_ids_are_rejected_without_ip_or_name_fallback():
    for value in (None, '', '192.168.1.12', 'atem-studio', 'a' * 31, 'g' * 32):
        with pytest.raises(dashboard_config.DashboardConfigError):
            dashboard_config.canonical_device_id(value)

