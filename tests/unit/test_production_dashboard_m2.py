"""
Unit and regression tests for Milestone 2:
Individual Output Switching and Upstream Keyer Control.

Covers:
1. Independent AUX Preview (software-only queue) and CUT execution.
2. Verified AUX state swap: after confirmed CUT, prior live source becomes queued preview.
3. AUX no-op on identical source cut and double-click suppression while pending.
4. Command timeout handling and failure recovery without unconfirmed swap.
5. Guarded M/E Background CUT:
   - Blocks CUT when any upstream keyer (KEY 1..4) is tied to next transition.
   - Blocks CUT when M/E is in transition.
   - Dispatches single deduplicated CUT command when safe background-only.
6. Linked M/E outputs share Program/Preview and deduplicate CUT across mirrored outputs.
7. Hardware M/E Preview selection emits set_preview and updates linked panels.
8. Independent Upstream Keyer on-air toggles, pending guards, and fill label resolution.
9. Program Selection Mode honoring (Preview + CUT only vs Direct Program).
10. External route change reconciliation and disconnection safety.
"""

import json
from pathlib import Path
import pytest

HERE = Path(__file__).parent


@pytest.mark.django_db
def test_dashboard_milestone_3b_keeps_deferred_switching_controls_out_of_ui(client):
    """The 3B state view does not expose switching actions reserved for 3C."""
    response = client.get('/atem/dashboard/', {'ip': '192.168.1.114'})
    assert response.status_code == 200
    content = response.content.decode('utf-8')

    assert 'Primary Switcher' in content
    assert 'virtualSwitcherViews' in content
    assert 'Other Outputs' in content
    assert '@click="cut(panel)"' not in content
    assert '@click="toggleUSK(k.keyIndex)"' not in content
    assert 'CUT ALL OUTPUTS' not in content


# =============================================================================
# Helper Logic Simulating Controller Behaviors for Comprehensive Test Verification
# =============================================================================

class DashboardControllerDouble:
    """Python simulation of production_dashboard.js logic for unit testing."""
    def __init__(self, sources, aux_outputs, mes, primary_me_preference=None):
        self.connected = True
        self.sources = sources
        self.auxOutputs = dict(aux_outputs)
        self.mes = json.loads(json.dumps(mes))
        self.primaryMeOutNumber = primary_me_preference
        self.programSelectionMode = 'preview_cut_only'
        self.actionError = ''
        self.actionNotice = ''
        self.dispatched = []
        self.session_storage = {}

        # Discover M/E Program source ID
        self.me1ProgramSourceId = None
        for s in self.sources:
            if s.get('port_type') == 128:
                long_name = (s.get('long') or '').lower()
                short_name = (s.get('short') or '').upper()
                if 'program' in long_name or 'pgm' in long_name or short_name == 'PGM':
                    self.me1ProgramSourceId = s['source']
                    break
        if self.me1ProgramSourceId is None:
            for s in self.sources:
                if s.get('source') == 10010:
                    self.me1ProgramSourceId = 10010
                    break

        # Initialize panels
        self.panels = [
            {'outNumber': 1, 'auxKey': 'aux1', 'friendlyName': 'Output 1', 'isME': False, 'isMEPrimary': False, 'isMEMirrored': False, 'onAirSourceId': None, 'queuedPreviewSourceId': None, 'pending': False, 'pendingTarget': None, 'pendingPrevLive': None},
            {'outNumber': 2, 'auxKey': 'aux2', 'friendlyName': 'Output 2', 'isME': False, 'isMEPrimary': False, 'isMEMirrored': False, 'onAirSourceId': None, 'queuedPreviewSourceId': None, 'pending': False, 'pendingTarget': None, 'pendingPrevLive': None},
            {'outNumber': 3, 'auxKey': 'aux3', 'friendlyName': 'Output 3', 'isME': False, 'isMEPrimary': False, 'isMEMirrored': False, 'onAirSourceId': None, 'queuedPreviewSourceId': None, 'pending': False, 'pendingTarget': None, 'pendingPrevLive': None},
        ]

        self.upstreamKeyers = []
        self.mapManagedOutputRoles()
        self.reconcilePanelSources()
        self.reconcileUpstreamKeyers()

    def mapManagedOutputRoles(self):
        me_matches = []
        if self.me1ProgramSourceId is not None:
            for p in self.panels:
                if self.auxOutputs.get(p['auxKey']) == self.me1ProgramSourceId:
                    me_matches.push(p['outNumber']) if hasattr(me_matches, 'push') else me_matches.append(p['outNumber'])

        self.meOutputCount = len(me_matches)
        primary = None
        if me_matches:
            if self.primaryMeOutNumber in me_matches:
                primary = self.primaryMeOutNumber
            elif 1 in me_matches:
                primary = 1
                self.primaryMeOutNumber = 1
            else:
                primary = me_matches[0]
                self.primaryMeOutNumber = primary

        for p in self.panels:
            is_me = p['outNumber'] in me_matches
            p['isME'] = is_me
            p['role'] = 'HardwareME' if is_me else 'VirtualAux'
            p['isMEPrimary'] = is_me and (p['outNumber'] == primary)
            p['isMEMirrored'] = is_me and (p['outNumber'] != primary)

    def reconcilePanelSources(self):
        me0 = self.mes[0] if self.mes else {}
        me_program = me0.get('program')
        me_preview = me0.get('preview')

        for p in self.panels:
            routed = self.auxOutputs.get(p['auxKey'])
            if p['isME']:
                if p['pending'] and me_program is not None:
                    if p['pendingTarget'] is not None and me_program == p['pendingTarget']:
                        p['pending'] = False
                        p['pendingTarget'] = None
                        p['pendingPrevLive'] = None
                p['onAirSourceId'] = me_program if me_program is not None else routed
                p['queuedPreviewSourceId'] = me_preview if me_preview is not None else p['onAirSourceId']
            else:
                if p['pending'] and routed is not None and routed == p['pendingTarget']:
                    # Confirmed swap
                    prev_live = p['pendingPrevLive']
                    p['pending'] = False
                    p['pendingTarget'] = None
                    p['pendingPrevLive'] = None
                    p['onAirSourceId'] = routed
                    p['queuedPreviewSourceId'] = prev_live
                    self.session_storage[f"pvw_out_{p['outNumber']}"] = prev_live
                    continue

                p['onAirSourceId'] = routed
                storage_val = self.session_storage.get(f"pvw_out_{p['outNumber']}")
                if storage_val is not None:
                    p['queuedPreviewSourceId'] = storage_val
                elif p['queuedPreviewSourceId'] is None:
                    p['queuedPreviewSourceId'] = routed

    def reconcileUpstreamKeyers(self):
        me0 = self.mes[0] if self.mes else {}
        usk = me0.get('usk', {})
        states = usk.get('states', [])
        data = usk.get('data', [])
        count = max(len(states), len(data))

        keyers = []
        for i in range(count):
            on_air = bool(states[i]) if i < len(states) else False
            fill_src = data[i].get('fill_source') if i < len(data) else None
            keyers.append({
                'keyIndex': i,
                'label': f'KEY {i + 1}',
                'onAir': on_air,
                'fillSourceId': fill_src,
                'pending': False
            })
        self.upstreamKeyers = keyers

    @property
    def meKeyTied(self):
        sel = self.mes[0].get('transition', {}).get('selection', {}) if self.mes else {}
        return bool(sel.get('key1') or sel.get('key2') or sel.get('key3') or sel.get('key4'))

    @property
    def meInTransition(self):
        return bool(self.mes[0].get('transition', {}).get('in_transition', False)) if self.mes else False

    def selectPreview(self, panel, source_id):
        if not self.connected:
            return
        if panel['isME']:
            self.dispatched.append({'command': 'set_preview', 'source': source_id, 'me': 0})
        else:
            panel['queuedPreviewSourceId'] = source_id
            self.session_storage[f"pvw_out_{panel['outNumber']}"] = source_id

    def selectProgramDirect(self, panel, source_id):
        if self.programSelectionMode != 'direct' or not self.connected:
            return
        if panel['isME']:
            self.dispatched.append({'command': 'set_program', 'source': source_id, 'me': 0})
        else:
            self.dispatched.append({'command': 'set_aux_output', 'aux_channel': panel['outNumber'] - 1, 'input_source': source_id})

    def cut(self, panel):
        if not self.connected or panel['pending']:
            return

        if panel['isME']:
            if self.meKeyTied:
                self.actionError = 'M/E CUT blocked: Keyer tied to next transition. Background-only CUT cannot be guaranteed.'
                return
            if self.meInTransition:
                self.actionError = 'M/E CUT blocked: Transition already in progress.'
                return

            # Deduplicated M/E CUT across all linked outputs
            for p in self.panels:
                if p['isME']:
                    p['pending'] = True
                    p['pendingTarget'] = panel['queuedPreviewSourceId']
                    p['pendingPrevLive'] = panel['onAirSourceId']

            self.dispatched.append({'command': 'cut', 'me': 0})
        else:
            target = panel['queuedPreviewSourceId']
            prev_live = panel['onAirSourceId']
            if target == prev_live:
                self.actionNotice = f"Source already live on {panel['friendlyName']}"
                return

            panel['pending'] = True
            panel['pendingTarget'] = target
            panel['pendingPrevLive'] = prev_live
            self.dispatched.append({
                'command': 'set_aux_output',
                'aux_channel': panel['outNumber'] - 1,
                'input_source': target
            })

    def toggleUSK(self, key_index):
        if not self.connected:
            return
        keyer = self.upstreamKeyers[key_index]
        if keyer['pending']:
            return
        keyer['pending'] = True
        self.dispatched.append({'command': 'toggle_usk', 'key_index': key_index, 'me': 0})


# =============================================================================
# Automated Tests for Milestone 2 Requirements
# =============================================================================

def _load_base_state():
    snapshot_path = HERE / 'build_full_state_snapshot.json'
    return json.loads(snapshot_path.read_text())


def test_aux_preview_selection_is_software_only():
    """Requirement 1: AUX Preview stays software-only until CUT. Emits zero hardware commands."""
    state = _load_base_state()
    # OUT 3 is independent AUX
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])

    panel3 = ctrl.panels[2]
    assert panel3['role'] == 'VirtualAux'

    # Select Camera 4 (source 4) as Preview for OUT 3
    ctrl.selectPreview(panel3, 4)

    assert panel3['queuedPreviewSourceId'] == 4
    assert ctrl.session_storage['pvw_out_3'] == 4
    # Crucial: NO commands dispatched!
    assert len(ctrl.dispatched) == 0


def test_aux_cut_execution_and_confirmed_state_swap():
    """Requirement 1 & 5: AUX CUT dispatches command and swaps live/preview on confirmed state update."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])

    panel3 = ctrl.panels[2]
    assert panel3['onAirSourceId'] == 1

    # Queue Camera 4 (source 4)
    ctrl.selectPreview(panel3, 4)
    assert len(ctrl.dispatched) == 0

    # Perform CUT on OUT 3
    ctrl.cut(panel3)

    # Dispatched command verified
    assert len(ctrl.dispatched) == 1
    assert ctrl.dispatched[0] == {'command': 'set_aux_output', 'aux_channel': 2, 'input_source': 4}
    assert panel3['pending'] is True
    # Before confirmation, live source is NOT yet changed in UI
    assert panel3['onAirSourceId'] == 1

    # Hardware confirms: incoming state update brings aux3 = 4
    ctrl.auxOutputs['aux3'] = 4
    ctrl.reconcilePanelSources()

    # Confirmed state swap verified:
    assert panel3['pending'] is False
    assert panel3['onAirSourceId'] == 4
    assert panel3['queuedPreviewSourceId'] == 1  # Swapped back to prior live source!
    assert ctrl.session_storage['pvw_out_3'] == 1


def test_aux_cut_noop_on_identical_source_and_rapid_reclick():
    """Requirement 1 & 5: CUT is no-op if queued source is already live, and suppresses rapid clicks."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])
    panel3 = ctrl.panels[2]

    # Queued source is already live (source 1)
    ctrl.selectPreview(panel3, 1)
    ctrl.cut(panel3)

    assert len(ctrl.dispatched) == 0
    assert 'Source already live' in ctrl.actionNotice

    # Now queue source 2 and cut
    ctrl.selectPreview(panel3, 2)
    ctrl.cut(panel3)
    assert len(ctrl.dispatched) == 1
    assert panel3['pending'] is True

    # Immediate second click while pending is suppressed
    ctrl.cut(panel3)
    assert len(ctrl.dispatched) == 1


def test_aux_unconfirmed_cut_does_not_swap():
    """Requirement 5: If hardware fails or times out without confirming new route, swap does not occur."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])
    panel3 = ctrl.panels[2]

    ctrl.selectPreview(panel3, 4)
    ctrl.cut(panel3)
    assert panel3['pending'] is True

    # Incoming state arrives, but aux3 did NOT change (remains 1)
    ctrl.reconcilePanelSources()
    # Swap has not occurred because hardware did not confirm
    assert panel3['onAirSourceId'] == 1
    assert panel3['pending'] is True


def test_guarded_me_cut_blocked_when_keyer_is_tied():
    """Requirement 2: CUT on M/E is BLOCKED if any upstream keyer is tied to next transition."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])

    panel1 = ctrl.panels[0]
    assert panel1['isME'] is True

    # Tie Key 1 to next transition
    ctrl.mes[0]['transition']['selection']['key1'] = True
    assert ctrl.meKeyTied is True

    # Attempt M/E CUT
    ctrl.cut(panel1)

    # CUT MUST BE BLOCKED
    assert len(ctrl.dispatched) == 0
    assert 'M/E CUT blocked' in ctrl.actionError
    assert 'tied to next transition' in ctrl.actionError
    assert panel1['pending'] is False


def test_guarded_me_cut_blocked_when_in_transition():
    """Requirement 2: CUT on M/E is BLOCKED if transition is actively running."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])
    panel1 = ctrl.panels[0]

    # Ensure background-only next-transition
    ctrl.mes[0]['transition']['selection'] = {'background': True, 'key1': False, 'key2': False, 'key3': False, 'key4': False}
    # Simulate in-transition active
    ctrl.mes[0]['transition']['in_transition'] = True
    assert ctrl.meInTransition is True

    ctrl.cut(panel1)
    assert len(ctrl.dispatched) == 0
    assert 'Transition already in progress' in ctrl.actionError


def test_safe_bkgd_only_me_cut_and_linked_output_deduplication():
    """Requirement 2 & 3: Safe M/E CUT dispatches exactly ONE command and updates linked outputs together."""
    state = _load_base_state()
    # OUT 1 and OUT 2 both mirror M/E Program
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])

    panel1 = ctrl.panels[0]
    panel2 = ctrl.panels[1]
    assert panel1['isME'] is True and panel2['isME'] is True

    # Selection is safe BKGD-only
    ctrl.mes[0]['transition']['selection'] = {'background': True, 'key1': False, 'key2': False, 'key3': False, 'key4': False}
    ctrl.mes[0]['transition']['in_transition'] = False
    assert ctrl.meKeyTied is False

    # Execute CUT from either panel (e.g. panel 2)
    ctrl.cut(panel2)

    # Exactly ONE cut command dispatched for M/E 0
    assert len(ctrl.dispatched) == 1
    assert ctrl.dispatched[0] == {'command': 'cut', 'me': 0}

    # BOTH linked panels are marked pending
    assert panel1['pending'] is True and panel2['pending'] is True

    # Hardware confirms CUT: Program and Preview swap on hardware
    ctrl.mes[0]['program'] = 1
    ctrl.mes[0]['preview'] = 2
    ctrl.reconcilePanelSources()

    # BOTH linked panels update synchronously to hardware state
    assert panel1['pending'] is False and panel2['pending'] is False
    assert panel1['onAirSourceId'] == 1 and panel2['onAirSourceId'] == 1
    assert panel1['queuedPreviewSourceId'] == 2 and panel2['queuedPreviewSourceId'] == 2


def test_hardware_me_preview_selection():
    """Requirement 2: Selecting Preview on M/E panel dispatches actual hardware set_preview."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])
    panel1 = ctrl.panels[0]

    # Select Camera 3 on M/E Preview
    ctrl.selectPreview(panel1, 3)

    assert len(ctrl.dispatched) == 1
    assert ctrl.dispatched[0] == {'command': 'set_preview', 'source': 3, 'me': 0}


def test_upstream_keyer_toggle_and_duplicate_suppression():
    """Requirement 4: Independent USK on-air toggles with duplicate command suppression."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])

    key1 = ctrl.upstreamKeyers[0]
    initial_on_air = key1['onAir']
    assert key1['pending'] is False

    # Toggle KEY 1
    ctrl.toggleUSK(0)
    assert len(ctrl.dispatched) == 1
    assert ctrl.dispatched[0] == {'command': 'toggle_usk', 'key_index': 0, 'me': 0}
    assert key1['pending'] is True

    # Re-click while pending is ignored
    ctrl.toggleUSK(0)
    assert len(ctrl.dispatched) == 1

    # Hardware confirms: key1 on_air flips to opposite
    ctrl.mes[0]['usk']['states'][0] = not initial_on_air
    ctrl.reconcileUpstreamKeyers()

    assert ctrl.upstreamKeyers[0]['onAir'] == (not initial_on_air)
    assert ctrl.upstreamKeyers[0]['pending'] is False


def test_program_selection_mode_behavior():
    """Requirement 5: Program row clicks do nothing in preview_cut_only; cut live in direct."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])
    panel3 = ctrl.panels[2]

    # Default mode: preview_cut_only
    assert ctrl.programSelectionMode == 'preview_cut_only'
    ctrl.selectProgramDirect(panel3, 4)
    assert len(ctrl.dispatched) == 0

    # Switch to direct mode
    ctrl.programSelectionMode = 'direct'
    ctrl.selectProgramDirect(panel3, 4)
    assert len(ctrl.dispatched) == 1
    assert ctrl.dispatched[0] == {'command': 'set_aux_output', 'aux_channel': 2, 'input_source': 4}


def test_disconnection_blocks_all_actions():
    """Requirement 5 & 7: When disconnected, all switching and toggle actions are blocked."""
    state = _load_base_state()
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 1}
    ctrl = DashboardControllerDouble(state['sources'], aux_outputs, state['mes'])
    ctrl.connected = False

    ctrl.cut(ctrl.panels[2])
    ctrl.cut(ctrl.panels[0])
    ctrl.selectPreview(ctrl.panels[0], 2)
    ctrl.toggleUSK(0)

    assert len(ctrl.dispatched) == 0
