"""Read-only route projection and saved-output ownership reconciliation.

This installation maps OUT 1–6 to AUX 1–6. AuxS/CAuS use AUX indices 0–5;
the fixed installation convention maps index ``n`` to physical OUT ``n + 1``.
The AUX index remains internal for routing and saved configuration. This is
an installation convention, not a mapping discovered or confirmed by ATEM.
"""

from collections import defaultdict


VIRTUAL_GROUPS = ('virtual1', 'virtual2')
PORT_ME_OUTPUT = 128
PORT_AUX_OUTPUT = 129
PHYSICAL_OUTPUT_COUNT = 6


def _physical_output_number(aux_index):
    return aux_index + 1 if type(aux_index) is int and 0 <= aux_index < PHYSICAL_OUTPUT_COUNT else None


def _nonnegative_int(value):
    return type(value) is int and value >= 0


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _source_catalog(mx):
    catalog = {}
    for key, node in _mapping(mx.get('input-properties')).items():
        source_id = key if _nonnegative_int(key) else getattr(node, 'index', None)
        if not _nonnegative_int(source_id) or node is None:
            continue
        catalog[source_id] = {
            'sourceId': source_id,
            'name': getattr(node, 'name', '') or '',
            'shortName': getattr(node, 'short_name', '') or '',
            'portType': getattr(node, 'port_type', None),
            'availableAux': getattr(node, 'available_aux', None) is True,
        }
    return catalog


def _program_output_id(sources):
    """Resolve the M/E Program output only from an unambiguous device label.

    The input-properties port type identifies M/E output sources but does not
    distinguish Program from Preview. Names can be customized, so ambiguity
    or a renamed/unrecognized label leaves this unresolved and fails closed.
    """
    candidates = []
    for source_id, source in sources.items():
        if source['portType'] != PORT_ME_OUTPUT:
            continue
        label = f"{source['name']} {source['shortName']}".casefold()
        if 'program' in label or 'pgm' in label:
            candidates.append(source_id)
    return candidates[0] if len(candidates) == 1 else None


def _aux_capability_count(mx):
    topology = mx.get('topology')
    count = getattr(topology, 'aux_outputs', None)
    return count if _nonnegative_int(count) else None


def _route_source(route):
    source = getattr(route, 'source', None)
    return source if _nonnegative_int(source) else None


def _saved_group(config, group_id):
    groups = _mapping(config.get('virtualSwitchers'))
    value = groups.get(group_id)
    return value if isinstance(value, dict) else {}


def _config_conflicts(mx, config, destinations, sources, program_output_id, state_fresh):
    conflicts = []
    claims = defaultdict(list)
    for group_id in VIRTUAL_GROUPS:
        group = _saved_group(config, group_id)
        outputs = group.get('outputs', [])
        if not isinstance(outputs, list):
            conflicts.append({'type': 'malformed_assignment', 'group': group_id})
            continue
        seen = set()
        for output_id in outputs:
            physical_output = _physical_output_number(output_id)
            if not _nonnegative_int(output_id):
                conflicts.append({'type': 'malformed_assignment', 'group': group_id,
                                  'outputId': None, 'auxIndex': output_id})
                continue
            if output_id in seen:
                conflicts.append({'type': 'duplicate_assignment', 'group': group_id,
                                  'outputId': physical_output, 'auxIndex': output_id})
            seen.add(output_id)
            claims[output_id].append(group_id)
            if output_id not in destinations:
                conflicts.append({'type': 'unavailable_output', 'group': group_id,
                                  'outputId': physical_output, 'auxIndex': output_id})

        for field in ('previewSource', 'programTarget'):
            source_id = group.get(field)
            if source_id is not None and (
                    not _nonnegative_int(source_id) or source_id not in sources or
                    sources[source_id]['availableAux'] is not True):
                conflicts.append({'type': 'invalid_saved_source', 'group': group_id,
                                  'field': field, 'sourceId': source_id})

    routes = _mapping(mx.get('aux-output-source'))
    count = _aux_capability_count(mx)
    mapping_ready = count == PHYSICAL_OUTPUT_COUNT
    if not mapping_ready:
        conflicts.append({
            'type': 'installation_topology_mismatch',
            'expectedAuxOutputCount': PHYSICAL_OUTPUT_COUNT,
            'auxOutputCount': count,
            'reason': (f'This installation requires {PHYSICAL_OUTPUT_COUNT} AUX channels '
                       f'(AUX 1–{PHYSICAL_OUTPUT_COUNT}); ATEM reported '
                       f'{count if count is not None else "no topology count"}.'),
        })
    if state_fresh and count is not None:
        for channel in sorted(key for key in routes if _nonnegative_int(key) and key >= count):
            conflicts.append({'type': 'unexpected_aux_route',
                              'outputId': _physical_output_number(channel), 'auxIndex': channel,
                              'auxOutputCount': count})
    for output_id, owners in claims.items():
        physical_output = _physical_output_number(output_id)
        if len(set(owners)) > 1:
            conflicts.append({'type': 'duplicate_ownership', 'outputId': physical_output,
                              'auxIndex': output_id,
                              'groups': sorted(set(owners))})
        if (mapping_ready and state_fresh and program_output_id is not None and
                _route_source(routes.get(output_id)) == program_output_id):
            conflicts.append({'type': 'primary_virtual_ownership_conflict',
                              'outputId': physical_output, 'auxIndex': output_id,
                              'groups': sorted(set(owners))})

    if state_fresh and program_output_id is None:
        for output_id, route in routes.items():
            if not _nonnegative_int(output_id):
                continue
            source = sources.get(_route_source(route))
            if source and source['portType'] == PORT_ME_OUTPUT:
                conflicts.append({'type': 'primary_route_identity_unknown',
                                  'outputId': _physical_output_number(output_id),
                                  'auxIndex': output_id,
                                  'sourceId': source['sourceId']})
    return conflicts, claims


def project_routes(mixerstate, config=None, revision=None, state_fresh=True):
    """Project observed AUX routes and reconcile them with saved ownership.

    Saved assignment IDs and command channels remain zero-based AUX indices.
    Projection records expose physical OUT 1–6 using the configured fixed
    installation convention. The mapping is usable only when topology reports
    exactly six AUX channels. This function never dispatches ATEM commands.
    """
    mx = mixerstate if isinstance(mixerstate, dict) else {}
    config_snapshot = config if isinstance(config, dict) else {}
    if isinstance(config_snapshot.get('config'), dict):
        revision = config_snapshot.get('revision', revision)
        device_id = config_snapshot.get('deviceId')
        config = config_snapshot['config']
    else:
        device_id = config_snapshot.get('deviceId')
        config = config_snapshot
    if not isinstance(config, dict):
        config = {'virtualSwitchers': {}}
    sources = _source_catalog(mx)
    count = _aux_capability_count(mx)
    routes = _mapping(mx.get('aux-output-source'))
    observed_channels = {key for key in routes if _nonnegative_int(key)}

    # Topology is the capability count. AuxS indices are observed routes. Keep
    # unexpected observed indices in the projection as read-only conflicts.
    channels = set(range(PHYSICAL_OUTPUT_COUNT))
    channels.update(observed_channels)
    program_id = _program_output_id(sources)
    mapping_ready = count == PHYSICAL_OUTPUT_COUNT
    capability_channels = set(range(PHYSICAL_OUTPUT_COUNT)) if mapping_ready else set()
    conflicts, claims = _config_conflicts(
        mx, config, capability_channels, sources, program_id, bool(state_fresh))
    conflict_keys = {(item.get('type'), item.get('auxIndex')) for item in conflicts}

    outputs = []
    for channel in sorted(channels):
        physical_output = _physical_output_number(channel)
        aux_route_observed = channel in routes
        observed = mapping_ready and aux_route_observed
        live_source_id = _route_source(routes.get(channel)) if observed else None
        source_info = sources.get(live_source_id)
        owners = sorted(set(claims.get(channel, [])))
        is_program_route = mapping_ready and program_id is not None and live_source_id == program_id
        topology_valid = mapping_ready and physical_output is not None
        output_conflicts = [item for item in conflicts
                            if item.get('auxIndex') == channel or
                            (physical_output is not None and item.get('outputId') == physical_output)]
        if not mapping_ready and physical_output is not None:
            output_conflicts.append({'type': 'installation_topology_mismatch',
                                     'outputId': physical_output, 'auxIndex': channel,
                                     'auxOutputCount': count})
        if not state_fresh:
            output_conflicts.append({'type': 'route_stale', 'outputId': physical_output,
                                     'auxIndex': channel})
        elif not observed:
            output_conflicts.append({'type': 'route_unobserved', 'outputId': physical_output,
                                     'auxIndex': channel})
        elif live_source_id is None:
            output_conflicts.append({'type': 'malformed_route', 'outputId': physical_output,
                                     'auxIndex': channel})
        elif source_info is None:
            output_conflicts.append({'type': 'route_source_missing',
                                     'outputId': physical_output, 'auxIndex': channel,
                                     'sourceId': live_source_id})
        conflicts.extend(item for item in output_conflicts if item not in conflicts)

        if not mapping_ready:
            owner = 'unresolved'
        elif not state_fresh or not observed or live_source_id is None:
            owner = 'unknown'
        elif (not topology_valid or
                ('duplicate_ownership', channel) in conflict_keys or
                ('primary_virtual_ownership_conflict', channel) in conflict_keys or
                ('primary_route_identity_unknown', channel) in conflict_keys or
                source_info is None):
            owner = 'unresolved'
        elif is_program_route:
            owner = 'primary'
        elif len(owners) == 1:
            owner = owners[0]
        else:
            owner = 'other'
        if not mapping_ready or not state_fresh or not observed or live_source_id is None or source_info is None:
            observed_owner = 'unknown'
        elif program_id is None and source_info['portType'] == PORT_ME_OUTPUT:
            observed_owner = 'unknown'
        else:
            observed_owner = 'primary' if is_program_route else 'other'

        outputs.append({
            'outputId': physical_output,
            'physicalOutputNumber': physical_output,
            'auxIndex': channel,
            'mappingSource': 'installation_convention' if physical_output is not None else None,
            'destinationType': 'aux',
            'displayName': (f'OUT {physical_output}' if physical_output is not None
                            else f'Unmapped AUX index {channel}'),
            'connectorId': physical_output,
            'connectorMapping': 'installation_convention' if physical_output is not None else 'unmapped',
            'commandChannel': channel if topology_valid else None,
            'available': topology_valid,
            'routeObserved': observed,
            'auxRouteObserved': aux_route_observed,
            'liveSourceId': live_source_id if state_fresh else None,
            'lastObservedSourceId': _route_source(routes.get(channel)) if not state_fresh else None,
            'liveSource': source_info if state_fresh and mapping_ready else None,
            'routeStatus': ('stale' if not state_fresh else
                            'topology_mismatch' if not mapping_ready else
                            'unobserved' if not observed else
                            'malformed' if live_source_id is None else
                            'source_missing' if source_info is None else 'observed'),
            'owner': owner,
            'observedRouteOwner': observed_owner,
            'savedOwners': owners,
            'conflicts': output_conflicts,
        })

    output_by_aux_index = {item['auxIndex']: item for item in outputs
                           if item['physicalOutputNumber'] is not None}
    groups = {}
    for group_id in VIRTUAL_GROUPS:
        saved = _saved_group(config, group_id)
        assignment_ids = saved.get('outputs', [])
        if not isinstance(assignment_ids, list):
            assignment_ids = []
        assigned = [output_by_aux_index[o] for o in assignment_ids
                    if _nonnegative_int(o) and o in output_by_aux_index]
        route_ids = [item['liveSourceId'] for item in assigned
                     if item['routeObserved'] and item['liveSourceId'] is not None]
        has_unknown = len(assigned) != len(route_ids)
        distinct_routes = set(route_ids)
        if not assigned:
            route_status = 'empty'
            live_source_id = None
        elif len(distinct_routes) > 1:
            route_status = 'mixed'
            live_source_id = None
        elif has_unknown:
            route_status = 'unknown'
            live_source_id = None
        else:
            route_status = 'uniform'
            live_source_id = route_ids[0]

        target = saved.get('programTarget')
        if route_status == 'empty':
            program_status = 'no_outputs'
        elif route_status == 'mixed':
            program_status = 'mixed'
        elif route_status == 'unknown':
            program_status = 'unknown'
        elif live_source_id == target:
            program_status = 'matched'
        else:
            program_status = 'divergent'

        preview = saved.get('previewSource')
        groups[group_id] = {
            'outputIds': [_physical_output_number(o) for o in assignment_ids],
            'outputs': [{'outputId': item['outputId'], 'liveSourceId': item['liveSourceId'],
                         'lastObservedSourceId': item['lastObservedSourceId'],
                         'routeStatus': item['routeStatus']} for item in assigned],
            'previewSourceId': preview,
            'previewSourceValid': (preview is None or (_nonnegative_int(preview) and
                preview in sources and sources[preview]['availableAux'] is True)),
            'savedProgramTargetId': target,
            'routeStatus': route_status,
            'liveSourceId': live_source_id,
            'programStatus': program_status,
        }

    program_bus = _mapping(mx.get('program-bus-input')).get(0)
    program_background = _route_source(program_bus)
    route_inventory_known = all(item['routeStatus'] == 'observed' for item in outputs)
    primary_status = ('unknown' if not state_fresh or program_id is None or not route_inventory_known else
                      'warning' if not any(item['observedRouteOwner'] == 'primary' for item in outputs)
                      else 'observed')
    return {
        'deviceId': device_id,
        'revision': revision,
        'capabilities': {
            'auxOutputCount': count,
            'expectedAuxOutputCount': PHYSICAL_OUTPUT_COUNT,
            'physicalOutputCount': PHYSICAL_OUTPUT_COUNT,
            'outputMappingStatus': 'ready' if mapping_ready else 'topology_mismatch',
            'outputMappingSource': 'installation_convention',
            'outputMappingReason': (None if mapping_ready else
                f'Expected {PHYSICAL_OUTPUT_COUNT} AUX channels for OUT 1–{PHYSICAL_OUTPUT_COUNT}; '
                f'ATEM reported {count if count is not None else "no topology count"}.'),
            'sourceCount': len(sources),
            'outputSourceCount': sum(1 for source in sources.values()
                                     if source['portType'] == PORT_AUX_OUTPUT),
            'programOutputSourceId': program_id,
            'programOutputStatus': 'observed' if program_id is not None else 'unknown',
            'connectorMapping': 'installation_convention',
        },
        'programBackgroundSourceId': program_background,
        'stateFresh': bool(state_fresh),
        'sources': [sources[key] for key in sorted(sources)],
        'outputs': outputs,
        'groups': groups,
        'primaryOutputIds': [item['outputId'] for item in outputs
                             if item['observedRouteOwner'] == 'primary'],
        'otherOutputIds': [item['outputId'] for item in outputs if item['owner'] == 'other'],
        'conflicts': conflicts,
        'minimumPrimaryDestinations': config.get('minimumPrimaryDestinations', True),
        'primaryDestinationWarning': (
            primary_status == 'warning'),
        'primaryDestinationStatus': primary_status,
    }


def validate_config_against_state(mixerstate, config, state_fresh=True):
    """Return only config errors that a proposed edit can safely correct."""
    projection = project_routes(mixerstate, config, state_fresh=state_fresh)
    assignment_ids = set()
    for group_id in VIRTUAL_GROUPS:
        outputs = _saved_group(config, group_id).get('outputs', [])
        if isinstance(outputs, list):
            assignment_ids.update(output for output in outputs if _nonnegative_int(output))

    always_block = {
        'malformed_assignment', 'duplicate_assignment', 'unavailable_output',
        'invalid_saved_source', 'duplicate_ownership',
        'primary_virtual_ownership_conflict', 'installation_topology_mismatch',
    }
    route_block = {
        'route_stale', 'route_unobserved', 'malformed_route',
        'route_source_missing', 'primary_route_identity_unknown',
    }
    return [item for item in projection['conflicts']
            if item['type'] in always_block or
            (item['type'] in route_block and item.get('auxIndex') in assignment_ids)]
