"""Offline behavioral checks for the dashboard's real command preflight."""

import asyncio
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from types import SimpleNamespace as NS

import pytest

from atem_control.control import dashboard_switching as switching
from atem_control.control.commands import dispatch as dispatch_command
from atem_control.control.consumer import ATEMConsumer
from atem_control.models import dashboard_device_defaults


class FakeConnection:
    def __init__(self):
        self.is_connected = True
        self.is_ready = True
        self.protocol = NS(transport=NS(last_rx_monotonic=time.monotonic()))
        self.mixerstate = {
            'program-bus-input': {0: NS(source=1)},
            'preview-bus-input': {0: NS(source=2)},
            'transition-settings': {0: NS(next_transition_bkgd=True,
                                          next_transition_key1=False, next_transition_key2=False,
                                          next_transition_key3=False, next_transition_key4=False)},
            'transition-position': {0: NS(in_transition=False, position=0, frames_remaining=0)},
            'key-on-air': {0: {0: NS(enabled=False), 1: NS(enabled=False)}},
            'aux-output-source': {2: NS(source=1)},
            'input-properties': {1: NS(available_aux=True, available_me1=True),
                                 2: NS(available_aux=True, available_me1=True),
                                 3: NS(available_aux=False, available_me1=True)},
            'topology': NS(aux_outputs=3),
        }


def _me_payload():
    return {'me': 0, 'expected_program': 1, 'expected_preview': 2}


@pytest.mark.parametrize('change,reason', [
    (lambda mx: mx.pop('transition-settings'), 'not been observed'),
    (lambda mx: mx.pop('transition-position'), 'not been observed'),
    (lambda mx: setattr(mx['transition-settings'][0], 'next_transition_key1', None), 'malformed'),
    (lambda mx: setattr(mx['transition-settings'][0], 'next_transition_bkgd', False), 'Background'),
    (lambda mx: setattr(mx['transition-settings'][0], 'next_transition_key2', True), 'KEY 2'),
    (lambda mx: setattr(mx['transition-position'][0], 'in_transition', True), 'in progress'),
    (lambda mx: setattr(mx['transition-position'][0], 'position', 500), 'not at rest'),
    (lambda mx: mx.pop('program-bus-input'), 'not been observed'),
])
def test_me_cut_fails_closed_on_unsafe_or_missing_raw_state(monkeypatch, change, reason):
    c = FakeConnection()
    change(c.mixerstate)
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    ok, error = switching.dispatch_me_cut(c, _me_payload())
    assert not ok and reason in error and not sent


def test_me_cut_requires_fresh_state_and_expected_buses(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    c.protocol.transport.last_rx_monotonic -= switching.MAX_RX_AGE + 1
    assert 'stale' in switching.dispatch_me_cut(c, _me_payload())[1]
    c.protocol.transport.last_rx_monotonic = time.monotonic()
    assert 'changed' in switching.dispatch_me_cut(c, {**_me_payload(), 'expected_preview': 1})[1]
    c.is_ready = False
    assert 'disconnected' in switching.dispatch_me_cut(c, _me_payload())[1]
    assert sent == []


def test_me_cut_uses_observed_rest_state_not_residual_frame_counter(monkeypatch):
    c = FakeConnection()
    c.mixerstate['transition-position'][0].frames_remaining = 7
    c.mixerstate['input-properties'][2].available_me1 = False
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args[1]) or (True, None))
    assert switching.me_cut_readiness(c)[0] is None
    assert switching.dispatch_me_cut(c, _me_payload()) == (True, None)
    assert sent == ['cut']


def _three_c_connection(routes=None):
    c = FakeConnection()
    c.mixerstate['topology'] = NS(aux_outputs=6, downstream_keyers=2, dves=1, stingers=1)
    c.mixerstate['transition-settings'][0].style = 0
    c.mixerstate['input-properties'].update({
        90010: NS(name='M/E 1 Program', short_name='PGM', port_type=128,
                  available_aux=True, available_me1=False),
        90011: NS(name='M/E 1 Preview', short_name='PVW', port_type=128,
                  available_aux=True, available_me1=False),
    })
    c.mixerstate['aux-output-source'] = {
        channel: NS(source=source) for channel, source in (routes or {
            0: 90010, 1: 1, 2: 2, 3: 1, 4: 2, 5: 1,
        }).items()
    }
    return c


def _three_c_config(**groups):
    config = dashboard_device_defaults()
    for group_id, value in groups.items():
        config['virtualSwitchers'][group_id].update(value)
    return {'deviceId': 'a' * 32, 'revision': 7, 'config': config}


def test_guarded_me_preview_direct_program_and_transition_style(monkeypatch):
    c = _three_c_connection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    assert switching.dispatch_me_preview(c, {'me': 0, 'source': 3, 'expected_preview': 2}) == (True, None)
    assert sent[-1] == ('set_preview', {'source': 3, 'me': 0})
    assert 'awaiting' in switching.dispatch_me_preview(c, {'me': 0, 'source': 1, 'expected_preview': 2})[1]
    c.mixerstate['preview-bus-input'][0].source = 3
    assert switching.dispatch_me_program(c, {'me': 0, 'source': 2, 'expected_program': 1}) == (True, None)
    assert sent[-1] == ('set_program', {'source': 2, 'me': 0})
    assert 'awaiting' in switching.dispatch_me_program(c, {'me': 0, 'source': 3, 'expected_program': 1})[1]

    # Clear the simulated in-process M/E operation as if state confirmed it.
    c.mixerstate['program-bus-input'][0].source = 2
    assert switching.dispatch_me_transition_style(c, {'me': 0, 'style': 2}) == (True, None)
    assert sent[-1] == ('set_transition_style', {'style': 2, 'me': 0})
    assert 'awaiting' in switching.dispatch_me_transition_style(c, {'me': 0, 'style': 2})[1]


def test_keyed_auto_requires_explicit_intent_and_does_not_change_ties(monkeypatch):
    c = _three_c_connection()
    c.mixerstate['transition-settings'][0].next_transition_key2 = True
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    payload = {'me': 0, 'expected_program': 1, 'expected_preview': 2,
               'expected_selection': {'background': True, 'key1': False, 'key2': True,
                                      'key3': False, 'key4': False}}
    assert 'explicit confirmation' in switching.dispatch_me_auto(c, payload)[1]
    assert switching.dispatch_me_auto(c, {**payload, 'allow_keyed': True}) == (True, None)
    assert sent == [('auto', {'me': 0})]
    assert c.mixerstate['transition-settings'][0].next_transition_key2 is True


def test_physical_output_route_checks_installation_topology_ownership_and_expected_route(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(virtual1={'outputs': [1], 'previewSource': 2, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    request = {'config_revision': 7, 'output_id': 3, 'mode': 'virtual_assign', 'group_id': 'virtual1',
               'expected_live': 2, 'input_source': 1}
    assert switching.dispatch_output_route(c, request, config)[0]
    assert sent == [('set_aux_output', {'aux_channel': 2, 'input_source': 1})]
    assert 'awaiting' in switching.dispatch_output_route(c, request, config)[1]

    c.mixerstate['topology'].aux_outputs = 5
    assert 'exactly six' in switching.dispatch_output_route(c, {**request, 'output_id': 4,
        'expected_live': 1}, config)[1]


def test_primary_output_release_routes_to_current_background_and_protects_last_destination(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 90010, 2: 2, 3: 1, 4: 2, 5: 1})
    config = _three_c_config()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    request = {'config_revision': 7, 'output_id': 1, 'mode': 'primary_release',
               'expected_live': 90010, 'input_source': 1}
    assert switching.dispatch_output_route(c, request, config)[0]
    assert sent == [('set_aux_output', {'aux_channel': 0, 'input_source': 1})]
    c.mixerstate['aux-output-source'][0].source = 1
    assert 'final Primary' in switching.dispatch_output_route(c, {**request, 'output_id': 2}, config)[1]


def test_virtual_group_cut_preflights_all_routes_then_dispatches_independently(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2})
    config = _three_c_config(virtual1={'outputs': [1, 2], 'previewSource': 2, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    payload = {'config_revision': 7, 'group_id': 'virtual1', 'input_source': 2}
    ok, result = switching.dispatch_virtual_group_cut(c, payload, config)
    assert ok
    assert result['previous'] == 1 and result['target'] == 2
    assert [item['ok'] for item in result['outcomes']] == [True, True]
    assert [data['aux_channel'] for _command, data in sent] == [1, 2]
    assert 'awaiting' in switching.dispatch_virtual_group_cut(c, payload, config)[1]


def test_mixed_virtual_group_alignment_requires_reviewed_routes_and_dispatches_per_output(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 1, 2: 2, 3: 1, 4: 2, 5: 1})
    config = _three_c_config(virtual1={'outputs': [1, 2], 'previewSource': 3, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    payload = {'config_revision': 7, 'group_id': 'virtual1', 'input_source': 1,
               'expected_routes': [{'channel': 1, 'source': 1}, {'channel': 2, 'source': 2}]}
    ok, result = switching.dispatch_virtual_group_align(c, payload, config)
    assert ok
    assert result['outcomes'] == [
        {'channel': 1, 'ok': True, 'no_op': True, 'error': None},
        {'channel': 2, 'ok': True, 'no_op': False, 'error': None},
    ]
    assert sent == [('set_aux_output', {'aux_channel': 2, 'input_source': 1})]

    c2 = _three_c_connection(routes={0: 90010, 1: 1, 2: 2, 3: 1, 4: 2, 5: 1})
    changed = {**payload, 'expected_routes': [{'channel': 1, 'source': 3}, {'channel': 2, 'source': 2}]}
    assert 'changed after' in switching.dispatch_virtual_group_align(c2, changed, config)[1]


def test_virtual_assignment_cannot_claim_primary_me_program_feed(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 1, 2: 2, 3: 1, 4: 2, 5: 1})
    config = _three_c_config()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    request = {'config_revision': 7, 'output_id': 2, 'mode': 'virtual_assign', 'group_id': 'virtual1',
               'expected_live': 1, 'input_source': 90010}
    ok, error = switching.dispatch_output_route(c, request, config)
    assert not ok and 'cannot claim the M/E Program feed' in error
    assert sent == []


def test_usk_toggle_is_key_specific_requires_raw_state_and_confirms_independently(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args[1:3]) or (True, None))
    payload = {'me': 0, 'key_index': 0, 'expected_on_air': False, 'target_on_air': True}
    assert switching.dispatch_usk_toggle(c, payload) == (True, None)
    assert sent == [('set_usk_on_air', {'me': 0, 'key_index': 0, 'enabled': True})]
    assert 'awaiting' in switching.dispatch_usk_toggle(c, payload)[1]
    assert switching.usk_toggle_readiness(c, 1)[0] is None
    c.mixerstate['key-on-air'][0][0].enabled = True
    assert switching.usk_toggle_readiness(c, 0) == (None, True)
    assert switching.dispatch_usk_toggle(c, {'me': 0, 'key_index': 0, 'expected_on_air': True,
                                             'target_on_air': False}) == (True, None)
    assert len(sent) == 2
    assert sent[1] == ('set_usk_on_air', {'me': 0, 'key_index': 0, 'enabled': False})
    c.mixerstate['key-on-air'][0][0].enabled = False
    assert switching.usk_toggle_readiness(c, 0) == (None, False)
    c.mixerstate['key-on-air'][0].pop(1)
    assert 'not been observed' in switching.dispatch_usk_toggle(
        c, {'me': 0, 'key_index': 1, 'expected_on_air': False, 'target_on_air': True})[1]


def test_dsk_toggle_uses_discovered_state_and_requires_stable_keyer(monkeypatch):
    c = FakeConnection()
    c.mixerstate['topology'].downstream_keyers = 2
    c.mixerstate['dkey-state'] = {
        0: NS(on_air=False, is_transitioning=False, is_autotransitioning=False),
        1: NS(on_air=False, is_transitioning=False, is_autotransitioning=False),
    }
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args[1:3]) or (True, None))
    on = {'dsk': 0, 'expected_on_air': False, 'target_on_air': True}

    assert switching.dispatch_dsk_toggle(c, on) == (True, None)
    assert sent == [('set_dsk_on_air', {'dsk': 0, 'enabled': True})]
    assert 'awaiting' in switching.dispatch_dsk_toggle(c, on)[1]
    c.mixerstate['dkey-state'][0].on_air = True
    assert switching.dsk_toggle_readiness(c, 0) == (None, True)
    off = {'dsk': 0, 'expected_on_air': True, 'target_on_air': False}
    assert switching.dispatch_dsk_toggle(c, off) == (True, None)
    assert sent[-1] == ('set_dsk_on_air', {'dsk': 0, 'enabled': False})

    c.mixerstate['dkey-state'][0].is_transitioning = True
    assert 'transitioning' in switching.dispatch_dsk_toggle(
        c, {'dsk': 0, 'expected_on_air': False, 'target_on_air': True})[1]
    assert len(sent) == 2


def test_consumer_uses_guarded_dsk_dispatch(monkeypatch):
    c = FakeConnection()
    c.mixerstate['topology'].downstream_keyers = 1
    c.mixerstate['dkey-state'] = {
        0: NS(on_air=False, is_transitioning=False, is_autotransitioning=False),
    }
    calls = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: calls.append(args[1]) or (True, None))
    consumer = ATEMConsumer.__new__(ATEMConsumer)
    consumer.connection = c
    consumer.sent = []
    consumer._record_atem_command = lambda *args: None

    async def send_json(data):
        consumer.sent.append(data)

    consumer.send_json = send_json
    payload = {'dsk': 0, 'expected_on_air': False, 'target_on_air': True}
    asyncio.run(consumer.execute_command('dashboard_toggle_dsk', payload))
    asyncio.run(consumer.execute_command('dashboard_toggle_dsk', payload))
    assert calls == ['set_dsk_on_air']
    assert 'awaiting' in consumer.sent[-1]['message']
    assert consumer.sent[-1]['dsk'] == 0


def test_dsk_toggle_uses_existing_atemwire_absolute_command_packet():
    c = FakeConnection()
    sent = []
    c.send = sent.append

    assert dispatch_command(c, 'set_dsk_on_air', {'dsk': 1, 'enabled': False}) == (True, None)
    assert len(sent) == 1
    assert type(sent[0]).__name__ == 'DkeyOnairCommand'
    assert (sent[0].index, sent[0].on_air) == (1, False)


def test_usk_snapshot_and_uncertain_review_use_observed_key_state(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args[1]) or (True, None))
    assert switching.safety_snapshot(c)['usk']['0'] == {'reason': None, 'onAir': False}
    assert switching.dispatch_usk_toggle(c, {'key_index': 0, 'expected_on_air': False,
                                             'target_on_air': True})[0]
    switching._operations[c][('usk', 0)]['since'] -= switching.PENDING_SECONDS + 1
    assert 'unconfirmed' in switching.safety_snapshot(c)['usk']['0']['reason']
    assert switching.review_unconfirmed(c, 'usk', 0) == (True, None)
    assert switching.safety_snapshot(c)['usk']['0'] == {'reason': None, 'onAir': False}
    assert sent == ['set_usk_on_air']
    c.mixerstate['key-on-air'][0][0].enabled = None
    assert switching.safety_snapshot(c)['usk']['0']['onAir'] is None


def test_absolute_usk_command_uses_existing_atemwire_packet_without_hardware():
    c = FakeConnection()
    sent = []
    c.send = sent.append
    assert dispatch_command(c, 'set_usk_on_air',
                            {'me': 0, 'key_index': 0, 'enabled': False}) == (True, None)
    assert len(sent) == 1
    assert type(sent[0]).__name__ == 'KeyOnAirCommand'
    assert (sent[0].index, sent[0].keyer, sent[0].enabled) == (0, 0, False)


def test_linked_me_cut_dispatches_once_and_suppresses_repeat(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args[1:3]) or (True, None))
    assert switching.dispatch_me_cut(c, _me_payload()) == (True, None)
    assert sent == [('cut', {'me': 0})]
    assert 'awaiting' in switching.dispatch_me_cut(c, _me_payload())[1]
    c.mixerstate['program-bus-input'][0].source = 2
    c.mixerstate['preview-bus-input'][0].source = 1
    assert switching.me_cut_readiness(c)[0] is None
    assert sent == [('cut', {'me': 0})]


def test_unconfirmed_me_cut_requires_explicit_read_only_review(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    assert switching.dispatch_me_cut(c, _me_payload())[0]
    switching._operations[c][('me', 0)]['since'] -= switching.PENDING_SECONDS + 1
    assert 'unconfirmed' in switching.me_cut_readiness(c)[0]
    assert 'unconfirmed' in switching.dispatch_me_cut(c, _me_payload())[1]
    assert switching.review_unconfirmed(c, 'me') == (True, None)
    assert switching.me_cut_readiness(c)[0] is None
    assert len(sent) == 1  # review never retransmits a command


@pytest.mark.parametrize('target,expected,mutation,reason', [
    (None, 1, None, 'valid'),
    (3, 1, None, 'not directly routable'),
    (1, 1, None, 'already live'),
    (2, 7, None, 'changed'),
    (2, 1, lambda mx: mx.pop('aux-output-source'), 'not been observed'),
    (2, 1, lambda mx: setattr(mx['topology'], 'aux_outputs', 2), 'not confirmed'),
])
def test_aux_cut_rejects_invalid_queue_destination_or_stale_baseline(monkeypatch, target, expected, mutation, reason):
    c = FakeConnection()
    if mutation:
        mutation(c.mixerstate)
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    ok, error = switching.dispatch_aux_cut(c, {'aux_channel': 2, 'input_source': target,
                                               'expected_live': expected})
    assert not ok and reason in error and not sent


def test_aux_cut_uses_existing_dispatch_once_and_waits_for_observed_route(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args[1:3]) or (True, None))
    payload = {'aux_channel': 2, 'input_source': 2, 'expected_live': 1}
    assert switching.dispatch_aux_cut(c, payload) == (True, None)
    assert sent == [('set_aux_output', {'aux_channel': 2, 'input_source': 2})]
    assert 'awaiting' in switching.dispatch_aux_cut(c, payload)[1]
    c.mixerstate['aux-output-source'][2].source = 2
    assert switching.aux_cut_readiness(c, 2)[0] is None
    assert len(sent) == 1


def test_consumer_rechecks_at_command_boundary_and_keeps_stock_verbs(monkeypatch):
    c = FakeConnection()
    calls = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: calls.append(args[1]) or (True, None))
    consumer = ATEMConsumer.__new__(ATEMConsumer)
    consumer.connection = c
    consumer.sent = []
    consumer._record_atem_command = lambda *args: None

    async def send_json(data):
        consumer.sent.append(data)
    consumer.send_json = send_json
    asyncio.run(consumer.execute_command('dashboard_cut_me', _me_payload()))
    assert calls == ['cut']
    asyncio.run(consumer.execute_command('dashboard_cut_me', _me_payload()))
    assert calls == ['cut']
    assert 'awaiting' in consumer.sent[-1]['message']


def test_consumer_uses_guarded_usk_dispatch(monkeypatch):
    c = FakeConnection()
    calls = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: calls.append(args[1]) or (True, None))
    consumer = ATEMConsumer.__new__(ATEMConsumer)
    consumer.connection = c
    consumer.sent = []
    consumer._record_atem_command = lambda *args: None

    async def send_json(data):
        consumer.sent.append(data)

    consumer.send_json = send_json
    payload = {'me': 0, 'key_index': 0, 'expected_on_air': False, 'target_on_air': True}
    asyncio.run(consumer.execute_command('dashboard_toggle_usk', payload))
    asyncio.run(consumer.execute_command('dashboard_toggle_usk', payload))
    assert calls == ['set_usk_on_air']
    assert 'awaiting' in consumer.sent[-1]['message']
    assert consumer.sent[-1]['key_index'] == 0


def test_consumer_review_clears_only_unconfirmed_guard_without_hardware_write(monkeypatch):
    c = FakeConnection()
    calls = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: calls.append(args[1]) or (True, None))
    consumer = ATEMConsumer.__new__(ATEMConsumer)
    consumer.connection = c
    consumer.sent = []
    consumer._record_atem_command = lambda *args: None

    async def send_json(data):
        consumer.sent.append(data)

    async def send_current_state():
        consumer.sent.append({'type': 'atem_state'})

    consumer.send_json = send_json
    consumer.send_current_state = send_current_state
    assert switching.dispatch_aux_cut(c, {'aux_channel': 2, 'input_source': 2, 'expected_live': 1})[0]
    switching._operations[c][('aux', 2)]['since'] -= switching.PENDING_SECONDS + 1
    asyncio.run(consumer.execute_command('dashboard_review_aux', {'aux_channel': 2}))
    assert consumer.sent[0]['type'] == 'dashboard_reviewed'
    assert consumer.sent[1]['type'] == 'atem_state'
    assert calls == ['set_aux_output']
    assert switching.aux_cut_readiness(c, 2)[0] is None


def test_actual_dashboard_javascript_behavior():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable for the behavioral dashboard test')
    script = Path(__file__).parents[1] / 'js' / 'production_dashboard_m21.test.cjs'
    result = subprocess.run([node, '--test', str(script)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_alpine_keyer_button_dom_with_offline_browser(tmp_path):
    """Optional real-Alpine DOM regression; fake WebSocket cannot reach ATEM."""
    if os.environ.get('ATEM_RUN_OFFLINE_BROWSER_TEST') != '1':
        pytest.skip('Set ATEM_RUN_OFFLINE_BROWSER_TEST=1 for local headless Edge')
    edge = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    if not edge.exists():
        pytest.skip('Microsoft Edge is unavailable')
    fixture = Path(__file__).parents[1] / 'js' / 'production_dashboard_alpine_dom.html'
    result = subprocess.run([
        str(edge), '--headless', '--disable-gpu', '--no-first-run',
        f'--user-data-dir={tmp_path / "edge-profile"}', '--virtual-time-budget=2500',
        '--dump-dom', fixture.as_uri(),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    match = re.search(r'<output id="result">(.*?)</output>', result.stdout, re.DOTALL)
    assert match and match.group(1) != 'waiting', result.stdout[-2000:]
    observed = json.loads(html.unescape(match.group(1)))
    assert observed['blockedClickSentNoCommand'] is True
    assert observed['enabledAfterOn'] is True
    assert observed['observedAtClick']['disabled'] is False
    assert observed['observedAtClick']['ariaDisabled'] is None
    assert observed['observedAtClick']['background'] == 'rgb(214, 39, 24)'
    assert [command['target_on_air'] for command in observed['commands']] == [True, False]


@pytest.mark.django_db
def test_rendered_dashboard_keeps_live_program_visible_and_cut_reasons(client):
    html = client.get('/atem/dashboard/').content.decode('utf-8')
    assert 'Observed M/E Program' in html
    assert 'Observed M/E Preview' in html
    assert 'outputSourceId(output)' in html
    assert 'outputStatus(output)' in html
    assert 'MIXED ROUTING' in html
    assert 'CUT ALL OUTPUTS' not in html
