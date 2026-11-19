"""Offline multi-session dashboard configuration notifications."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync
from channels.layers import InMemoryChannelLayer

from atem_control.control import dashboard_config
from atem_control.control.consumer import ATEMConsumer
from tests.unit.test_dashboard_config import DEVICE_A, changed_config, connection


@pytest.mark.django_db
def test_config_revision_broadcast_refreshes_other_session_and_stale_save_is_rejected():
    initial = dashboard_config.get_config_for_connection(connection(), ip='192.168.1.12')
    revised = dashboard_config.update_config_for_connection(
        connection(), initial['revision'], changed_config(502), ip='192.168.1.12')

    layer = InMemoryChannelLayer()
    other_channel = async_to_sync(layer.new_channel)('dashboard-test')
    group = ATEMConsumer._dashboard_config_group_name(DEVICE_A)
    async_to_sync(layer.group_add)(group, other_channel)

    other = ATEMConsumer.__new__(ATEMConsumer)
    other.channel_layer = layer
    other.channel_name = other_channel
    other.connection = connection()
    other.current_ip = '192.168.1.12'
    other._dashboard_device_id = DEVICE_A
    other._dashboard_config_group = group
    other._dashboard_config = initial
    sent = []

    async def send_json(message):
        sent.append(message)

    other.send_json = send_json
    other.send_current_state = AsyncMock()

    publisher = ATEMConsumer.__new__(ATEMConsumer)
    publisher.channel_layer = layer
    publisher.channel_name = 'config-publisher'
    publisher._dashboard_config_group = group
    async_to_sync(publisher._broadcast_dashboard_config_revision)(revised)
    event = async_to_sync(layer.receive)(other_channel)
    async_to_sync(other.dashboard_config_changed)(event)

    assert sent[0]['type'] == 'dashboard_config_changed'
    assert sent[0]['revision'] == revised['revision']
    assert sent[0]['config'] == revised['config']
    other.send_current_state.assert_awaited_once()
    with pytest.raises(dashboard_config.DashboardConfigError, match='Stale configuration revision'):
        dashboard_config.update_config_for_connection(
            connection(), initial['revision'], changed_config(501), ip='192.168.1.12')


@pytest.mark.django_db
def test_state_projection_retires_primary_claim_and_notifies_other_tab():
    device = connection()
    device.mixerstate['input-properties'][90010] = SimpleNamespace(
        name='M/E 1 Program', short_name='PGM', port_type=128, available_aux=True)
    initial = dashboard_config.get_config_for_connection(device)
    config = changed_config()
    config['virtualSwitchers']['virtual1']['outputs'] = [2]
    saved = dashboard_config.update_config_for_connection(device, initial['revision'], config)

    layer = InMemoryChannelLayer()
    group = ATEMConsumer._dashboard_config_group_name(DEVICE_A)
    other_channel = async_to_sync(layer.new_channel)('dashboard-test')
    async_to_sync(layer.group_add)(group, other_channel)
    publisher = ATEMConsumer.__new__(ATEMConsumer)
    publisher.connection = device
    publisher.current_ip = '192.168.1.12'
    publisher.channel_layer = layer
    publisher.channel_name = 'config-publisher'
    publisher._dashboard_config_group = group
    publisher.send_json = AsyncMock()

    device.mixerstate['aux-output-source'][2].source = 90010
    state = {'is_connected': True, 'dashboardSafety': {'fresh': True}}
    projection = async_to_sync(publisher._project_dashboard_routes)(state, saved)
    assert projection['primaryOutputIds'] == [3]
    assert 3 not in projection['otherOutputIds']
    assert projection['groups']['virtual1']['outputIds'] == []
    assert projection['revision'] == saved['revision'] + 1
    publisher.send_json.assert_awaited_once_with(
        {'type': 'dashboard_primary_destinations_reconciled', 'outputs': [3]})

    other = ATEMConsumer.__new__(ATEMConsumer)
    other.connection = device
    other.current_ip = publisher.current_ip
    other.channel_name = other_channel
    other._dashboard_device_id = DEVICE_A
    other.send_json = AsyncMock()
    other.send_current_state = AsyncMock()
    event = async_to_sync(layer.receive)(other_channel)
    async_to_sync(other.dashboard_config_changed)(event)
    assert other.send_json.await_args_list[0].args[0]['config']['virtualSwitchers']['virtual1']['outputs'] == []
    assert other.send_json.await_args_list[1].args[0]['outputs'] == [3]
