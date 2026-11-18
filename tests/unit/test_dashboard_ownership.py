"""Offline tests for dynamic route projection and saved ownership."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from atem_control.control.dashboard_ownership import project_routes, validate_config_against_state
from atem_control.models import dashboard_device_defaults


def node(index, name, port_type=0, available_aux=True, short_name=''):
    return SimpleNamespace(index=index, name=name, short_name=short_name,
                           port_type=port_type, available_aux=available_aux)


def state(aux_count=6, routes=None, program_id=90010, program_label='M/E 1 Program'):
    sources = {
        program_id: node(program_id, program_label, 128, True, 'M1G'),
        90011: node(90011, 'M/E 1 Preview', 128, True, 'M1L'),
        1: node(1, 'Camera 1', 0),
        2: node(2, 'Camera 2', 0),
        8001: node(8001, 'AUX output source 1', 129, True),
        8002: node(8002, 'AUX output source 2', 129, True),
    }
    return {
        'topology': SimpleNamespace(aux_outputs=aux_count),
        'input-properties': sources,
            'aux-output-source': {
            channel: SimpleNamespace(source=source)
            for channel, source in (routes if routes is not None else {
                0: program_id, 1: 1, 2: 2, 3: 1, 4: 2, 5: 1,
            }).items()
        },
        'program-bus-input': {0: SimpleNamespace(source=1)},
    }


def config_with(**group_values):
    config = deepcopy(dashboard_device_defaults())
    for group_id, values in group_values.items():
        config['virtualSwitchers'][group_id].update(values)
    return config


def test_maps_six_physical_outputs_to_installation_aux_indices():
    projected = project_routes(state())

    assert projected['capabilities']['auxOutputCount'] == 6
    assert projected['capabilities']['physicalOutputCount'] == 6
    assert projected['capabilities']['outputMappingStatus'] == 'ready'
    assert [item['outputId'] for item in projected['outputs']] == [1, 2, 3, 4, 5, 6]
    assert [item['auxIndex'] for item in projected['outputs']] == [0, 1, 2, 3, 4, 5]
    assert [item['displayName'] for item in projected['outputs']] == [
        'OUT 1', 'OUT 2', 'OUT 3', 'OUT 4', 'OUT 5', 'OUT 6',
    ]
    assert [item['commandChannel'] for item in projected['outputs']] == [0, 1, 2, 3, 4, 5]
    assert [item['liveSourceId'] for item in projected['outputs']] == [90010, 1, 2, 1, 2, 1]
    assert projected['outputs'][0]['connectorMapping'] == 'installation_convention'
    assert projected['outputs'][0]['mappingSource'] == 'installation_convention'
    assert projected['capabilities']['connectorMapping'] == 'installation_convention'
    assert {source['sourceId'] for source in projected['sources']} == {
        1, 2, 8001, 8002, 90010, 90011,
    }


@pytest.mark.parametrize('count', [None, 0, 5, 7])
def test_incomplete_or_unexpected_aux_topology_blocks_physical_output_mapping(count):
    projected = project_routes(state(aux_count=count, routes={0: 90010, 1: 1}))

    assert [item['displayName'] for item in projected['outputs'][:6]] == [
        'OUT 1', 'OUT 2', 'OUT 3', 'OUT 4', 'OUT 5', 'OUT 6',
    ]
    assert projected['capabilities']['outputMappingStatus'] == 'topology_mismatch'
    assert projected['capabilities']['outputMappingReason']
    assert all(item['available'] is False and item['commandChannel'] is None
               for item in projected['outputs'][:6])
    assert all(item['owner'] == 'unresolved' and item['liveSourceId'] is None
               for item in projected['outputs'][:6])
    assert any(item['type'] == 'installation_topology_mismatch'
               for item in validate_config_against_state(
                   state(aux_count=count, routes={0: 90010, 1: 1}),
                   config_with(virtual1={'outputs': [0]})))


def test_primary_output_identity_is_resolved_from_discovered_source_catalog():
    projected = project_routes(state(routes={0: 90010, 1: 1}, program_id=90010))

    assert projected['capabilities']['programOutputSourceId'] == 90010
    assert projected['primaryOutputIds'] == [1]
    assert projected['outputs'][0]['owner'] == 'primary'
    assert projected['programBackgroundSourceId'] == 1


def test_ambiguous_primary_feed_is_exposed_as_unresolved_not_other():
    projected = project_routes(state(routes={0: 90010}, program_label='Custom Out'))

    assert projected['capabilities']['programOutputSourceId'] is None
    assert projected['outputs'][0]['owner'] == 'unresolved'
    assert any(c['type'] == 'primary_route_identity_unknown' for c in projected['conflicts'])


def test_saved_virtual_outputs_get_exclusive_ownership_and_group_live_projection():
    config = config_with(virtual1={'outputs': [1, 2], 'programTarget': 1, 'previewSource': 2})
    projected = project_routes(state(routes={0: 90010, 1: 1, 2: 1, 3: 2}),
                               {'deviceId': 'a' * 32, 'revision': 3, 'config': config})

    assert projected['outputs'][0]['owner'] == 'primary'
    assert projected['outputs'][1]['owner'] == 'virtual1'
    assert projected['outputs'][2]['owner'] == 'virtual1'
    assert projected['outputs'][3]['owner'] == 'other'
    group = projected['groups']['virtual1']
    assert group['outputIds'] == [2, 3]
    assert group['routeStatus'] == 'uniform'
    assert group['liveSourceId'] == 1
    assert group['programStatus'] == 'matched'
    assert group['previewSourceId'] == 2
    assert group['savedProgramTargetId'] == 1
    assert projected['revision'] == 3
    assert projected['deviceId'] == 'a' * 32


def test_divergent_routes_are_mixed_without_substituting_saved_program_target():
    config = config_with(virtual1={'outputs': [1, 2], 'programTarget': 1, 'previewSource': 2})
    before = deepcopy(config)
    projected = project_routes(state(routes={0: 90010, 1: 1, 2: 2}), config)

    assert projected['groups']['virtual1']['routeStatus'] == 'mixed'
    assert projected['groups']['virtual1']['programStatus'] == 'mixed'
    assert projected['groups']['virtual1']['liveSourceId'] is None
    assert projected['groups']['virtual1']['savedProgramTargetId'] == 1
    assert config == before  # Projection never rewrites saved state.


def test_duplicate_ownership_and_within_group_duplicates_are_reported():
    config = config_with(virtual1={'outputs': [1, 1]}, virtual2={'outputs': [1]})
    projected = project_routes(state(), config)
    kinds = {conflict['type'] for conflict in projected['conflicts']}

    assert 'duplicate_assignment' in kinds
    assert 'duplicate_ownership' in kinds
    assert projected['outputs'][1]['owner'] == 'unresolved'


def test_saved_unavailable_output_and_invalid_sources_are_not_silently_dropped():
    config = config_with(virtual1={
        'outputs': [8], 'previewSource': 999, 'programTarget': 90012,
    })
    projected = project_routes(state(), config)
    conflicts = {(item['type'], item.get('outputId'), item.get('sourceId'), item.get('auxIndex'))
                 for item in projected['conflicts']}

    assert ('unavailable_output', None, None, 8) in conflicts
    assert ('invalid_saved_source', None, 999, None) in conflicts
    assert ('invalid_saved_source', None, 90012, None) in conflicts
    assert projected['groups']['virtual1']['outputIds'] == [None]
    assert projected['groups']['virtual1']['previewSourceValid'] is False


def test_saved_source_present_in_catalog_but_unavailable_for_aux_is_a_conflict():
    mx = state()
    mx['input-properties'][2].available_aux = False
    config = config_with(virtual1={'previewSource': 2, 'programTarget': 2})

    conflicts = validate_config_against_state(mx, config)

    assert [item['field'] for item in conflicts if item['type'] == 'invalid_saved_source'] == [
        'previewSource', 'programTarget',
    ]


def test_missing_topology_does_not_promote_observed_route_to_writable_output():
    mx = state(routes={4: 1})
    mx['topology'] = None
    projected = project_routes(mx)

    assert len(projected['outputs']) == 6
    assert projected['outputs'][4]['outputId'] == 5
    assert projected['outputs'][4]['auxRouteObserved'] is True
    assert projected['outputs'][4]['routeObserved'] is False
    assert projected['outputs'][4]['available'] is False
    assert projected['outputs'][4]['commandChannel'] is None
    assert validate_config_against_state(mx, config_with(virtual1={'outputs': [4]}))


def test_stale_state_exposes_last_observed_routes_without_claiming_current_ownership():
    config = config_with(virtual1={'outputs': [1], 'programTarget': 1})
    projected = project_routes(state(routes={0: 90010, 1: 1}), config, state_fresh=False)

    assert projected['stateFresh'] is False
    assert projected['outputs'][0]['owner'] == 'unknown'
    assert projected['outputs'][0]['liveSourceId'] is None
    assert projected['outputs'][0]['lastObservedSourceId'] == 90010
    assert projected['groups']['virtual1']['routeStatus'] == 'unknown'
    assert projected['primaryDestinationStatus'] == 'unknown'


def test_external_route_change_updates_projection_and_reports_primary_conflict():
    config = config_with(virtual1={'outputs': [1], 'programTarget': 1})
    first = project_routes(state(routes={0: 90010, 1: 1}), config)
    # Another operator changes channel 1 to the M/E Program feed. The saved
    # group assignment remains untouched and ownership becomes unresolved.
    external = project_routes(state(routes={0: 90010, 1: 90010}), config)

    assert first['groups']['virtual1']['programStatus'] == 'matched'
    assert external['outputs'][1]['owner'] == 'unresolved'
    assert external['outputs'][1]['observedRouteOwner'] == 'primary'
    assert external['primaryOutputIds'] == [1, 2]
    assert external['groups']['virtual1']['programStatus'] == 'divergent'
    assert any(c['type'] == 'primary_virtual_ownership_conflict'
               for c in external['conflicts'])
    assert config['virtualSwitchers']['virtual1']['outputs'] == [1]


def test_observed_routes_change_on_reconnect_without_commands_or_saved_state_changes():
    config = config_with(virtual2={'outputs': [2], 'programTarget': 1})
    first = project_routes(state(routes={0: 90010, 2: 1}), config)
    reconnected = project_routes(state(routes={0: 90010, 2: 2}), config)

    assert first['groups']['virtual2']['liveSourceId'] == 1
    assert reconnected['groups']['virtual2']['liveSourceId'] == 2
    assert reconnected['groups']['virtual2']['programStatus'] == 'divergent'
    assert config['virtualSwitchers']['virtual2']['programTarget'] == 1

