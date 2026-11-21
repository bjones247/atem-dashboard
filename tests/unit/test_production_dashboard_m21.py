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
from atem_control.control import dashboard_config
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
    c.mixerstate['device-identity'] = NS(device_id='a' * 32)
    c.mixerstate['topology'] = NS(aux_outputs=6, downstream_keyers=2, dves=1, stingers=1)
    c.mixerstate['transition-settings'][0].style = 0
    c.mixerstate['input-properties'].update({
        1000: NS(name='Color Bars', short_name='Bars', port_type=2,
                 available_aux=True, available_me1=False),
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


def _take_all_request(action='cut'):
    return {'device_id': 'a' * 32, 'config_revision': 7, 'primary_action': action,
            'expected_program': 1, 'expected_preview': 2,
            'expected_selection': {'background': True, 'key1': False, 'key2': False,
                                   'key3': False, 'key4': False},
            'allow_keyed': False,
            'groups': {'virtual1': {'live': 1, 'preview': 2},
                       'virtual2': {'live': 2, 'preview': 1}}}


def test_assignment_dialog_layout_and_hidden_cut_feedback():
    template = (Path(__file__).resolve().parents[2] / 'atem_control' / 'templates' / 'dashboard.html').read_text()
    assert 'grid-template-columns: 4.5rem 5rem minmax(9rem, 1fr) 7rem' in template
    assert '<span>SELECT</span><span>Output</span><span>Current Output Source</span><span>Switcher</span>' in template
    assert "other: 'Unswitched'" in template
    dialog = template[template.index('aria-label="Change output assignments"'):]
    assert dialog.index('>Save</button>') < dialog.index('>Cancel</button>')
    assert 'Review TAKE ALL results' not in template
    assert '.production-dashboard .cut-feedback-hidden { display: none !important; }' in template
    assert template.count('class="cut-reason cut-feedback-hidden') == 3
    assert 'class="cut-feedback-hidden text-warning" role="status"' in template
    assert template.count('class="cut-feedback-hidden basis-full text-[10px] text-warning"') == 2
    assert ':title="assignmentChangeReason() ||' in template
    assert ':title="takeAllReason() ||' in template


def _key_only_auto_payload():
    return {'me': 0, 'expected_program': 1, 'expected_preview': 2,
            'expected_selection': {'background': False, 'key1': True, 'key2': False,
                                   'key3': False, 'key4': False},
            'expected_key_states': {'0': False}, 'allow_keyed': True,
            'expected_style': 0}


def test_key_only_auto_confirms_from_observed_key_state_and_transition_rest(monkeypatch):
    c = FakeConnection()
    c.mixerstate['transition-settings'][0].style = 0
    c.mixerstate['transition-settings'][0].next_transition_bkgd = False
    c.mixerstate['transition-settings'][0].next_transition_key1 = True
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))

    assert switching.dispatch_me_auto(c, _key_only_auto_payload()) == (True, None)
    assert sent == ['auto']
    operation = switching._operations[c][('me', 0)]
    assert operation['key_targets'] == {'0': True}
    # A key-on observation while the M/E transition is still running is not
    # enough to confirm completion.
    c.mixerstate['key-on-air'][0][0].enabled = True
    c.mixerstate['transition-position'][0].in_transition = True
    reason, _state = switching.me_auto_readiness(c, _key_only_auto_payload())
    assert 'active or not at rest' in reason
    assert ('me', 0) in switching._operations.get(c, {})

    c.mixerstate['transition-position'][0].in_transition = False
    reason, _state = switching.me_auto_readiness(c, _key_only_auto_payload())
    assert 'keyer state changed' in reason  # the prior AUTO was confirmed and its guard cleared
    assert ('me', 0) not in switching._operations.get(c, {})
    assert sent == ['auto']


def test_key_only_auto_requires_observed_key_state_and_times_out_unconfirmed(monkeypatch):
    c = FakeConnection()
    c.mixerstate['transition-settings'][0].style = 0
    c.mixerstate['transition-settings'][0].next_transition_bkgd = False
    c.mixerstate['transition-settings'][0].next_transition_key1 = True
    c.mixerstate['key-on-air'][0][0].enabled = None
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    assert 'on-air state is unknown' in switching.dispatch_me_auto(c, _key_only_auto_payload())[1]
    assert sent == []

    c.mixerstate['key-on-air'][0][0].enabled = False
    assert switching.dispatch_me_auto(c, _key_only_auto_payload()) == (True, None)
    switching._operations[c][('me', 0)]['since'] -= switching.PENDING_SECONDS + 1
    reason, _state = switching.me_auto_readiness(c, _key_only_auto_payload())
    assert 'Key-only AUTO is unconfirmed' in reason
    assert ('me', 0) in switching._operations.get(c, {})
    assert len(sent) == 1


def test_background_auto_keeps_program_source_confirmation(monkeypatch):
    c = FakeConnection()
    c.mixerstate['transition-settings'][0].style = 0
    payload = {'me': 0, 'expected_program': 1, 'expected_preview': 2,
               'expected_selection': {'background': True, 'key1': False, 'key2': False,
                                      'key3': False, 'key4': False},
               'allow_keyed': False, 'expected_style': 0}
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))

    assert switching.dispatch_me_auto(c, payload) == (True, None)
    assert sent == ['auto']
    assert switching._operations[c][('me', 0)]['key_targets'] is None
    c.mixerstate['program-bus-input'][0].source = 2
    c.mixerstate['preview-bus-input'][0].source = 1
    assert switching.me_auto_readiness(c, {**payload, 'expected_program': 2, 'expected_preview': 1})[0] is None
    assert ('me', 0) not in switching._operations.get(c, {})


def test_take_all_rejects_legacy_auto_requests_without_writes(monkeypatch):
    c = _three_c_connection()
    c.mixerstate['transition-settings'][0].style = 0
    c.mixerstate['transition-settings'][0].next_transition_bkgd = False
    c.mixerstate['transition-settings'][0].next_transition_key1 = True
    config = _three_c_config()
    request = _take_all_request('auto')
    request.update({
        'expected_selection': {'background': False, 'key1': True, 'key2': False,
                               'key3': False, 'key4': False},
        'expected_key_states': {'0': False}, 'allow_keyed': True,
    })
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))

    ok, result = switching.dispatch_take_all(c, request, config)

    assert not ok
    assert 'CUT only' in result
    assert sent == []


def test_take_all_dispatches_primary_and_both_virtual_groups_once(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(
        virtual1={'outputs': [1], 'previewSource': 2, 'programTarget': 1},
        virtual2={'outputs': [2], 'previewSource': 1, 'programTarget': 2})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))

    ok, result = switching.dispatch_take_all(c, _take_all_request(), config)

    assert ok
    assert result['primary']['command'] == 'cut'
    assert result['virtual']['virtual1']['status'] == 'pending'
    assert result['virtual']['virtual2']['status'] == 'pending'
    assert [(command, data.get('aux_channel')) for command, data in sent] == [
        ('cut', None), ('set_aux_output', 1), ('set_aux_output', 2)]


def test_take_all_skips_already_live_participants_and_requires_one_change(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(
        virtual1={'outputs': [1], 'previewSource': 1, 'programTarget': 1},
        virtual2={'outputs': [2], 'previewSource': 1, 'programTarget': 2})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))

    request = _take_all_request()
    request['groups']['virtual1']['preview'] = 1
    ok, result = switching.dispatch_take_all(c, request, config)
    assert ok
    assert result['virtual']['virtual1']['status'] == 'skipped'
    assert [(command, data.get('aux_channel')) for command, data in sent] == [
        ('cut', None), ('set_aux_output', 2)]

    c = _three_c_connection()
    c.mixerstate['preview-bus-input'][0].source = 1
    request = {**request, 'expected_preview': 1}
    sent.clear()
    ok, result = switching.dispatch_take_all(c, request, config)
    assert ok
    assert result['primary']['status'] == 'skipped'
    assert [(command, data.get('aux_channel')) for command, data in sent] == [('set_aux_output', 2)]

    c = _three_c_connection()
    c.mixerstate['preview-bus-input'][0].source = 1
    config['config']['virtualSwitchers']['virtual2']['previewSource'] = 2
    request['groups']['virtual2']['preview'] = 2
    sent.clear()
    ok, reason = switching.dispatch_take_all(c, request, config)
    assert not ok and 'already live on every switcher' in reason
    assert sent == []


def test_config_save_reconciles_confirmed_take_all_routes_before_blocking():
    c = _three_c_connection()
    switching._record(c, ('aux', 1), 1, 2)
    switching._record(c, ('aux', 2), 2, 1)
    assert switching.configuration_update_block_reason(c)

    c.mixerstate['aux-output-source'][1].source = 2
    assert switching.configuration_update_block_reason(c)
    assert ('aux', 1) not in switching._operations[c]

    c.mixerstate['aux-output-source'][2].source = 1
    assert switching.configuration_update_block_reason(c) is None
    assert not any(key[0] == 'aux' for key in switching._operations[c])


def test_take_all_consumer_uses_guarded_dispatch_and_returns_per_switcher_results(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config()
    calls = []
    outcome = {'device_id': 'a' * 32, 'primary': {'ok': True, 'command': 'cut'},
               'virtual': {'virtual1': {'status': 'skipped', 'outcomes': []},
                           'virtual2': {'status': 'skipped', 'outcomes': []}}}
    monkeypatch.setattr(switching, 'dispatch_take_all',
                        lambda *args, **kwargs: calls.append((args[1], kwargs)) or (True, outcome))
    consumer = ATEMConsumer.__new__(ATEMConsumer)
    consumer.connection = c
    consumer.sent = []
    consumer._record_atem_command = lambda *args: None

    async def ensure_config(force_reload=False):
        assert force_reload
        return config

    async def send_json(data):
        consumer.sent.append(data)
    consumer._ensure_dashboard_config = ensure_config
    consumer.send_json = send_json
    asyncio.run(consumer.execute_command('dashboard_take_all', _take_all_request()))

    assert calls and calls[0][1] == {'require_current_revision': True}
    assert consumer.sent == [{'type': 'dashboard_take_all_started', **outcome}]


def test_take_all_consumer_reports_virtual_cuts_when_primary_is_skipped(monkeypatch):
    c = _three_c_connection()
    c.mixerstate['preview-bus-input'][0].source = 1
    config = _three_c_config(
        virtual1={'outputs': [1], 'previewSource': 2, 'programTarget': 1},
        virtual2={'outputs': [2], 'previewSource': 1, 'programTarget': 2})
    request = {**_take_all_request(), 'expected_preview': 1}
    dispatched = []
    monkeypatch.setattr(dashboard_config, 'get_config_for_connection', lambda _connection: config)
    monkeypatch.setattr(switching, 'dispatch',
                        lambda _connection, command, payload: dispatched.append((command, payload)) or (True, None))
    consumer = ATEMConsumer.__new__(ATEMConsumer)
    consumer.connection = c
    consumer.sent = []
    logged = []
    consumer._record_atem_command = lambda command, payload: logged.append((command, payload))

    async def ensure_config(force_reload=False):
        assert force_reload
        return config

    async def send_json(data):
        consumer.sent.append(data)

    consumer._ensure_dashboard_config = ensure_config
    consumer.send_json = send_json
    asyncio.run(consumer.execute_command('dashboard_take_all', request))

    assert [command for command, _payload in dispatched] == ['set_aux_output', 'set_aux_output']
    assert [command for command, _payload in logged] == ['set_aux_output', 'set_aux_output']
    assert [payload['input_source'] for _command, payload in logged] == [2, 1]
    assert len(consumer.sent) == 1
    response = consumer.sent[0]
    assert response['type'] == 'dashboard_take_all_started'
    assert response['primary']['status'] == 'skipped'
    assert response['virtual']['virtual1']['status'] == 'pending'
    assert response['virtual']['virtual2']['status'] == 'pending'


def test_take_all_uses_cut_with_a_non_cut_style_and_skips_empty_groups(monkeypatch):
    c = _three_c_connection()
    c.mixerstate['transition-settings'][0].style = 2
    config = _three_c_config(virtual1={'outputs': [], 'previewSource': 2, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))

    ok, result = switching.dispatch_take_all(c, _take_all_request(), config)

    assert ok
    assert result['primary']['command'] == 'cut'
    assert result['virtual']['virtual1']['status'] == 'skipped'
    assert result['virtual']['virtual2']['status'] == 'skipped'
    assert sent == ['cut']


def test_take_all_dispatches_after_the_requested_primary_preview_is_observed(monkeypatch):
    c = _three_c_connection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))
    assert switching.dispatch_me_preview(c, {'me': 0, 'source': 3, 'expected_preview': 2}) == (True, None)
    c.mixerstate['preview-bus-input'][0].source = 3

    ok, result = switching.dispatch_take_all(c, {**_take_all_request(), 'expected_preview': 3}, _three_c_config())

    assert ok, result
    assert result['primary']['target'] == 3
    assert sent == ['set_preview', 'cut']


def test_take_all_exposes_an_unconfirmed_preview_until_read_only_review(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))
    assert switching.dispatch_me_preview(c, {'me': 0, 'source': 3, 'expected_preview': 2})[0]
    [pending] = switching.safety_snapshot(c)['takeAllBlockers']
    assert pending['label'] == 'M/E Preview'
    assert pending['reviewable'] is False

    switching._operations[c][('me_preview', 0)]['since'] -= switching.PENDING_SECONDS + 1
    [unconfirmed] = switching.safety_snapshot(c)['takeAllBlockers']
    assert unconfirmed['reviewable'] is True
    assert switching.dispatch_take_all(c, _take_all_request(), config) == (False, unconfirmed['message'])
    assert sent == ['set_preview']

    assert switching.review_unconfirmed(c, 'me_preview') == (True, None)
    assert switching.safety_snapshot(c)['takeAllBlockers'] == []
    assert sent == ['set_preview']
    assert switching.dispatch_take_all(c, _take_all_request(), config)[0]
    assert sent == ['set_preview', 'cut']


def test_take_all_waits_for_a_pending_downstream_keyer_to_finish_transitioning(monkeypatch):
    c = _three_c_connection()
    dsk = NS(on_air=True, is_transitioning=True, is_autotransitioning=False)
    c.mixerstate['dkey-state'] = {0: dsk}
    switching._record(c, ('dsk', 0), False, True)
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append(command) or (True, None))
    ok, reason = switching.dispatch_take_all(c, _take_all_request(), _three_c_config())
    assert not ok and 'Downstream keyer 1' in reason
    assert sent == []

    dsk.is_transitioning = False
    assert switching.dispatch_take_all(c, _take_all_request(), _three_c_config())[0]
    assert sent == ['cut']


def test_take_all_empty_group_is_skipped_even_when_its_saved_queue_is_unavailable(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(
        virtual1={'outputs': [], 'previewSource': 3, 'programTarget': 1},
        virtual2={'outputs': [2], 'previewSource': 1, 'programTarget': 2})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))

    ok, result = switching.dispatch_take_all(c, _take_all_request(), config)

    assert ok
    assert result['virtual']['virtual1']['status'] == 'skipped'
    assert result['virtual']['virtual2']['status'] == 'pending'
    assert [(command, data.get('aux_channel')) for command, data in sent] == [
        ('cut', None), ('set_aux_output', 2)]


@pytest.mark.parametrize('mutate, message', [
    (lambda c, config, request: setattr(c.mixerstate['topology'], 'aux_outputs', 5), 'six-AUX'),
    (lambda c, config, request: config['config']['virtualSwitchers']['virtual1'].update({'outputs': [1], 'previewSource': 3}), 'conflicted'),
    (lambda c, config, request: (config['config']['virtualSwitchers']['virtual1'].update({'outputs': [1]}), config['config']['virtualSwitchers']['virtual2'].update({'outputs': [1]})), 'conflicted'),
    (lambda c, config, request: request.update({'config_revision': 6}), 'revision'),
    (lambda c, config, request: setattr(c.protocol.transport, 'last_rx_monotonic', time.monotonic() - switching.MAX_RX_AGE - 1), 'stale'),
    (lambda c, config, request: (setattr(c.mixerstate['transition-settings'][0], 'next_transition_key1', True), request['expected_selection'].update({'key1': True})), 'KEY 1'),
    (lambda c, config, request: setattr(c.mixerstate['transition-position'][0], 'in_transition', True), 'in progress'),
    (lambda c, config, request: switching._operations.setdefault(c, {}).update({('aux', 1): {'before': 1, 'target': 2, 'since': time.monotonic(), 'uncertain': False}}), 'pending or unconfirmed'),
])
def test_take_all_preflight_failure_dispatches_nothing(monkeypatch, mutate, message):
    c = _three_c_connection()
    config = _three_c_config(
        virtual1={'outputs': [1], 'previewSource': 2, 'programTarget': 1},
        virtual2={'outputs': [2], 'previewSource': 1, 'programTarget': 2})
    request = _take_all_request()
    mutate(c, config, request)
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))

    ok, reason = switching.dispatch_take_all(c, request, config)

    assert not ok and message.lower() in reason.lower()
    assert sent == []


def test_take_all_reports_independent_partial_virtual_failures_without_retry(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(
        virtual1={'outputs': [1], 'previewSource': 2, 'programTarget': 1},
        virtual2={'outputs': [2], 'previewSource': 1, 'programTarget': 2})
    sent = []
    def dispatch(_connection, command, data):
        sent.append((command, data))
        if command == 'set_aux_output' and data['aux_channel'] == 2:
            return False, 'simulated offline dispatch failure'
        return True, None
    monkeypatch.setattr(switching, 'dispatch', dispatch)

    ok, result = switching.dispatch_take_all(c, _take_all_request(), config)

    assert ok
    assert result['primary']['ok'] is True
    assert result['virtual']['virtual1']['status'] == 'pending'
    assert result['virtual']['virtual2']['status'] == 'partial'
    assert len(sent) == 3


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


@pytest.mark.django_db
def test_route_dispatch_rechecks_config_revision_and_blocks_config_edits_until_route_confirmation(monkeypatch):
    c = _three_c_connection()
    initial = dashboard_config.get_config_for_connection(c)
    config = initial['config']
    config['virtualSwitchers']['virtual1'].update({'outputs': [], 'previewSource': 2, 'programTarget': 1})
    current = dashboard_config.update_config_for_connection(c, initial['revision'], config)
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    request = {'config_revision': initial['revision'], 'output_id': 3, 'mode': 'virtual_assign',
               'group_id': 'virtual1', 'expected_live': 2, 'input_source': 1}
    ok, error = switching.dispatch_output_route(c, request, current, require_current_revision=True)
    assert not ok and 'configuration changed' in error.lower()
    assert sent == []

    request.update({'config_revision': current['revision'], 'expected_live': 2, 'input_source': 1})
    # OUT 3 currently carries IN 2; this explicitly assigns it to the
    # group's current Program target, IN 1.
    ok, _route = switching.dispatch_output_route(c, request, current, require_current_revision=True)
    assert ok
    assert sent == [('set_aux_output', {'aux_channel': 2, 'input_source': 1})]

    proposed = {**config, 'customNames': {**config['customNames'], 'virtual1': 'Other session'}}
    with pytest.raises(dashboard_config.DashboardConfigError, match='route is pending or unconfirmed'):
        dashboard_config.update_config_for_connection(c, current['revision'], proposed)

    c.mixerstate['aux-output-source'][2].source = 1
    assert switching.aux_cut_readiness(c, 2)[0] is None
    saved = dashboard_config.update_config_for_connection(c, current['revision'], proposed)
    assert saved['config']['customNames']['virtual1'] == 'Other session'


def test_primary_output_release_routes_to_verified_bars_and_protects_last_destination(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 90010, 2: 2, 3: 1, 4: 2, 5: 1})
    config = _three_c_config()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    request = {'config_revision': 7, 'output_id': 1, 'mode': 'primary_release',
               'expected_live': 90010, 'input_source': 1000}
    c.mixerstate['input-properties'][1000].available_aux = False
    assert 'Color Bars' in switching.dispatch_output_route(c, {**request, 'input_source': 1}, config)[1]
    assert sent == []
    c.mixerstate['input-properties'][1000].available_aux = True
    assert switching.dispatch_output_route(c, request, config)[0]
    assert sent == [('set_aux_output', {'aux_channel': 0, 'input_source': 1000})]
    c.mixerstate['aux-output-source'][0].source = 1000
    assert 'final Primary' in switching.dispatch_output_route(c, {**request, 'output_id': 2}, config)[1]


@pytest.mark.django_db
def test_primary_reconciliation_preserves_routes_and_unblocks_first_virtual_assignment(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 90010, 2: 90010, 3: 90010, 4: 2, 5: 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    initial = dashboard_config.get_config_for_connection(c)
    old = _three_c_config(virtual1={'outputs': [1, 2, 3], 'previewSource': 2, 'programTarget': 1})['config']
    snapshot = dashboard_config.update_config(initial['deviceId'], initial['revision'], old)
    saved, retired = dashboard_config.reconcile_primary_assignments(c, snapshot)
    assert retired == [2, 3, 4]
    assert saved['config']['virtualSwitchers']['virtual1'] == {
        'outputs': [], 'previewSource': 2, 'programTarget': 1,
    }
    assert dashboard_config.reconcile_primary_assignments(c, saved) is None
    request = {'config_revision': saved['revision'], 'output_id': 6, 'mode': 'virtual_assign',
               'group_id': 'virtual2', 'expected_live': 1, 'input_source': 1}
    assert switching.dispatch_output_route(c, request, saved)[1]['no_op']
    proposed = saved['config']
    proposed['virtualSwitchers']['virtual2'].update(outputs=[5], programTarget=1)
    dashboard_config.update_config_for_connection(c, saved['revision'], proposed)
    assert sent == []
    assert c.mixerstate['aux-output-source'][2].source == 90010


@pytest.mark.django_db
def test_primary_reconciliation_remembers_takeover_through_pending_route(monkeypatch):
    c = _three_c_connection()
    initial = dashboard_config.get_config_for_connection(c)
    config = _three_c_config(virtual1={'outputs': [2], 'previewSource': 3, 'programTarget': 2})['config']
    snapshot = dashboard_config.update_config(initial['deviceId'], initial['revision'], config)
    monkeypatch.setattr(switching, 'dispatch', lambda *args: (True, None))
    request = {'config_revision': snapshot['revision'], 'output_id': 6, 'mode': 'other_route',
               'expected_live': 1, 'input_source': 2}
    assert switching.dispatch_output_route(c, request, snapshot)[0]
    c.mixerstate['aux-output-source'][2].source = 90010
    assert dashboard_config.reconcile_primary_assignments(c, snapshot) is None
    assert dashboard_config.pending_primary_retirements(c, snapshot) == {2}

    c.mixerstate['aux-output-source'][2].source = 2
    assert 'superseded virtual assignment' in switching.output_route_readiness(
        c, {**request, 'output_id': 3, 'expected_live': 2, 'input_source': 1}, snapshot)[0]
    c.mixerstate['aux-output-source'][5].source = 2
    switching.safety_snapshot(c)
    saved, retired = dashboard_config.reconcile_primary_assignments(c, snapshot)
    assert retired == [3]
    assert saved['config']['virtualSwitchers']['virtual1']['outputs'] == []
    assert dashboard_config.pending_primary_retirements(c, saved) == ()
    assert c.mixerstate['aux-output-source'][2].source == 2


def test_mixed_virtual_cut_uses_reviewed_routes_and_skips_an_output_already_on_target(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(virtual1={'outputs': [1, 2], 'previewSource': 2, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    request = {'config_revision': 7, 'group_id': 'virtual1', 'input_source': 2,
               'expected_routes': [{'channel': 1, 'source': 3}, {'channel': 2, 'source': 2}]}
    assert 'OUT 2 changed' in switching.dispatch_virtual_group_cut(c, request, config)[1]
    assert sent == []
    request['expected_routes'][0]['source'] = 1
    ok, result = switching.dispatch_virtual_group_cut(c, request, config)
    assert ok and result['previous'] is None
    assert [(item['before'], item.get('no_op', False)) for item in result['outcomes']] == [(1, False), (2, True)]
    assert sent == [('set_aux_output', {'aux_channel': 1, 'input_source': 2})]


def test_virtual_direct_routes_bars_without_using_or_overwriting_queued_preview(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(virtual1={'outputs': [1, 2], 'previewSource': 3, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    request = {'config_revision': 7, 'group_id': 'virtual1', 'input_source': 1000,
               'expected_routes': [{'channel': 1, 'source': 1}, {'channel': 2, 'source': 2}]}
    assert 'Queued Preview changed' in switching.dispatch_virtual_group_cut(c, request, config)[1]
    request['mode'] = 'direct'
    assert 'identity changed' in switching.dispatch_virtual_group_cut(c, request, config)[1]
    request['device_id'] = config['deviceId']
    c.mixerstate['input-properties'][1000].available_aux = False
    assert 'not directly routable' in switching.dispatch_virtual_group_cut(c, request, config)[1]
    c.mixerstate['input-properties'][1000].available_aux = True
    assert 'Primary M/E Program' in switching.dispatch_virtual_group_cut(c, {**request, 'input_source': 90010}, config)[1]
    assert sent == []

    ok, result = switching.dispatch_virtual_group_cut(c, request, config)
    assert ok and result['mode'] == 'direct'
    assert sent == [('set_aux_output', {'aux_channel': channel, 'input_source': 1000}) for channel in (1, 2)]
    assert config['config']['virtualSwitchers']['virtual1']['previewSource'] == 3
    assert 'awaiting hardware confirmation' in switching.dispatch_virtual_group_cut(c, request, config)[1]


def test_take_all_preflights_mixed_routes_before_sending_primary_cut(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config(virtual1={'outputs': [1, 2], 'previewSource': 2, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    payload = _take_all_request()
    payload['groups']['virtual1'] = {'preview': 2, 'routes': [{'channel': 1, 'source': 3}, {'channel': 2, 'source': 2}]}
    assert 'OUT 2 changed' in switching.dispatch_take_all(c, payload, config)[1]
    assert sent == []
    payload['groups']['virtual1']['routes'][0]['source'] = 1
    ok, result = switching.dispatch_take_all(c, payload, config)
    assert ok
    assert result['virtual']['virtual1']['previous'] is None
    assert [command for command, _ in sent] == ['cut', 'set_aux_output']


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
    assert ('aux', 2) not in switching._operations.get(c, {})
    assert len(sent) == 1


def test_unconfirmed_aux_route_with_original_source_requires_read_only_review(monkeypatch):
    c = FakeConnection()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda *args: sent.append(args) or (True, None))
    payload = {'aux_channel': 2, 'input_source': 2, 'expected_live': 1}

    assert switching.dispatch_aux_cut(c, payload) == (True, None)
    switching._operations[c][('aux', 2)]['since'] -= switching.PENDING_SECONDS + 1
    assert 'unconfirmed' in switching.aux_cut_readiness(c, 2)[0]
    assert 'unconfirmed' in switching.dispatch_aux_cut(c, payload)[1]
    assert switching.review_unconfirmed(c, 'aux', 2) == (True, None)
    assert ('aux', 2) not in switching._operations.get(c, {})
    assert len(sent) == 1  # read-only review does not retry the route command


def test_unexpected_aux_route_stays_guarded_across_dashboard_sessions(monkeypatch):
    c = _three_c_connection()
    config = _three_c_config()
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    first = {'config_revision': 7, 'output_id': 3, 'mode': 'other_route',
             'expected_live': 2, 'input_source': 1}

    assert switching.dispatch_output_route(c, first, config)[0]
    # An external controller selects a third source before the original
    # request is confirmed. A second dashboard session observes that route.
    c.mixerstate['input-properties'][3] = NS(available_aux=True, available_me1=True)
    c.mixerstate['aux-output-source'][2].source = 3
    second = {**first, 'expected_live': 3, 'input_source': 2}
    ok, reason = switching.dispatch_output_route(c, second, config)

    assert not ok and 'unconfirmed' in reason.lower()
    assert 'review current hardware state' in reason.lower()
    assert len(sent) == 1  # the competing session cannot dispatch
    assert switching.configuration_update_block_reason(c)

    # Explicit read-only review releases the guard but does not issue a write.
    switching._operations[c][('aux', 2)]['since'] -= switching.PENDING_SECONDS + 1
    assert switching.review_unconfirmed(c, 'aux', 2) == (True, None)
    assert switching.configuration_update_block_reason(c) is None
    assert len(sent) == 1


def test_multi_output_unexpected_route_keeps_only_that_output_guarded(monkeypatch):
    c = _three_c_connection(routes={0: 90010, 1: 1, 2: 1, 3: 1, 4: 2, 5: 1})
    config = _three_c_config(virtual1={'outputs': [1, 2], 'previewSource': 2, 'programTarget': 1})
    sent = []
    monkeypatch.setattr(switching, 'dispatch', lambda _c, command, data: sent.append((command, data)) or (True, None))
    payload = {'config_revision': 7, 'group_id': 'virtual1', 'input_source': 2}

    ok, result = switching.dispatch_virtual_group_cut(c, payload, config)
    assert ok and len(result['outcomes']) == 2
    assert [item['channel'] for item in result['outcomes']] == [1, 2]

    c.mixerstate['input-properties'][3] = NS(available_aux=True, available_me1=True)
    c.mixerstate['aux-output-source'][1].source = 3  # OUT 2 diverges unexpectedly
    c.mixerstate['aux-output-source'][2].source = 2  # OUT 3 confirms its target
    assert 'unconfirmed' in switching.aux_cut_readiness(c, 1)[0].lower()
    assert switching.aux_cut_readiness(c, 2)[0] is None
    operations = switching._operations.get(c, {})
    assert ('aux', 1) in operations
    assert ('aux', 2) not in operations
    assert switching.configuration_update_block_reason(c)
    assert len(sent) == 2


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
def test_rendered_assignment_and_confirmation_dialogs_use_dashboard_alpine_scope(client, tmp_path):
    """Render the real Django dashboard with real Alpine and a command-capturing WebSocket."""
    if os.environ.get('ATEM_RUN_OFFLINE_BROWSER_TEST') != '1':
        pytest.skip('Set ATEM_RUN_OFFLINE_BROWSER_TEST=1 for local headless Edge')
    edge = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    if not edge.exists():
        pytest.skip('Microsoft Edge is unavailable')

    rendered = client.get('/atem/dashboard/').content.decode('utf-8')
    dashboard_styles = ''.join(re.findall(r'<style\b[^>]*>.*?</style>', rendered, re.DOTALL))
    root_match = re.search(r'<div\b[^>]*\bx-data=["\']productionDashboard["\'][^>]*>', rendered)
    assert root_match, 'Django-rendered dashboard is missing its productionDashboard root.'
    root_start = root_match.start()
    depth = 0
    root_end = None
    for tag_match in re.finditer(r'</?div\b[^>]*>', rendered[root_start:], re.DOTALL):
        tag = tag_match.group(0)
        depth += -1 if tag.startswith('</') else 1
        if depth == 0:
            root_end = root_start + tag_match.end()
            break
    assert root_end is not None, 'Could not isolate the rendered Alpine dashboard root.'
    component_html = rendered[root_start:root_end]

    dashboard_js = (Path(__file__).parents[2] / 'atem_control/static/js/production_dashboard.js').as_uri()
    alpine_js = (Path(__file__).parents[2] / 'atem_control/static/vendor/alpine.min.js').as_uri()
    harness = r"""
window.sentCommands = [];
class OfflineWebSocket {
  static OPEN = 1; static CONNECTING = 0;
  constructor() { this.readyState = OfflineWebSocket.OPEN; }
  send(value) { window.sentCommands.push(JSON.parse(value)); }
  close() { this.readyState = 3; }
}
window.WebSocket = OfflineWebSocket;
function makeState(routes) {
  const sourceNames = [
    {source: 1, short: 'IN1', long: 'Input 1', port_type: 0, available_aux: true, available_me1: true},
    {source: 2, short: 'IN2', long: 'Input 2', port_type: 0, available_aux: true, available_me1: true},
    {source: 1000, short: 'Bars', long: 'Color Bars', port_type: 2, available_aux: true, available_me1: false},
    {source: 90010, short: 'PGM', long: 'M/E 1 Program', port_type: 128, available_aux: true, available_me1: false},
  ];
  const outputs = routes.map((liveSourceId, channel) => ({
    outputId: channel + 1, auxIndex: channel, displayName: `OUT ${channel + 1}`,
    liveSourceId, lastObservedSourceId: null, routeStatus: 'observed',
    owner: channel === 0 ? 'primary' : 'other',
    observedRouteOwner: liveSourceId === 90010 ? 'primary' : 'other',
    savedOwners: [], available: true, conflicts: [],
  }));
  const emptyGroup = {outputIds: [], routeStatus: 'empty', liveSourceId: null,
    savedProgramTargetId: 1, previewSourceId: 2, previewSourceValid: true, outputs: []};
  return {
    is_connected: true, sources: sourceNames,
    auxOutputs: Object.fromEntries(routes.map((source, i) => [`aux${i + 1}`, source])),
    topology: {dsks: 0}, dsks: [],
    mes: [{program: 1, preview: 2, transition: {in_transition: false, position: 0, style: 0,
      selection: {background: true, key1: false, key2: false, key3: false, key4: false}},
      usk: {states: [], data: []}}],
    dashboardSafety: {fresh: true, meCut: {reason: '', program: 1, preview: 2}, aux: {}, usk: {}, dsk: {}},
    dashboardRouting: {
      deviceId: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', revision: 7, stateFresh: true,
      capabilities: {outputMappingStatus: 'ready', outputMappingReason: '', programOutputSourceId: 90010, colorBarsSourceId: 1000},
      outputs, groups: {virtual1: {...emptyGroup}, virtual2: {...emptyGroup}}, conflicts: [],
      programBackgroundSourceId: 1,
    },
  };
}
window.addEventListener('load', async () => {
  try {
    const root = document.querySelector('[x-data="productionDashboard"]');
    const dashboard = Alpine.$data(root);
    const deviceId = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    dashboard.updateState(makeState([90010, 90010, 2, 1, 2, 1]));
    await Alpine.nextTick();
    const cards = root.querySelectorAll('.switcher-card');
    const changeButton = card => card.querySelector('button[aria-label*="output assignments"]');
    const configUnavailableDisabled = changeButton(cards[0]).disabled;
    const configUnavailableReason = dashboard.assignmentChangeReason();
    const staleState = makeState([90010, 90010, 2, 1, 2, 1]);
    staleState.dashboardSafety.fresh = false;
    dashboard.updateState(staleState); await Alpine.nextTick();
    const staleDisabled = changeButton(cards[0]).disabled;
    const staleReason = dashboard.assignmentChangeReason();
    const invalidTopology = makeState([90010, 90010, 2, 1, 2, 1]);
    invalidTopology.dashboardRouting.capabilities.outputMappingStatus = 'topology_mismatch';
    invalidTopology.dashboardRouting.capabilities.outputMappingReason = 'Expected six AUX channels; found five.';
    dashboard.updateState(invalidTopology); await Alpine.nextTick();
    const topologyDisabled = changeButton(cards[0]).disabled;
    const topologyReason = dashboard.assignmentChangeReason();
    const config = {schemaVersion: 1,
      virtualSwitchers: {
        virtual1: {outputs: [], previewSource: 2, programTarget: 1},
        virtual2: {outputs: [], previewSource: 2, programTarget: 1},
      }, customNames: {primary: null, virtual1: null, virtual2: null},
      minimumPrimaryDestinations: true, preferences: {}};
    dashboard.dashboardConfigDeviceId = deviceId;
    dashboard.dashboardConfig = {deviceId, revision: 7, config};
    dashboard.updateState(makeState([90010, 90010, 2, 1, 2, 1]));
    dashboard.dashboardConfigError = 'Revision conflict'; await Alpine.nextTick();
    const configErrorDisabled = changeButton(cards[0]).disabled;
    const configErrorReason = dashboard.assignmentChangeReason();
    dashboard.dashboardConfigError = '';
    await Alpine.nextTick();
    await new Promise(resolve => setTimeout(resolve, 50));

    const visible = dialog => {
      if (!dialog || !root.contains(dialog) || dialog.hasAttribute('x-cloak') ||
          !Alpine.evaluate(dialog, dialog.getAttribute('x-show'))) return false;
      const style = getComputedStyle(dialog);
      return style.display !== 'none' && style.visibility !== 'hidden';
    };
    const assignmentDialog = document.querySelector('[aria-label="Change output assignments"]');
    changeButton(cards[0]).click(); await Alpine.nextTick();
    await new Promise(resolve => setTimeout(resolve, 25));
    const primaryOpened = visible(assignmentDialog) && dashboard.assignmentOwner === 'primary';
    const primaryVisibilityDebug = {open: dashboard.assignmentDialogOpen, owner: dashboard.assignmentOwner,
      display: getComputedStyle(assignmentDialog).display, visibility: getComputedStyle(assignmentDialog).visibility,
      style: assignmentDialog.getAttribute('style'), inRoot: root.contains(assignmentDialog)};
    assignmentDialog.querySelector('.modal-action .btn-ghost').click();
    await Alpine.nextTick();
    const primaryCancelled = !visible(assignmentDialog) && !dashboard.assignmentDialogOpen;

    changeButton(cards[0]).click(); await Alpine.nextTick();
    const outTwoLabel = [...assignmentDialog.querySelectorAll('label')].find(label => label.textContent.includes('OUT 2'));
    const outTwoCheckbox = outTwoLabel?.querySelector('input[type="checkbox"]');
    outTwoCheckbox?.click(); await Alpine.nextTick();
    const primaryReleaseReview = dashboard.stagedAssignmentDescription(dashboard.projectedOutputs.find(output => output.outputId === 2));
    assignmentDialog.querySelector('.modal-action .btn-primary').click(); await Alpine.nextTick();
    const primaryReleaseCommand = window.sentCommands.find(command =>
      command.command === 'dashboard_output_route' && command.output_id === 2);
    dashboard.handleMessage({type: 'dashboard_output_route_accepted', output_id: 2, input_source: 1000});
    dashboard.updateState(makeState([90010, 1000, 2, 1, 2, 1])); await Alpine.nextTick();
    const primaryReleaseConfirmed = dashboard.routeBatch === null && !dashboard.assignmentDialogOpen;

    changeButton(cards[1]).click(); await Alpine.nextTick();
    const virtualOneOpened = visible(assignmentDialog) && dashboard.assignmentOwner === 'virtual1';
    const outThreeLabel = [...assignmentDialog.querySelectorAll('label')].find(label => label.textContent.includes('OUT 3'));
    const checkbox = outThreeLabel?.querySelector('input[type="checkbox"]');
    checkbox?.click(); await Alpine.nextTick();
    const reviewedDiff = dashboard.stagedAssignmentDescription(dashboard.projectedOutputs.find(output => output.outputId === 3));
    assignmentDialog.querySelector('.modal-action .btn-primary').click(); await Alpine.nextTick();
    const routeCommand = window.sentCommands.find(command =>
      command.command === 'dashboard_output_route' && command.output_id === 3);
    const applyConnected = routeCommand?.output_id === 3 && dashboard.assignmentBusy;

    dashboard.handleMessage({type: 'dashboard_output_route_accepted', output_id: 3, input_source: 1});
    dashboard.updateState(makeState([90010, 1, 1, 1, 2, 1]));
    const saveCommand = window.sentCommands.find(command => command.command === 'dashboard_config_update');
    if (saveCommand) {
      dashboard.handleMessage({type: 'dashboard_config', deviceId, revision: 8, config: saveCommand.config});
    }
    await Alpine.nextTick();
    const assignmentFinished = !!saveCommand && !visible(assignmentDialog);

    changeButton(cards[2]).click(); await Alpine.nextTick();
    const virtualTwoOpened = visible(assignmentDialog) && dashboard.assignmentOwner === 'virtual2';
    assignmentDialog.querySelector('.modal-action .btn-ghost').click(); await Alpine.nextTick();

    const conflictState = makeState([90010, 90010, 2, 1, 2, 1]);
    conflictState.dashboardRouting.outputs[1].owner = 'primary';
    conflictState.dashboardRouting.outputs[1].observedRouteOwner = 'primary';
    conflictState.dashboardRouting.outputs[1].savedOwners = ['virtual1'];
    conflictState.dashboardRouting.outputs[1].conflicts = [{type: 'primary_virtual_ownership_conflict', outputId: 2}];
    conflictState.dashboardRouting.conflicts = conflictState.dashboardRouting.outputs[1].conflicts;
    conflictState.dashboardRouting.supersededVirtualOutputIds = [2];
    dashboard.updateState(conflictState);
    dashboard.dashboardConfig.config.virtualSwitchers.virtual1.outputs = [1];
    await Alpine.nextTick();
    changeButton(cards[1]).click(); await Alpine.nextTick();
    const conflictedOutput = [...assignmentDialog.querySelectorAll('label')].find(label => label.textContent.includes('OUT 2'));
    const conflictCheckbox = conflictedOutput?.querySelector('input[type="checkbox"]');
    const primaryOwnsConflictedOutput = dashboard.primarySwitcherOutputs.some(output => output.outputId === 2) &&
      !dashboard.otherOutputViews.some(output => output.outputId === 2);
    const conflictExcludedFromVirtual = !!conflictCheckbox && !conflictCheckbox.checked && conflictCheckbox.disabled;
    assignmentDialog.querySelector('.modal-action .btn-ghost').click(); await Alpine.nextTick();

    dashboard.keyedAutoConfirmOpen = true; await Alpine.nextTick();
    const keyedDialog = document.querySelector('[aria-label="Confirm keyed AUTO"]');
    const keyedDialogScoped = visible(keyedDialog) && keyedDialog.textContent.includes('Confirm keyed AUTO');
    keyedDialog.querySelector('.modal-action .btn-ghost').click(); await Alpine.nextTick();

    dashboard.groupAlignDraft = {groupId: 'virtual1', target: 1,
      expectedRoutes: [{channel: 1, source: 1}, {channel: 2, source: 2}]};
    await Alpine.nextTick();
    const alignDialog = document.querySelector('[aria-label="Confirm virtual switcher route alignment"]');
    const alignmentDialogScoped = visible(alignDialog) && alignDialog.textContent.includes('Align mixed routes');
    alignDialog.querySelector('.modal-action .btn-ghost').click(); await Alpine.nextTick();

    const takeRoutes = [90010, 1, 2, 1, 2, 1];
    const takeState = makeState(takeRoutes);
    takeState.dashboardRouting.outputs[1].owner = 'virtual1';
    takeState.dashboardRouting.outputs[2].owner = 'virtual2';
    takeState.dashboardRouting.groups.virtual1 = {outputIds: [2], routeStatus: 'uniform', liveSourceId: 1,
      previewSourceId: 2, previewSourceValid: true, savedProgramTargetId: 1, outputs: [takeState.dashboardRouting.outputs[1]]};
    takeState.dashboardRouting.groups.virtual2 = {outputIds: [3], routeStatus: 'uniform', liveSourceId: 2,
      previewSourceId: 1, previewSourceValid: true, savedProgramTargetId: 2, outputs: [takeState.dashboardRouting.outputs[2]]};
    dashboard.dashboardConfig.config.virtualSwitchers.virtual1 = {outputs: [1], previewSource: 2, programTarget: 1};
    dashboard.dashboardConfig.config.virtualSwitchers.virtual2 = {outputs: [2], previewSource: 1, programTarget: 2};
    dashboard.updateState(takeState); await Alpine.nextTick();
    const liveStyle = button => ({background: getComputedStyle(button).backgroundColor,
      color: getComputedStyle(button).color, opacity: getComputedStyle(button).opacity,
      disabled: button.disabled});
    const primaryLiveStyle = liveStyle(cards[0].querySelectorAll('.source-grid')[1].querySelector('.btn-live-source'));
    const virtualLiveStyle = liveStyle(cards[1].querySelectorAll('.source-grid')[1].querySelector('.btn-live-source'));
    const outputBadgeStyle = {background: getComputedStyle(cards[0].querySelector('.output-badge')).backgroundColor,
      color: getComputedStyle(cards[0].querySelector('.output-badge')).color};
    const takeAllCard = root.querySelector('[aria-label="TAKE ALL"]');
    const takeAllButton = [...takeAllCard.querySelectorAll('button')].find(button => button.textContent.trim() === 'TAKE ALL');
    const takeAllReady = !takeAllButton.disabled && dashboard.takeAllReason() === '';
    const keyedState = makeState(takeRoutes);
    keyedState.mes[0].transition.selection.key1 = true;
    keyedState.dashboardSafety.meCut.reason = 'M/E CUT blocked: KEY 1 tied to next transition.';
    keyedState.dashboardRouting = takeState.dashboardRouting;
    dashboard.updateState(keyedState); await Alpine.nextTick();
    const commandsBeforeTiedCut = window.sentCommands.length;
    dashboard.takeAll(); await Alpine.nextTick();
    const tiedTakeAllBlocked = takeAllButton.disabled && window.sentCommands.length === commandsBeforeTiedCut;
    dashboard.updateState(takeState); await Alpine.nextTick();
    takeAllButton.click(); await Alpine.nextTick();
    const takeAllCommand = window.sentCommands.find(command => command.command === 'dashboard_take_all');
    dashboard.handleMessage({type: 'dashboard_take_all_started', device_id: deviceId,
      primary: {ok: true, action: 'cut', command: 'cut', before: 1, target: 2, style: 0},
      virtual: {
        virtual1: {status: 'pending', target: 2, previous: 1, outcomes: [{channel: 1, ok: true}]},
        virtual2: {status: 'pending', target: 1, previous: 2, outcomes: [{channel: 2, ok: true}]},
      }});
    await Alpine.nextTick();
    await new Promise(resolve => setTimeout(resolve, 50));
    const takeAllResultElement = takeAllCard.querySelector('[aria-live="polite"]');
    const takeAllPendingWithoutResultPanel = dashboard.takeAllOperation?.status === 'pending' &&
      getComputedStyle(takeAllResultElement).display === 'none' &&
      !takeAllCard.textContent.includes('Review TAKE ALL results');
    const otherRow = root.querySelector('.other-output-list-inner');
    const otherOverflow = getComputedStyle(otherRow.closest('.other-output-list')).overflowX;
    const otherDirectButtons = otherRow.querySelectorAll('.route-source-grid button').length > 0 &&
      otherRow.querySelectorAll('[aria-label*="Preview"], [aria-label*="Program"]').length === 0;

    const hardwareCommands = window.sentCommands.filter(command =>
      !['dashboard_config_get', 'dashboard_output_route', 'dashboard_config_update', 'dashboard_take_all'].includes(command.command));
    document.getElementById('result').textContent = JSON.stringify({
      primaryOpened, primaryReleaseReview, primaryReleaseCommand, primaryReleaseConfirmed,
      virtualOneOpened, virtualTwoOpened, reviewedDiff, applyConnected,
      assignmentFinished, keyedDialogScoped, alignmentDialogScoped, hardwareCommands,
      configUnavailableDisabled, configUnavailableReason,
      primaryCancelled, staleDisabled, staleReason, topologyDisabled, topologyReason,
      configErrorDisabled, configErrorReason, primaryOwnsConflictedOutput, conflictExcludedFromVirtual,
      primaryVisibilityDebug, takeAllReady, takeAllCommand, tiedTakeAllBlocked,
      takeAllPendingWithoutResultPanel, otherOverflow, otherDirectButtons,
      primaryLiveStyle, virtualLiveStyle, outputBadgeStyle,
    });
  } catch (error) {
    document.getElementById('result').textContent = JSON.stringify({error: String(error), stack: error.stack});
  }
});
"""
    fixture = tmp_path / 'rendered_dashboard_assignment_dom.html'
    static_root = Path(__file__).parents[2] / 'atem_control/static'
    css_links = ''.join(
        f'<link rel="stylesheet" href="{(static_root / path).as_uri()}">'
        for path in ('vendor/webatem.css', 'vendor/bootstrap-icons/bootstrap-icons.min.css', 'brand/brand.css')
    )
    fixture.write_text(
        '<!doctype html><html data-theme="dark"><meta charset="utf-8"><style>[x-cloak]{display:none!important}</style>' + dashboard_styles + css_links
        + '<script>window.sentCommands=[];</script>' + component_html
        + '<output id="result">waiting</output>'
        + f'<script src="{dashboard_js}"></script><script>{harness}</script>'
        + f'<script defer src="{alpine_js}"></script>',
        encoding='utf-8')
    result = subprocess.run([
        str(edge), '--headless', '--disable-gpu', '--no-first-run',
        f'--user-data-dir={tmp_path / "edge-profile"}', '--virtual-time-budget=4000',
        '--dump-dom', fixture.as_uri(),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    match = re.search(r'<output id="result">(.*?)</output>', result.stdout, re.DOTALL)
    assert match and match.group(1) != 'waiting', result.stdout[-3000:]
    observed = json.loads(html.unescape(match.group(1)))
    assert 'error' not in observed, observed
    assert observed['primaryOpened'] is True, observed['primaryVisibilityDebug']
    assert observed['primaryCancelled'] is True
    assert 'Release to Color Bars' in observed['primaryReleaseReview']
    assert observed['primaryReleaseCommand']['mode'] == 'primary_release'
    assert observed['primaryReleaseCommand']['input_source'] == 1000
    assert observed['primaryReleaseConfirmed'] is True
    assert observed['virtualOneOpened'] is True
    assert observed['virtualTwoOpened'] is True
    assert 'Route IN2' in observed['reviewedDiff']
    assert observed['applyConnected'] is True
    assert observed['assignmentFinished'] is True
    assert observed['keyedDialogScoped'] is True
    assert observed['alignmentDialogScoped'] is True
    assert observed['hardwareCommands'] == []
    assert observed['configUnavailableDisabled'] is True
    assert 'configuration' in observed['configUnavailableReason'].lower()
    assert observed['staleDisabled'] is True
    assert 'stale' in observed['staleReason'].lower()
    assert observed['topologyDisabled'] is True
    assert 'six AUX channels' in observed['topologyReason']
    assert observed['configErrorDisabled'] is True
    assert 'revision conflict' in observed['configErrorReason'].lower()
    assert observed['takeAllReady'] is True
    assert observed['takeAllCommand']['primary_action'] == 'cut'
    assert observed['tiedTakeAllBlocked'] is True
    assert observed['takeAllPendingWithoutResultPanel'] is True
    assert observed['otherOverflow'] == 'auto'
    assert observed['otherDirectButtons'] is True
    for style in (observed['primaryLiveStyle'], observed['virtualLiveStyle']):
        assert style == {'background': 'rgb(220, 38, 38)', 'color': 'rgb(255, 255, 255)',
                         'opacity': '1', 'disabled': True}
    assert observed['outputBadgeStyle'] == {'background': 'rgb(229, 231, 235)',
                                            'color': 'rgb(17, 24, 39)'}
    assert observed['primaryOwnsConflictedOutput'] is True
    assert observed['conflictExcludedFromVirtual'] is True


@pytest.mark.django_db
def test_rendered_dashboard_keeps_live_program_visible_and_cut_feedback_hidden(client):
    html = client.get('/atem/dashboard/').content.decode('utf-8')
    assert 'Observed M/E Program' not in html
    assert 'Observed M/E Preview' not in html
    assert 'outputSourceId(output)' in html
    assert 'outputStatus(output)' in html
    assert 'x-show="view.routeWarning"' in html
    assert 'x-text="view.routeWarning?.title"' in html
    assert '.production-dashboard .cut-feedback-hidden { display: none !important; }' in html
    assert 'Observed hardware routes' not in html
    assert 'All assigned outputs:' not in html
    assert 'CUT ALL OUTPUTS' not in html
