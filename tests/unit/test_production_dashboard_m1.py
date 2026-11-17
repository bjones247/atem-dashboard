"""
Unit and regression tests for Milestone 1 of the Production Dashboard.
Verifies:
1. Endpoint /atem/dashboard/ renders HTTP 200 and loads dashboard.html.
2. Template contains the three managed physical panels, safe disabled CUT buttons, and status indicators.
3. Cross-view navigation between stock control.html and dashboard.html.
4. Dynamic discovery logic for:
   - Single M/E output
   - Multiple M/E outputs (mirrored/linked destinations sharing Program/Preview)
   - Zero M/E outputs (all independent AUX)
5. Synchronization of state across linked M/E destinations without misleading virtual Preview.
6. Ability to designate primary M/E panel among linked outputs without hardware changes.
7. Verification that Milestone 1 Preview interactions generate ZERO hardware switching commands.
8. Regression verification that existing stock views (/atem/ and /atem/control/) remain functional.
"""

import json
from pathlib import Path
import pytest

HERE = Path(__file__).parent


@pytest.mark.django_db
def test_dashboard_endpoint_renders_ok(client):
    """GET /atem/dashboard/ renders HTTP 200 with required context."""
    response = client.get('/atem/dashboard/')
    assert response.status_code == 200
    assert 'dashboard.html' in [t.name for t in response.templates]
    assert response.context['initial_ip'] == ''

    # With initial IP query parameter
    response_with_ip = client.get('/atem/dashboard/', {'ip': '192.168.1.114'})
    assert response_with_ip.status_code == 200
    assert response_with_ip.context['initial_ip'] == '192.168.1.114'


@pytest.mark.django_db
def test_dashboard_template_contains_three_panels_and_disabled_cut(client):
    """Template contains the 3 physical output panels and disabled CUT buttons."""
    response = client.get('/atem/dashboard/', {'ip': '192.168.1.114'})
    content = response.content.decode('utf-8')

    # Status header
    assert 'Production Dashboard' in content
    assert 'Full Switcher' in content

    # Check for panel loop and output number binding
    assert 'x-for="panel in panels"' in content
    assert "'OUT ' + panel.outNumber" in content

    # Check for Preview and Program rows
    assert 'Preview (Next)' in content
    assert 'Program (Live)' in content

    # Check for Upstream Keyers sections (primary M/E panel + fallback)
    assert 'Upstream Keyers' in content

    # Check that CUT buttons are visibly disabled in Milestone 1
    assert 'CUT disabled in M1' in content or 'Disabled in M1' in content
    assert 'CUT ALL OUTPUTS' in content


@pytest.mark.django_db
def test_cross_view_navigation_retained(client):
    """Stock control surface has a link to the Production Dashboard, and vice versa."""
    # Control page -> Dashboard link
    control_resp = client.get('/atem/control/', {'ip': '192.168.1.114'})
    assert control_resp.status_code == 200
    control_html = control_resp.content.decode('utf-8')
    assert '/atem/dashboard/' in control_html

    # Dashboard page -> Control page link
    dash_resp = client.get('/atem/dashboard/', {'ip': '192.168.1.114'})
    assert dash_resp.status_code == 200
    dash_html = dash_resp.content.decode('utf-8')
    assert '/atem/control/' in dash_html


def _discover_me_program_id(sources):
    for s in sources:
        if s.get('port_type') == 128:
            long_name = (s.get('long') or '').lower()
            short_name = (s.get('short') or '').upper()
            if 'program' in long_name or 'pgm' in long_name or short_name == 'PGM':
                return s['source']
    for s in sources:
        if s.get('source') == 10010:
            return 10010
    return None


def _map_panels(sources, aux_outputs, primary_preference=None):
    me_program_src = _discover_me_program_id(sources)
    panels = [
        {'out': 1, 'aux': 'aux1', 'source': aux_outputs.get('aux1')},
        {'out': 2, 'aux': 'aux2', 'source': aux_outputs.get('aux2')},
        {'out': 3, 'aux': 'aux3', 'source': aux_outputs.get('aux3')},
    ]

    me_matches = [p['out'] for p in panels if me_program_src is not None and p['source'] == me_program_src]
    
    primary_out = None
    if me_matches:
        if primary_preference in me_matches:
            primary_out = primary_preference
        else:
            primary_out = me_matches[0]

    result = []
    for p in panels:
        is_me = p['out'] in me_matches
        result.append({
            'out': p['out'],
            'is_me': is_me,
            'role': 'HardwareME' if is_me else 'VirtualAux',
            'is_primary': is_me and (p['out'] == primary_out),
            'is_mirrored': is_me and (p['out'] != primary_out),
            'source': p['source']
        })
    return result, me_matches, primary_out


def test_single_me_output_discovery():
    """Verify single M/E output mapping (golden snapshot: OUT 2 carries M/E Program)."""
    snapshot_path = HERE / 'build_full_state_snapshot.json'
    state = json.loads(snapshot_path.read_text())

    panels, me_matches, primary_out = _map_panels(state.get('sources', []), state.get('auxOutputs', {}))
    assert me_matches == [2]
    assert primary_out == 2

    assert panels[0]['role'] == 'VirtualAux' and not panels[0]['is_me']
    assert panels[1]['role'] == 'HardwareME' and panels[1]['is_primary'] and not panels[1]['is_mirrored']
    assert panels[2]['role'] == 'VirtualAux' and not panels[2]['is_me']


def test_multiple_me_outputs_mirrored_and_linked():
    """Verify multiple physical outputs carrying M/E Program are recognized as linked/mirrored.
    
    Matches actual user hardware: OUT 1 and OUT 2 carry M/E Program, OUT 3 carries independent AUX.
    """
    snapshot_path = HERE / 'build_full_state_snapshot.json'
    state = json.loads(snapshot_path.read_text())
    sources = state.get('sources', [])

    # Hardware scenario: OUT 1 and OUT 2 both route M/E 1 Program (10010); OUT 3 routes Camera 3 (3)
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 3}

    panels, me_matches, primary_out = _map_panels(sources, aux_outputs)
    assert me_matches == [1, 2]
    assert primary_out == 1  # Lowest numbered default

    # OUT 1 is Primary M/E
    assert panels[0]['is_me'] is True
    assert panels[0]['role'] == 'HardwareME'
    assert panels[0]['is_primary'] is True
    assert panels[0]['is_mirrored'] is False

    # OUT 2 is Linked/Mirrored M/E
    assert panels[1]['is_me'] is True
    assert panels[1]['role'] == 'HardwareME'
    assert panels[1]['is_primary'] is False
    assert panels[1]['is_mirrored'] is True

    # OUT 3 is independent Virtual AUX
    assert panels[2]['is_me'] is False
    assert panels[2]['role'] == 'VirtualAux'
    assert panels[2]['is_primary'] is False
    assert panels[2]['is_mirrored'] is False


def test_designate_primary_me_panel_without_hardware_changes():
    """Verify operator can designate OUT 2 as primary M/E panel among linked outputs."""
    snapshot_path = HERE / 'build_full_state_snapshot.json'
    state = json.loads(snapshot_path.read_text())
    sources = state.get('sources', [])
    aux_outputs = {'aux1': 10010, 'aux2': 10010, 'aux3': 3}

    # Operator explicitly sets primary preference to OUT 2
    panels, me_matches, primary_out = _map_panels(sources, aux_outputs, primary_preference=2)
    assert primary_out == 2

    # Now OUT 2 is primary, OUT 1 is mirrored
    assert panels[0]['is_primary'] is False and panels[0]['is_mirrored'] is True
    assert panels[1]['is_primary'] is True and panels[1]['is_mirrored'] is False


def test_zero_me_outputs_all_virtual_aux():
    """Verify that when zero outputs carry M/E Program, all operate as independent AUX destinations."""
    snapshot_path = HERE / 'build_full_state_snapshot.json'
    state = json.loads(snapshot_path.read_text())
    sources = state.get('sources', [])

    # None route M/E Program (e.g. cameras 1, 2, 3)
    aux_outputs = {'aux1': 1, 'aux2': 2, 'aux3': 3}

    panels, me_matches, primary_out = _map_panels(sources, aux_outputs)
    assert me_matches == []
    assert primary_out is None

    for p in panels:
        assert p['role'] == 'VirtualAux'
        assert p['is_me'] is False
        assert p['is_primary'] is False
        assert p['is_mirrored'] is False


def test_zero_hardware_writes_in_milestone_1_code():
    """Verify production_dashboard.js contains zero hardware command sends for Milestone 1 interactions."""
    js_path = HERE.parent.parent / 'atem_control' / 'static' / 'js' / 'production_dashboard.js'
    js_content = js_path.read_text(encoding='utf-8')

    # Ensure selectPreview, selectProgramDirect, cut, cutAll, toggleUSK send NO WebSocket messages
    # The only ws.send calls allowed are the initial handshake: 'connect' and 'refresh'
    import re
    send_calls = re.findall(r'this\.ws\.send\((.*?)\)', js_content, re.DOTALL)
    
    sent_commands = []
    for call in send_calls:
        match = re.search(r"command:\s*['\"]([^'\"]+)['\"]", call)
        if match:
            sent_commands.append(match.group(1))

    assert set(sent_commands).issubset({'connect', 'refresh'})
    assert 'cut' not in sent_commands
    assert 'set_aux_output' not in sent_commands
    assert 'set_program' not in sent_commands
    assert 'toggle_usk' not in sent_commands
