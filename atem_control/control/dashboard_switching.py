"""Conservative, dashboard-only switching preflight on the pooled ATEM connection.

The stock WebATEM verbs remain unchanged. A preflight and enqueue are serialized
per process, but another ATEM controller can change state between them; observed
hardware state, never command acceptance, remains the source of truth.
"""

import threading
import time
import weakref

from atem_control.control.commands import dispatch


MAX_RX_AGE = 4.0  # atemwire re-handshakes after roughly five quiet seconds
PENDING_SECONDS = 3.0
_lock = threading.RLock()
_operations = weakref.WeakKeyDictionary()


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
    if live == operation['target'] or (live is not None and live != operation['before']):
        operations.pop(key, None)
        return None
    if time.monotonic() - operation['since'] >= PENDING_SECONDS:
        operation['uncertain'] = True
        return 'Previous command is unconfirmed. Review current hardware state before another CUT.'
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
        if getattr(program_source, 'available_me1', None) is not True or getattr(preview_source, 'available_me1', None) is not True:
            return 'M/E Program or Preview source is not confirmed as routable.', program, preview
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
        frames_remaining = getattr(position, 'frames_remaining', None)
        if not _integer(frames_remaining) or frames_remaining != 0:
            return 'M/E transition frame count is unknown or not at rest.', program, preview
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
        return {'fresh': freshness_reason is None,
                'meCut': {'reason': reason, 'program': program, 'preview': preview}, 'aux': aux}


def _record(connection, key, before, target):
    operations = _operations.setdefault(connection, {})
    operations[key] = {'before': before, 'target': target, 'since': time.monotonic(), 'uncertain': False}


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


def review_unconfirmed(connection, kind, channel=0):
    """Explicit read-only reconciliation after timeout; never retries a write."""
    with _lock:
        if kind not in ('me', 'aux') or (kind == 'aux' and not _integer(channel)):
            return False, 'Unknown dashboard switching operation.'
        mx, reason = _raw(connection)
        if reason:
            return False, reason
        key = ('me', 0) if kind == 'me' else ('aux', channel)
        live = _source(mx, 'program-bus-input' if kind == 'me' else 'aux-output-source', key[1])
        if live is None:
            return False, 'Current hardware route has not been observed.'
        operations = _operations.get(connection, {})
        operation = operations.get(key)
        if operation and time.monotonic() - operation['since'] < PENDING_SECONDS:
            return False, 'Wait for the current command to settle before reviewing.'
        operations.pop(key, None)
        return True, None
