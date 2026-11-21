"""Conservative, dashboard-only switching preflight on the pooled ATEM connection.

The stock WebATEM verbs remain unchanged. A preflight and enqueue are serialized
per process, but another ATEM controller can change state between them; observed
hardware state, never command acceptance, remains the source of truth.
"""

import threading
import time
import weakref
from contextlib import contextmanager

from atem_control.control.commands import dispatch


MAX_RX_AGE = 4.0  # atemwire re-handshakes after roughly five quiet seconds
PENDING_SECONDS = 3.0
_lock = threading.RLock()
_operations = weakref.WeakKeyDictionary()


@contextmanager
def configuration_update_lock():
    """Serialize config CAS with route preflight and command enqueue."""
    with _lock:
        yield


def configuration_update_block_reason(connection):
    """Prevent ownership/config edits while physical AUX results are uncertain."""
    with _lock:
        operations = _operations.get(connection, {})
        if any(key[0] == 'aux' for key in operations):
            mx, _reason = _raw(connection)
            if mx is not None:
                for key in list(operations):
                    if key[0] == 'aux':
                        _pending(connection, key, _source(mx, 'aux-output-source', key[1]))
        if any(key[0] == 'aux' for key in operations):
            return 'A physical output route is pending or unconfirmed; review hardware state before saving configuration.'
        return None


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _raw(connection):
    if not connection or not getattr(connection, 'is_connected', False) or not getattr(connection, 'is_ready', False):
        return None, 'Switcher disconnected or reconnecting.'
    transport = getattr(getattr(connection, 'protocol', None), 'transport', None)
    last_rx = getattr(transport, 'last_rx_monotonic', None)
    if not isinstance(last_rx, (int, float)) or last_rx <= 0 or not 0 <= time.monotonic() - last_rx <= MAX_RX_AGE:
        return None, 'ATEM state is stale or its receive time is unknown.'
    mx = getattr(connection, 'mixerstate', None)
    if not isinstance(mx, dict) or not mx:
        return None, 'ATEM hardware state is unavailable.'
    return mx, None


def _entry(mx, name, index):
    entries = mx.get(name)
    return entries.get(index) if isinstance(entries, dict) else None


def _source(mx, name, index):
    entry = _entry(mx, name, index)
    value = getattr(entry, 'source', None)
    return value if _integer(value) else None


def _pending(connection, key, live):
    operations = _operations.get(connection, {})
    operation = operations.get(key)
    if not operation:
        return None
    key_targets = operation.get('key_targets')
    if key_targets is not None:
        if live != operation['before']:
            operation['uncertain'] = True
            return 'M/E background changed during key-only AUTO; review current hardware state before another action.'
        mx = getattr(connection, 'mixerstate', None)
        keys_confirmed = isinstance(mx, dict) and all(
            _usk_on_air(mx, int(index)) is target
            for index, target in key_targets.items()
        )
        position = _entry(mx, 'transition-position', 0) if isinstance(mx, dict) else None
        transition_at_rest = (type(getattr(position, 'in_transition', None)) is bool and
                              position.in_transition is False and
                              _integer(getattr(position, 'position', None)) and
                              position.position == 0)
        if keys_confirmed and transition_at_rest:
            operations.pop(key, None)
            return None
        if time.monotonic() - operation['since'] >= PENDING_SECONDS:
            operation['uncertain'] = True
            return 'Key-only AUTO is unconfirmed. Review current keyer and M/E state before another action.'
        return 'Key-only AUTO is awaiting observed keyer and transition confirmation.'
    if live == operation['target']:
        operations.pop(key, None)
        return None
    if live is not None and live != operation['before']:
        operation['uncertain'] = True
        return ('Observed hardware state differs from both the previous and requested source. '
                'The operation is unconfirmed; review current hardware state before another action.')
    if time.monotonic() - operation['since'] >= PENDING_SECONDS:
        operation['uncertain'] = True
        return 'Previous command is unconfirmed. Review current hardware state before another action.'
    return 'A switching command is awaiting hardware confirmation.'


def me_cut_readiness(connection):
    """Return (reason, program, preview); a falsey reason means safe to CUT."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return reason, None, None
        program = _source(mx, 'program-bus-input', 0)
        preview = _source(mx, 'preview-bus-input', 0)
        if program is None or preview is None:
            return 'M/E Program or Preview has not been observed.', program, preview
        program_source = _entry(mx, 'input-properties', program)
        preview_source = _entry(mx, 'input-properties', preview)
        if program_source is None or preview_source is None:
            return 'M/E Program or Preview source is missing from the device catalog.', program, preview
        # Both sources are already observed on real M/E buses. Availability
        # flags describe a new bus assignment and may omit internal sources;
        # CUT only takes the currently selected Preview bus to Program.
        reason = _pending(connection, ('me', 0), program)
        if reason:
            return reason, program, preview
        settings = _entry(mx, 'transition-settings', 0)
        position = _entry(mx, 'transition-position', 0)
        if settings is None or position is None:
            return 'M/E transition selection or position has not been observed.', program, preview
        fields = [getattr(settings, 'next_transition_bkgd', None)] + [
            getattr(settings, f'next_transition_key{i}', None) for i in range(1, 5)
        ] + [getattr(position, 'in_transition', None)]
        if any(type(value) is not bool for value in fields):
            return 'M/E transition state is incomplete or malformed.', program, preview
        if fields[0] is not True:
            return 'Background is not selected for the next M/E transition.', program, preview
        tied = [f'KEY {i}' for i in range(1, 5) if fields[i]]
        if tied:
            return f"M/E CUT blocked: {', '.join(tied)} tied to next transition.", program, preview
        if fields[-1] is True:
            return 'M/E transition is already in progress.', program, preview
        handle_position = getattr(position, 'position', None)
        if not _integer(handle_position) or handle_position != 0:
            return 'M/E transition position is unknown or not at rest.', program, preview
        # TrPs frames_remaining may retain a value after the ATEM reports
        # in_transition=False and position=0. Those two observed fields are
        # the rest-state guard; the residual countdown is informational.
        if program == preview:
            return 'M/E Preview is already live; select a different Preview source.', program, preview
        return None, program, preview


def aux_cut_readiness(connection, channel, target=None, expected_live=None):
    """Return (reason, live); channel is the existing zero-based AUX index."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return reason, None
        top = mx.get('topology')
        count = getattr(top, 'aux_outputs', None)
        if not _integer(channel) or not _integer(count) or channel >= count:
            return 'AUX destination is not confirmed by device topology.', None
        live = _source(mx, 'aux-output-source', channel)
        if live is None:
            return 'Current AUX route has not been observed.', None
        reason = _pending(connection, ('aux', channel), live)
        if reason:
            return reason, live
        if target is None:
            return None, live
        if not _integer(target):
            return 'No valid AUX Preview source is queued.', live
        source = _entry(mx, 'input-properties', target)
        if source is None or getattr(source, 'available_aux', None) is not True:
            return 'Queued source is not directly routable to this AUX.', live
        if target == live:
            return 'Queued AUX Preview source is already live.', live
        if expected_live is not None and expected_live != live:
            return 'AUX route changed since Preview was queued; review the live source.', live
        return None, live


def _usk_on_air(mx, key_index):
    me_keys = _entry(mx, 'key-on-air', 0)
    entry = me_keys.get(key_index) if isinstance(me_keys, dict) else None
    value = getattr(entry, 'enabled', None)
    return value if type(value) is bool else None


def usk_toggle_readiness(connection, key_index, expected_on_air=None):
    """Return (reason, observed_on_air) from a received KeOn packet."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return reason, None
        if not _integer(key_index):
            return 'Invalid upstream keyer index.', None
        live = _usk_on_air(mx, key_index)
        if live is None:
            return 'Upstream keyer on-air state has not been observed.', None
        reason = _pending(connection, ('usk', key_index), live)
        if reason:
            return reason, live
        if expected_on_air is not None and expected_on_air is not live:
            return 'Upstream keyer changed; review current on-air state.', live
        return None, live


def _dsk_on_air(mx, dsk_index):
    state = _entry(mx, 'dkey-state', dsk_index)
    value = getattr(state, 'on_air', None)
    return value if type(value) is bool else None


def dsk_toggle_readiness(connection, dsk_index, expected_on_air=None):
    """Return (reason, observed_on_air) from a received DskS packet."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return reason, None
        count = getattr(mx.get('topology'), 'downstream_keyers', None)
        if not _integer(dsk_index) or not _integer(count) or dsk_index >= count:
            return 'Downstream keyer is not confirmed by device topology.', None
        state = _entry(mx, 'dkey-state', dsk_index)
        live = _dsk_on_air(mx, dsk_index)
        if live is None:
            return 'Downstream keyer on-air state has not been observed.', None
        if type(getattr(state, 'is_transitioning', None)) is not bool or \
                type(getattr(state, 'is_autotransitioning', None)) is not bool:
            return 'Downstream keyer transition state is incomplete.', live
        if state.is_transitioning or state.is_autotransitioning:
            return 'Downstream keyer is transitioning.', live
        reason = _pending(connection, ('dsk', dsk_index), live)
        if reason:
            return reason, live
        if expected_on_air is not None and expected_on_air is not live:
            return 'Downstream keyer changed; review current on-air state.', live
        return None, live


def _take_all_pending_controls(connection, mx):
    """Reconcile tracked controls against fresh hardware and report blockers."""
    blockers = []
    for (kind, index), operation in list(_operations.get(connection, {}).items()):
        if kind == 'me_preview':
            label = 'M/E Preview'
            live = _source(mx, 'preview-bus-input', 0)
        elif kind == 'usk':
            label = f'Upstream keyer {index + 1}'
            live = _usk_on_air(mx, index)
        elif kind == 'dsk':
            label = f'Downstream keyer {index + 1}'
            state = _entry(mx, 'dkey-state', index)
            count = getattr(mx.get('topology'), 'downstream_keyers', None)
            live = None
            if (_integer(count) and index < count and getattr(state, 'is_transitioning', None) is False and
                    getattr(state, 'is_autotransitioning', None) is False):
                live = _dsk_on_air(mx, index)
        else:
            continue
        reason = _pending(connection, (kind, index), live)
        if reason:
            blockers.append({
                'kind': kind, 'index': index, 'label': label,
                'message': f'{label} is blocking TAKE ALL. {reason}',
                'reviewable': live is not None and time.monotonic() - operation['since'] >= PENDING_SECONDS,
            })
    return blockers


def safety_snapshot(connection):
    """UI projection from the same evaluation used at the command boundary."""
    with _lock:
        reason, program, preview = me_cut_readiness(connection)
        mx, freshness_reason = _raw(connection)
        top = mx.get('topology') if mx else None
        count = getattr(top, 'aux_outputs', 0) or 0
        aux = {}
        for channel in range(min(count, 64)) if _integer(count) else ():
            aux_reason, live = aux_cut_readiness(connection, channel)
            aux[str(channel)] = {'reason': aux_reason, 'live': live}
        usk = {}
        me_keys = _entry(mx, 'key-on-air', 0) if mx else None
        if isinstance(me_keys, dict):
            for key_index in me_keys:
                if _integer(key_index):
                    key_reason, on_air = usk_toggle_readiness(connection, key_index)
                    usk[str(key_index)] = {'reason': key_reason, 'onAir': on_air}
        dsk = {}
        dsk_count = getattr(top, 'downstream_keyers', None)
        if _integer(dsk_count):
            for dsk_index in range(min(dsk_count, 64)):
                dsk_reason, on_air = dsk_toggle_readiness(connection, dsk_index)
                dsk[str(dsk_index)] = {'reason': dsk_reason, 'onAir': on_air}
        return {'fresh': freshness_reason is None,
                'meCut': {'reason': reason, 'program': program, 'preview': preview},
                'takeAllBlockers': _take_all_pending_controls(connection, mx) if mx else [],
                'aux': aux, 'usk': usk, 'dsk': dsk}


def state_is_fresh(connection):
    """Whether the pooled connection has a recent, ready hardware snapshot."""
    with _lock:
        _mx, reason = _raw(connection)
        return reason is None


def _record(connection, key, before, target, key_targets=None):
    operations = _operations.setdefault(connection, {})
    operations[key] = {'before': before, 'target': target, 'since': time.monotonic(),
                       'uncertain': False, 'key_targets': key_targets}


def dispatch_me_cut(connection, data):
    """Recheck raw state and enqueue exactly one existing WebATEM CUT command."""
    with _lock:
        if data.get('me', 0) != 0:
            return False, 'Dashboard supports M/E 1 only.'
        reason, program, preview = me_cut_readiness(connection)
        if reason:
            return False, reason
        if not _integer(data.get('expected_program')) or not _integer(data.get('expected_preview')):
            return False, 'Expected M/E Program and Preview sources are required.'
        if data['expected_program'] != program or data['expected_preview'] != preview:
            return False, 'M/E Program or Preview changed; review current hardware state.'
        ok, error = dispatch(connection, 'cut', {'me': 0})
        if ok:
            _record(connection, ('me', 0), program, preview)
        return ok, error


def dispatch_aux_cut(connection, data):
    """Recheck raw source/route and enqueue one existing AUX routing command."""
    with _lock:
        channel = data.get('aux_channel')
        target = data.get('input_source')
        expected_live = data.get('expected_live')
        if not _integer(target):
            return False, 'No valid AUX Preview source is queued.'
        if not _integer(expected_live):
            return False, 'Expected live AUX source is required for a safe CUT.'
        reason, live = aux_cut_readiness(connection, channel, target, expected_live)
        if reason:
            return False, reason
        ok, error = dispatch(connection, 'set_aux_output', {'aux_channel': channel, 'input_source': target})
        if ok:
            _record(connection, ('aux', channel), live, target)
        return ok, error


def dispatch_usk_toggle(connection, data):
    """Guard an explicit USK on-air target on the pooled command path."""
    with _lock:
        key_index = data.get('key_index')
        expected = data.get('expected_on_air')
        target = data.get('target_on_air')
        if data.get('me', 0) != 0 or type(expected) is not bool or type(target) is not bool or target is expected:
            return False, 'Expected M/E 1 keyer state and opposite on-air target are required.'
        reason, live = usk_toggle_readiness(connection, key_index, data['expected_on_air'])
        if reason:
            return False, reason
        ok, error = dispatch(connection, 'set_usk_on_air',
                             {'me': 0, 'key_index': key_index, 'enabled': target})
        if ok:
            _record(connection, ('usk', key_index), live, target)
        return ok, error


def dispatch_dsk_toggle(connection, data):
    """Guard an explicit DSK on-air target on the pooled command path."""
    with _lock:
        dsk_index = data.get('dsk')
        expected = data.get('expected_on_air')
        target = data.get('target_on_air')
        if type(expected) is not bool or type(target) is not bool or target is expected:
            return False, 'Expected DSK state and opposite on-air target are required.'
        reason, live = dsk_toggle_readiness(connection, dsk_index, expected)
        if reason:
            return False, reason
        ok, error = dispatch(connection, 'set_dsk_on_air',
                             {'dsk': dsk_index, 'enabled': target})
        if ok:
            _record(connection, ('dsk', dsk_index), live, target)
        return ok, error


def _me_state(mx):
    """Return validated M/E buses, transition settings, and position."""
    program = _source(mx, 'program-bus-input', 0)
    preview = _source(mx, 'preview-bus-input', 0)
    settings = _entry(mx, 'transition-settings', 0)
    position = _entry(mx, 'transition-position', 0)
    if program is None or preview is None:
        return None, 'M/E Program or Preview has not been observed.'
    if _entry(mx, 'input-properties', program) is None or _entry(mx, 'input-properties', preview) is None:
        return None, 'M/E Program or Preview source is missing from the device catalog.'
    if settings is None or position is None:
        return None, 'M/E transition settings or position have not been observed.'
    selection = [getattr(settings, 'next_transition_bkgd', None)] + [
        getattr(settings, f'next_transition_key{i}', None) for i in range(1, 5)]
    in_transition = getattr(position, 'in_transition', None)
    position_value = getattr(position, 'position', None)
    if any(type(value) is not bool for value in selection) or type(in_transition) is not bool:
        return None, 'M/E transition selection or progress state is incomplete or malformed.'
    if not _integer(position_value):
        return None, 'M/E transition position is unknown.'
    return {'program': program, 'preview': preview, 'settings': settings,
            'position': position, 'selection': selection,
            'in_transition': in_transition, 'position_value': position_value}, None


def dispatch_me_preview(connection, data):
    """Guard and dispatch a Primary hardware Preview selection."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return False, reason
        state, reason = _me_state(mx)
        if reason:
            return False, reason
        target = data.get('source')
        expected = data.get('expected_preview')
        if data.get('me', 0) != 0 or not _integer(target) or not _integer(expected):
            return False, 'A valid M/E 1 Preview source and expected current source are required.'
        if state['preview'] != expected:
            return False, 'M/E Preview changed; review the current hardware state.'
        if state['in_transition'] or state['position_value'] != 0:
            return False, 'M/E Preview is locked while a transition is active or not at rest.'
        pending = _pending(connection, ('me_preview', 0), state['preview'])
        if pending:
            return False, pending
        source = _entry(mx, 'input-properties', target)
        if source is None or getattr(source, 'available_me1', None) is not True:
            return False, 'Selected source is not directly available to M/E 1.'
        ok, error = dispatch(connection, 'set_preview', {'source': target, 'me': 0})
        if ok:
            _record(connection, ('me_preview', 0), state['preview'], target)
        return ok, error


def dispatch_me_program(connection, data):
    """Guard the explicitly enabled direct Primary Program operation."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return False, reason
        state, reason = _me_state(mx)
        if reason:
            return False, reason
        target = data.get('source')
        expected = data.get('expected_program')
        if data.get('me', 0) != 0 or not _integer(target) or not _integer(expected):
            return False, 'A valid M/E 1 Program source and expected current source are required.'
        if state['program'] != expected:
            return False, 'M/E Program changed; review the current hardware state.'
        if state['in_transition'] or state['position_value'] != 0:
            return False, 'Direct Program selection is blocked while an M/E transition is active.'
        pending = _pending(connection, ('me', 0), state['program'])
        if pending:
            return False, pending
        source = _entry(mx, 'input-properties', target)
        if source is None or getattr(source, 'available_me1', None) is not True:
            return False, 'Selected source is not directly available to M/E 1.'
        if target == state['program']:
            return False, 'Selected source is already M/E Program.'
        ok, error = dispatch(connection, 'set_program', {'source': target, 'me': 0})
        if ok:
            _record(connection, ('me', 0), state['program'], target)
        return ok, error


def dispatch_me_auto(connection, data):
    """Guard Primary AUTO; keyed transitions require explicit confirmation."""
    with _lock:
        reason, state = me_auto_readiness(connection, data)
        if reason:
            return False, reason
        ok, error = dispatch(connection, 'auto', {'me': 0})
        if ok:
            _record(connection, ('me', 0), state['program'], state['preview'],
                    key_targets=state.get('key_targets'))
        return ok, error


def me_auto_readiness(connection, data):
    """Validate the selected hardware AUTO without issuing a command."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return reason, None
        state, reason = _me_state(mx)
        if reason:
            return reason, None
        if data.get('me', 0) != 0 or data.get('expected_program') != state['program'] or \
                data.get('expected_preview') != state['preview']:
            return 'M/E Program or Preview changed; review the current hardware state.', None
        if state['in_transition'] or state['position_value'] != 0:
            return 'M/E transition is active or not at rest.', None
        if state['program'] == state['preview']:
            return 'M/E Preview is already live; select a different Preview source.', None
        pending = _pending(connection, ('me', 0), state['program'])
        if pending:
            return pending, None
        background, *keys = state['selection']
        expected_selection = data.get('expected_selection')
        observed_selection = {'background': background,
                              **{f'key{i + 1}': keys[i] for i in range(4)}}
        if not isinstance(expected_selection, dict) or expected_selection != observed_selection:
            return 'M/E next-transition selection changed; review the tied keyers before AUTO.', None
        if not (background or any(keys)):
            return 'No M/E background or keyer is selected for the next transition.', None
        tied = [index + 1 for index, selected in enumerate(keys) if selected]
        if tied and data.get('allow_keyed') is not True:
            return 'Keyed AUTO requires explicit confirmation for: ' + ', '.join(f'KEY {i}' for i in tied), None
        if not background:
            key_before = {}
            key_targets = {}
            for key_index, selected in enumerate(keys):
                if not selected:
                    continue
                on_air = _usk_on_air(mx, key_index)
                if on_air is None:
                    return f'Key-only AUTO cannot be confirmed because KEY {key_index + 1} on-air state is unknown.', None
                key_before[str(key_index)] = on_air
                key_targets[str(key_index)] = not on_air
            expected_key_states = data.get('expected_key_states')
            if not isinstance(expected_key_states, dict) or expected_key_states != key_before:
                return 'Key-only AUTO keyer state changed or is unavailable; review keyer state before AUTO.', None
            state['key_before'] = key_before
            state['key_targets'] = key_targets
        style = getattr(state['settings'], 'style', None)
        if type(style) is not int or style not in (0, 1, 2, 3, 4):
            return 'Selected M/E transition style is unknown or unsupported.', None
        if data.get('expected_style', style) != style:
            return 'Selected M/E transition style changed; review before AUTO.', None
        pending_style = _pending(connection, ('transition_style', 0), style)
        if pending_style:
            return pending_style, None
        if style in (3, 4):
            capability = 'dves' if style == 3 else 'stingers'
            count = getattr(mx.get('topology'), capability, None)
            if not _integer(count) or count == 0:
                return f'{"DVE" if style == 3 else "Stinger"} transition capability is unavailable or unknown.', None
        return None, state


def dispatch_me_transition_style(connection, data):
    """Configure a supported transition style without executing it."""
    with _lock:
        mx, reason = _raw(connection)
        if reason:
            return False, reason
        style = data.get('style')
        if type(style) is not int or style not in (0, 1, 2, 3, 4):
            return False, 'Unsupported transition style.'
        settings = _entry(mx, 'transition-settings', 0)
        position = _entry(mx, 'transition-position', 0)
        if settings is None or position is None or type(getattr(settings, 'style', None)) is not int:
            return False, 'Current M/E transition style has not been observed.'
        if type(getattr(position, 'in_transition', None)) is not bool or \
                not _integer(getattr(position, 'position', None)):
            return False, 'M/E transition progress state is incomplete.'
        if position.in_transition or position.position != 0:
            return False, 'Transition style cannot change while M/E is transitioning.'
        if style in (3, 4):
            topology = mx.get('topology')
            capability = 'dves' if style == 3 else 'stingers'
            count = getattr(topology, capability, None)
            if not _integer(count) or count == 0:
                return False, f'{"DVE" if style == 3 else "Stinger"} transition capability is unavailable or unknown.'
        pending = _pending(connection, ('transition_style', 0), settings.style)
        if pending:
            return False, pending
        if style == settings.style:
            return False, 'Transition style is already selected.'
        ok, error = dispatch(connection, 'set_transition_style', {'style': style, 'me': 0})
        if ok:
            _record(connection, ('transition_style', 0), settings.style, style)
        return ok, error


def _config_payload(config_snapshot):
    if isinstance(config_snapshot, dict) and isinstance(config_snapshot.get('config'), dict):
        return config_snapshot['config'], config_snapshot.get('revision')
    return config_snapshot if isinstance(config_snapshot, dict) else {}, None


def _current_config_revision_reason(connection, config_snapshot):
    """Recheck the device's CAS revision at the serialized write boundary."""
    _config, revision = _config_payload(config_snapshot)
    if type(revision) is not int:
        return 'A verified device configuration revision is required before routing.'
    try:
        from atem_control.control.dashboard_config import get_config_for_connection
        current = get_config_for_connection(connection)
    except Exception:
        return 'Current device configuration could not be verified; routing is blocked.'
    if current.get('deviceId') != config_snapshot.get('deviceId'):
        return 'Connected switcher identity changed; reload configuration before routing.'
    if current.get('revision') != revision:
        return 'Dashboard configuration changed; reload ownership before routing.'
    return None


def _group(config, group_id):
    groups = config.get('virtualSwitchers')
    item = groups.get(group_id) if isinstance(groups, dict) else None
    return item if isinstance(item, dict) else {}


def _route_projection(connection, mx, config_snapshot, revision):
    from atem_control.control.dashboard_config import pending_primary_retirements
    from atem_control.control.dashboard_ownership import project_routes
    return project_routes(mx, config_snapshot, revision,
                          retired_channels=pending_primary_retirements(connection, config_snapshot))


def output_route_readiness(connection, data, config_snapshot):
    """Validate one physical output route for a named 3C workflow."""
    mx, reason = _raw(connection)
    if reason:
        return reason, None
    config, revision = _config_payload(config_snapshot)
    if data.get('config_revision') != revision:
        return 'Dashboard configuration changed; reload ownership before routing.', None
    output_id = data.get('output_id')
    if type(output_id) is not int or not 1 <= output_id <= 6:
        return 'Physical output must be OUT 1 through OUT 6.', None
    channel = output_id - 1
    topology = mx.get('topology')
    if getattr(topology, 'aux_outputs', None) != 6:
        return 'Physical OUT routing is unavailable unless exactly six AUX channels are reported.', None
    live = _source(mx, 'aux-output-source', channel)
    if live is None:
        return f'OUT {output_id} current route has not been observed.', None
    expected_live = data.get('expected_live')
    if not _integer(expected_live) or expected_live != live:
        return f'OUT {output_id} changed since the operation was reviewed.', None
    target = data.get('input_source')
    source = _entry(mx, 'input-properties', target) if _integer(target) else None
    if source is None or getattr(source, 'available_aux', None) is not True:
        return f'Selected source is not directly routable to OUT {output_id}.', None
    pending = _pending(connection, ('aux', channel), live)
    if pending:
        return pending, None

    projection = _route_projection(connection, mx, config_snapshot, revision)
    output = next((item for item in projection['outputs'] if item['outputId'] == output_id), None)
    if not output or not output.get('available') or output.get('routeStatus') != 'observed':
        return f'OUT {output_id} is unavailable or unresolved.', None
    owner = output.get('owner')
    saved_owners = output.get('savedOwners') or []
    mode = data.get('mode')
    program_id = projection['capabilities'].get('programOutputSourceId')
    if program_id is None:
        return 'M/E Program output identity is ambiguous; ownership routing is blocked.', None
    if owner == 'unresolved' or owner == 'unknown' or len(saved_owners) > 1:
        return f'OUT {output_id} has an ownership conflict that must be resolved first.', None
    if output_id in projection['supersededVirtualOutputIds']:
        return f'OUT {output_id} has a superseded virtual assignment. Wait for ownership to refresh.', None

    if mode == 'primary_assign':
        if target != program_id:
            return 'Primary assignment must route to the discovered M/E Program feed.', None
        if output.get('observedRouteOwner') == 'primary':
            return f'OUT {output_id} already carries M/E Program.', None
        if owner not in ('other', 'virtual1', 'virtual2'):
            return f'OUT {output_id} cannot be assigned to Primary from its current ownership state.', None
        transfer_from = data.get('transfer_from')
        if owner in ('virtual1', 'virtual2') and transfer_from != owner:
            return f'OUT {output_id} is owned by {owner}; initiate an explicit ownership transfer.', None
        if owner == 'other' and saved_owners:
            return f'OUT {output_id} has a saved assignment; resolve the ownership conflict first.', None
    elif mode == 'primary_release':
        if output.get('observedRouteOwner') != 'primary' or live != program_id:
            return f'OUT {output_id} is not currently routed to the discovered M/E Program feed.', None
        me, reason = _me_state(mx)
        if reason:
            return reason, None
        if me['in_transition'] or me['position_value'] != 0 or \
                _pending(connection, ('me', 0), me['program']):
            return 'Cannot release an M/E Program output while M/E is transitioning or a command is pending.', None
        bars = projection['capabilities']['colorBarsSourceId']
        if bars is None:
            return 'Color Bars is unavailable or cannot be verified as AUX-routable; output release is blocked.', None
        if target != bars:
            return 'Primary release must route to the verified Color Bars source.', None
        if config.get('minimumPrimaryDestinations', True):
            count = sum(1 for item in projection['outputs'] if item['observedRouteOwner'] == 'primary')
            if count <= 1:
                return 'Cannot release the final Primary Program destination while the minimum-destination policy is enabled.', None
    elif mode == 'virtual_assign':
        group_id = data.get('group_id')
        if group_id not in ('virtual1', 'virtual2'):
            return 'Unknown virtual switcher.', None
        group = _group(config, group_id)
        if not isinstance(group.get('outputs'), list):
            return 'Saved virtual switcher assignments are malformed.', None
        if any(output_id - 1 in group['outputs'] for output_id in projection['supersededVirtualOutputIds']):
            return 'Virtual switcher ownership is being reconciled. Wait for refreshed settings.', None
        if channel in group['outputs']:
            return f'OUT {output_id} is already assigned to this virtual switcher.', None
        other_group = 'virtual2' if group_id == 'virtual1' else 'virtual1'
        other_outputs = _group(config, other_group).get('outputs', [])
        if channel in other_outputs:
            if data.get('transfer_from') != other_group:
                return f'OUT {output_id} belongs to {other_group}; initiate an explicit ownership transfer.', None
        elif owner == 'primary':
            if data.get('transfer_from') != 'primary':
                return f'OUT {output_id} carries M/E Program; initiate an explicit transfer from Primary.', None
            if config.get('minimumPrimaryDestinations', True) and len(projection['primaryOutputIds']) <= 1:
                return 'Cannot transfer the final Primary Program destination while the minimum-destination policy is enabled.', None
        elif owner != 'other':
            return f'OUT {output_id} is not available for virtual assignment.', None
        if projection['groups'][group_id]['routeStatus'] in ('mixed', 'unknown'):
            return f'{group_id} routing must be uniform and observed before assigning another output.', None
        if target == program_id:
            return 'A virtual switcher cannot claim the M/E Program feed; assign this output to Primary.', None
        expected_target = projection['groups'][group_id]['liveSourceId']
        if projection['groups'][group_id]['routeStatus'] == 'empty':
            expected_target = group.get('programTarget')
            if expected_target is None and owner == 'other' and not saved_owners:
                expected_target = live
        if target != expected_target:
            return f'{group_id} assignment target changed; review the current live or saved Program target.', None
        if target is None:
            return f'{group_id} has no saved Program target; set one before assigning an output.', None
        if live == target:
            # Assignment can complete without routing if the current output is
            # already carrying the exact group target; the caller still needs
            # to persist the ownership through a revisioned config update.
            return None, {'live': live, 'target': target, 'channel': channel, 'no_op': True}
        if output.get('observedRouteOwner') == 'primary' and data.get('transfer_from') != 'primary':
            return f'OUT {output_id} is currently Primary; explicit transfer confirmation is required.', None
    elif mode == 'other_route':
        if owner != 'other' or saved_owners:
            return f'OUT {output_id} is not an unowned Other Output.', None
        if target == program_id:
            return 'Routing to M/E Program changes ownership; use the Primary assignment workflow.', None
    else:
        return 'Unknown physical output operation.', None

    if target == live:
        return f'OUT {output_id} is already showing the selected source.', None
    return None, {'live': live, 'target': target, 'channel': channel, 'no_op': False}


def dispatch_output_route(connection, data, config_snapshot, require_current_revision=False):
    """Preflight and enqueue one 3C physical output route through WebATEM."""
    with _lock:
        if require_current_revision:
            reason = _current_config_revision_reason(connection, config_snapshot)
            if reason:
                return False, reason
        reason, route = output_route_readiness(connection, data, config_snapshot)
        if reason:
            return False, reason
        if route['no_op']:
            return True, route
        ok, error = dispatch(connection, 'set_aux_output', {
            'aux_channel': route['channel'], 'input_source': route['target']})
        if ok:
            _record(connection, ('aux', route['channel']), route['live'], route['target'])
        return ok, error or route


def _virtual_group_cut_plan(connection, data, config_snapshot):
    mx, reason = _raw(connection)
    if reason:
        return reason, None
    config, revision = _config_payload(config_snapshot)
    group_id = data.get('group_id')
    if group_id not in ('virtual1', 'virtual2'):
        return 'Unknown virtual switcher.', None
    if data.get('config_revision') != revision:
        return 'Dashboard configuration changed; reload before CUT.', None
    group = _group(config, group_id)
    channels = group.get('outputs')
    if not isinstance(channels, list) or not channels:
        return 'This virtual switcher has no assigned outputs.', None
    if any(type(c) is not int or not 0 <= c < 6 for c in channels) or len(channels) != len(set(channels)):
        return 'Virtual switcher has duplicate or unavailable output assignments.', None
    if getattr(mx.get('topology'), 'aux_outputs', None) != 6:
        return 'Physical OUT routing is unavailable unless exactly six AUX channels are reported.', None
    mode = data.get('mode', 'cut')
    if mode not in ('cut', 'direct'):
        return 'Unknown virtual switcher routing mode.', None
    if mode == 'direct':
        if not config_snapshot.get('deviceId') or data.get('device_id') != config_snapshot['deviceId']:
            return 'Connected switcher identity changed; reload before Direct Program.', None
        target = data.get('input_source')
        if 'expected_routes' not in data:
            return 'Direct Program requires the observed route of every assigned output.', None
    else:
        target = group.get('previewSource')
        if not _integer(target) or data.get('input_source') != target or data.get('expected_preview', target) != target:
            return 'Queued Preview changed or is invalid; reload the virtual switcher state.', None
    source = _entry(mx, 'input-properties', target) if _integer(target) else None
    if source is None or getattr(source, 'available_aux', None) is not True:
        return 'The selected source is not directly routable to the assigned outputs.', None
    projection = _route_projection(connection, mx, config_snapshot, revision)
    projected = projection['groups'][group_id]
    program_id = projection['capabilities']['programOutputSourceId']
    if program_id is None or target == program_id:
        return 'Virtual switching cannot target an unknown or Primary M/E Program feed.', None
    if projected['routeStatus'] not in ('uniform', 'mixed'):
        return 'All assigned output routes must be current and observed before CUT.', None
    if 'expected_routes' in data:
        expected_by_channel = _reviewed_routes(data['expected_routes'], channels)
        if expected_by_channel is None:
            return 'The reviewed routes are malformed or no longer match group ownership.', None
    elif projected['routeStatus'] == 'uniform':
        # Older dashboard sessions can still submit a uniform group.
        expected_by_channel = dict.fromkeys(channels, data.get('expected_live', projected['liveSourceId']))
    else:
        return 'Review the current route of every output before cutting a mixed group.', None
    outputs = {output['auxIndex']: output for output in projection['outputs']}
    before = {}
    for channel in channels:
        output = outputs.get(channel)
        live = _source(mx, 'aux-output-source', channel)
        if not output or output['owner'] != group_id or output['routeStatus'] != 'observed':
            return f'OUT {channel + 1} is unavailable, stale, or ownership-conflicted.', None
        if live is None or live != expected_by_channel[channel]:
            return f'OUT {channel + 1} changed after the routes were reviewed.', None
        pending = _pending(connection, ('aux', channel), live)
        if pending:
            return pending, None
        before[channel] = live
    if all(live == target for live in before.values()):
        return 'The selected source is already live.', None
    return None, {'group_id': group_id, 'channels': channels,
                  'target': target, 'before': before, 'previous': projected['liveSourceId'],
                  'revision': revision}


def _reviewed_routes(expected, channels):
    if not isinstance(expected, list) or len(expected) != len(channels):
        return None
    routes = {}
    for item in expected:
        if (not isinstance(item, dict) or not _integer(item.get('channel')) or
                not _integer(item.get('source')) or item['channel'] in routes):
            return None
        routes[item['channel']] = item['source']
    return routes if set(routes) == set(channels) else None


def dispatch_virtual_group_cut(connection, data, config_snapshot, require_current_revision=False):
    """Preflight a virtual group then enqueue one route per changed output.

    The commands are independent and may partially succeed. This function
    returns an outcome for every destination and never retries a failure.
    """
    with _lock:
        if require_current_revision:
            reason = _current_config_revision_reason(connection, config_snapshot)
            if reason:
                return False, reason
        reason, plan = _virtual_group_cut_plan(connection, data, config_snapshot)
        if reason:
            return False, reason
        outcomes = []
        for channel in plan['channels']:
            live = plan['before'][channel]
            mx, reason = _raw(connection)
            if reason or getattr(mx.get('topology'), 'aux_outputs', None) != 6 or \
                    _source(mx, 'aux-output-source', channel) != live:
                outcomes.append({'channel': channel, 'ok': False, 'before': live,
                                 'error': reason or f'OUT {channel + 1} changed during CUT dispatch.'})
                continue
            if live == plan['target']:
                outcomes.append({'channel': channel, 'ok': True, 'no_op': True, 'before': live, 'error': None})
                continue
            ok, error = dispatch(connection, 'set_aux_output', {
                'aux_channel': channel, 'input_source': plan['target']})
            if ok:
                _record(connection, ('aux', channel), live, plan['target'])
            outcomes.append({'channel': channel, 'ok': ok, 'before': live, 'error': error})
        return True, {'group_id': plan['group_id'], 'target': plan['target'],
                      'previous': plan['previous'], 'revision': plan['revision'],
                      'mode': data.get('mode', 'cut'),
                      'outcomes': outcomes}


def take_all_readiness(connection, data, config_snapshot, require_current_revision=False):
    """Preflight every TAKE ALL participant without issuing hardware writes."""
    with _lock:
        if require_current_revision:
            reason = _current_config_revision_reason(connection, config_snapshot)
            if reason:
                return reason, None
        mx, reason = _raw(connection)
        if reason:
            return reason, None
        try:
            from atem_control.control.dashboard_config import device_id_from_connection
            device_id = device_id_from_connection(connection)
        except Exception as error:
            return str(error), None
        config, revision = _config_payload(config_snapshot)
        if config_snapshot.get('deviceId') != device_id or data.get('device_id') != device_id:
            return 'Connected switcher identity changed; reload before TAKE ALL.', None
        if type(revision) is not int or data.get('config_revision') != revision:
            return 'Dashboard configuration revision is stale or unavailable.', None
        if getattr(mx.get('topology'), 'aux_outputs', None) != 6:
            return 'TAKE ALL requires the expected six-AUX output topology.', None
        if data.get('primary_action', 'cut') != 'cut':
            return 'TAKE ALL supports CUT only.', None
        if configuration_update_block_reason(connection):
            return 'An output routing operation is pending or unconfirmed; review it before TAKE ALL.', None
        blockers = _take_all_pending_controls(connection, mx)
        if blockers:
            return blockers[0]['message'], None

        me, reason = _me_state(mx)
        if reason:
            return reason, None
        if not _integer(data.get('expected_program')) or not _integer(data.get('expected_preview')) or \
                data['expected_program'] != me['program'] or data['expected_preview'] != me['preview']:
            return 'M/E Program or Preview changed; review current hardware state before TAKE ALL.', None
        expected_selection = data.get('expected_selection')
        observed_selection = {'background': me['selection'][0],
                              **{f'key{i + 1}': value for i, value in enumerate(me['selection'][1:])}}
        if not isinstance(expected_selection, dict) or expected_selection != observed_selection:
            return 'M/E next-transition selection changed; review it before TAKE ALL.', None
        primary_data = {'me': 0, 'expected_program': me['program'], 'expected_preview': me['preview']}
        reason, _program, _preview = me_cut_readiness(connection)
        primary_skipped = reason == 'M/E Preview is already live; select a different Preview source.'
        if reason and not primary_skipped:
            return reason, None

        projection = _route_projection(connection, mx, config_snapshot, revision)
        if projection['capabilities'].get('programOutputSourceId') is None:
            return 'M/E Program output identity is ambiguous; TAKE ALL is blocked.', None
        empty_groups = {group_id for group_id in ('virtual1', 'virtual2')
                        if _group(config, group_id).get('outputs') == []}
        blocking_conflicts = [conflict for conflict in projection.get('conflicts', [])
                              if not (conflict.get('type') == 'invalid_saved_source' and
                                      conflict.get('group') in empty_groups)]
        if blocking_conflicts:
            return 'Physical output ownership or route state is conflicted; resolve it before TAKE ALL.', None
        virtual = {}
        assigned_channels = set()
        expected_groups = data.get('groups')
        if not isinstance(expected_groups, dict):
            return 'Virtual switcher route expectations are unavailable.', None
        for group_id in ('virtual1', 'virtual2'):
            group = _group(config, group_id)
            channels = group.get('outputs')
            if not isinstance(channels, list) or any(
                    type(channel) is not int or not 0 <= channel < 6 for channel in channels):
                return f'{group_id} has invalid or unavailable output assignments.', None
            if len(channels) != len(set(channels)) or any(channel in assigned_channels for channel in channels):
                return 'Virtual switcher output assignments overlap or contain duplicates.', None
            assigned_channels.update(channels)
            if not channels:
                virtual[group_id] = {'status': 'skipped', 'channels': []}
                continue
            expected = expected_groups.get(group_id)
            if not isinstance(expected, dict):
                return f'{group_id} route state is unavailable; refresh before TAKE ALL.', None
            cut_data = {'group_id': group_id, 'config_revision': revision,
                        'input_source': group.get('previewSource'),
                        'expected_preview': expected.get('preview')}
            if 'routes' in expected:
                cut_data['expected_routes'] = expected['routes']
            else:
                cut_data['expected_live'] = expected.get('live')
            reason, group_plan = _virtual_group_cut_plan(connection, cut_data, config_snapshot)
            if reason == 'The selected source is already live.':
                virtual[group_id] = {'status': 'skipped', 'channels': []}
                continue
            if reason:
                return f'{group_id}: {reason}', None
            virtual[group_id] = group_plan
        if primary_skipped and all(group.get('status') == 'skipped' for group in virtual.values()):
            return 'Preview is already live on every switcher; select a different Preview source.', None
        return None, {'device_id': device_id, 'revision': revision,
                      'primary': None if primary_skipped else primary_data, 'virtual': virtual}


def dispatch_take_all(connection, data, config_snapshot, require_current_revision=False):
    """Preflight all participants, then dispatch each through guarded paths."""
    with _lock:
        reason, plan = take_all_readiness(
            connection, data, config_snapshot, require_current_revision=require_current_revision)
        if reason:
            return False, reason

        if plan['primary'] is None:
            primary = {'status': 'skipped', 'ok': True, 'action': 'cut'}
        else:
            primary_ok, primary_error = dispatch_me_cut(connection, plan['primary'])
            primary = {'ok': primary_ok, 'action': 'cut', 'command': 'cut',
                       'before': plan['primary']['expected_program'],
                       'target': plan['primary']['expected_preview'],
                       'error': primary_error if not primary_ok else ''}

        virtual = {}
        for group_id in ('virtual1', 'virtual2'):
            group_plan = plan['virtual'][group_id]
            if group_plan.get('status') == 'skipped':
                virtual[group_id] = {'status': 'skipped', 'outcomes': []}
                continue
            group_data = {'group_id': group_id, 'config_revision': plan['revision'],
                          'input_source': group_plan['target'],
                          'expected_preview': group_plan['target'],
                          'expected_routes': [{'channel': channel, 'source': live}
                                              for channel, live in group_plan['before'].items()]}
            ok, result = dispatch_virtual_group_cut(
                connection, group_data, config_snapshot,
                require_current_revision=require_current_revision)
            if not ok:
                virtual[group_id] = {'status': 'failed', 'target': group_plan['target'],
                                     'previous': group_plan['previous'], 'outcomes': [],
                                     'error': result}
                continue
            for outcome in result['outcomes']:
                if outcome['ok']:
                    outcome['output_id'] = outcome['channel'] + 1
            virtual[group_id] = {'status': 'pending' if all(item['ok'] for item in result['outcomes']) else 'partial',
                                 'target': result['target'], 'previous': result['previous'],
                                 'outcomes': result['outcomes'], 'error': ''}
        return True, {'device_id': plan['device_id'], 'revision': plan['revision'],
                      'primary': primary, 'virtual': virtual}


def dispatch_virtual_group_align(connection, data, config_snapshot, require_current_revision=False):
    """Explicitly align a mixed virtual group to one reviewed target.

    ``expected_routes`` binds the request to the complete route snapshot shown
    in the operator confirmation. Each changed physical route is dispatched
    and tracked independently; already-matching outputs are returned as
    confirmed no-ops.
    """
    with _lock:
        if require_current_revision:
            reason = _current_config_revision_reason(connection, config_snapshot)
            if reason:
                return False, reason
        mx, reason = _raw(connection)
        if reason:
            return False, reason
        config, revision = _config_payload(config_snapshot)
        group_id = data.get('group_id')
        if group_id not in ('virtual1', 'virtual2'):
            return False, 'Unknown virtual switcher.'
        if data.get('config_revision') != revision:
            return False, 'Dashboard configuration changed; reload before aligning routes.'
        group = _group(config, group_id)
        channels = group.get('outputs')
        if not isinstance(channels, list) or not channels:
            return False, 'This virtual switcher has no assigned outputs.'
        if any(type(channel) is not int or not 0 <= channel < 6 for channel in channels) or \
                len(channels) != len(set(channels)):
            return False, 'Virtual switcher has duplicate or unavailable output assignments.'
        if getattr(mx.get('topology'), 'aux_outputs', None) != 6:
            return False, 'Physical OUT routing is unavailable unless exactly six AUX channels are reported.'
        target = data.get('input_source')
        source = _entry(mx, 'input-properties', target) if _integer(target) else None
        if source is None or getattr(source, 'available_aux', None) is not True:
            return False, 'Alignment target is not directly routable to the assigned outputs.'
        projection = _route_projection(connection, mx, config_snapshot, revision)
        group_projection = projection['groups'][group_id]
        if group_projection['routeStatus'] != 'mixed':
            return False, 'Alignment is only available for a currently mixed virtual group.'
        program_id = projection['capabilities'].get('programOutputSourceId')
        if program_id is None or target == program_id:
            return False, 'Alignment cannot target an unknown or Primary M/E Program feed.'
        expected_by_channel = _reviewed_routes(data.get('expected_routes'), channels)
        if expected_by_channel is None:
            return False, 'The reviewed routes are malformed or no longer match group ownership.'
        current_routes = {}
        for channel in channels:
            output = next((item for item in projection['outputs'] if item.get('auxIndex') == channel), None)
            live = _source(mx, 'aux-output-source', channel)
            if not output or output.get('owner') != group_id or output.get('routeStatus') != 'observed' or live is None:
                return False, 'A group output is unavailable, stale, or ownership-conflicted.'
            if expected_by_channel[channel] != live:
                return False, f'OUT {channel + 1} changed after the alignment plan was reviewed.'
            pending = _pending(connection, ('aux', channel), live)
            if pending:
                return False, pending
            current_routes[channel] = live
        outcomes = []
        for channel in channels:
            live = current_routes[channel]
            if live == target:
                outcomes.append({'channel': channel, 'ok': True, 'no_op': True, 'error': None})
                continue
            ok, error = dispatch(connection, 'set_aux_output', {
                'aux_channel': channel, 'input_source': target})
            if ok:
                _record(connection, ('aux', channel), live, target)
            outcomes.append({'channel': channel, 'ok': ok, 'no_op': False, 'error': error})
        return True, {'group_id': group_id, 'target': target, 'revision': revision,
                      'outcomes': outcomes}


def review_unconfirmed(connection, kind, channel=0):
    """Explicit read-only reconciliation after timeout; never retries a write."""
    with _lock:
        if kind not in ('me', 'me_preview', 'style', 'aux', 'usk', 'dsk') or \
                (kind in ('aux', 'usk', 'dsk') and not _integer(channel)):
            return False, 'Unknown dashboard switching operation.'
        mx, reason = _raw(connection)
        if reason:
            return False, reason
        key = ('me', 0) if kind == 'me' else (kind, 0) if kind in ('me_preview', 'style') else (kind, channel)
        if kind == 'usk':
            live = _usk_on_air(mx, channel)
        elif kind == 'dsk':
            live = _dsk_on_air(mx, channel)
        elif kind == 'me_preview':
            live = _source(mx, 'preview-bus-input', 0)
        elif kind == 'style':
            settings = _entry(mx, 'transition-settings', 0)
            live = getattr(settings, 'style', None)
        else:
            live = _source(mx, 'program-bus-input' if kind == 'me' else 'aux-output-source', key[1])
        if live is None:
            return False, 'Current hardware route has not been observed.'
        operations = _operations.get(connection, {})
        operation = operations.get(key)
        if operation and time.monotonic() - operation['since'] < PENDING_SECONDS:
            return False, 'Wait for the current command to settle before reviewing.'
        operations.pop(key, None)
        return True, None
