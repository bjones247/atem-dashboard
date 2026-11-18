const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.resolve(__dirname, '../../atem_control/static/js/production_dashboard.js'), 'utf8');

function controller() {
  let factory;
  let nextTimer = 1;
  const timers = new Map();
  const storage = new Map();
  const sent = [];
  const context = {
    document: { addEventListener: (_event, callback) => callback() },
    Alpine: { data: (_name, callback) => { factory = callback; } },
    WebSocket: { OPEN: 1 },
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    sessionStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    setTimeout: (callback) => { const id = nextTimer++; timers.set(id, callback); return id; },
    clearTimeout: (id) => timers.delete(id),
    console,
  };
  vm.runInNewContext(source, context, { filename: 'production_dashboard.js' });
  const dashboard = factory();
  dashboard.ipAddress = '192.0.2.4';
  dashboard.ws = { readyState: 1, send: (data) => sent.push(JSON.parse(data)) };
  return { dashboard, sent, timers };
}

function hardware({ program = 1, preview = 2, aux3 = 1, meReason = null, auxReason = null,
                    usk = [false, false] } = {}) {
  return {
    is_connected: true,
    sources: [
      { source: 1, short: 'IN1', long: 'Input 1', port_type: 0, available_aux: true, available_me1: true },
      { source: 2, short: 'IN2', long: 'Input 2', port_type: 0, available_aux: true, available_me1: true },
      { source: 3, short: 'IN3', long: 'Input 3', port_type: 0, available_aux: true, available_me1: true },
      { source: 1000, short: 'Bars', long: 'Color Bars', port_type: 2, available_aux: true },
      { source: 10010, short: 'PGM', long: 'ME 1 Program', port_type: 128, available_aux: true },
    ],
    auxOutputs: { aux1: 10010, aux2: 10010, aux3 },
    mes: [{ program, preview, transition: { selection: { background: true, key1: false, key2: false, key3: false, key4: false }, in_transition: false },
            usk: { states: usk, data: usk.map(() => ({ fill_source: 1 })) } }],
    dashboardSafety: {
      fresh: true,
      meCut: { reason: meReason, program, preview },
      aux: { '0': { reason: null, live: 10010 }, '1': { reason: null, live: 10010 }, '2': { reason: auxReason, live: aux3 } },
      usk: Object.fromEntries(usk.map((onAir, index) => [String(index), { reason: null, onAir }])),
    },
  };
}

test('linked M/E panels have one live source and send one guarded CUT', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  assert.equal(d.panels[0].onAirSourceId, 1);
  assert.equal(d.panels[1].onAirSourceId, 1);
  assert.equal(d.meCutReason, '');
  d.cut(d.panels[1]);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { command: 'dashboard_cut_me', me: 0, expected_program: 1, expected_preview: 2 });
  assert.equal(d.panels[0].pending, true);
  d.cut(d.panels[0]);
  assert.equal(sent.length, 1);
  d.updateState(hardware({ program: 2, preview: 1 }));
  assert.equal(d.panels[0].onAirSourceId, 2);
  assert.equal(d.panels[1].onAirSourceId, 2);
  assert.equal(d.panels[0].pending, false);
});

test('missing safety, tied key, or disconnect blocks M/E CUT', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware({ meReason: 'M/E transition selection has not been observed.' }));
  d.cut(d.panels[0]);
  assert.equal(sent.length, 0);
  d.updateState(hardware({ meReason: 'KEY 1 tied to next transition.' }));
  d.cut(d.panels[0]);
  assert.equal(sent.length, 0);
  d.handleMessage({ type: 'connection_status', connected: false });
  assert.match(d.meCutReason, /disconnected/i);
  d.cut(d.panels[0]);
  assert.equal(sent.length, 0);
});

test('AUX Preview is virtual; CUT swaps only after hardware route confirms', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  assert.match(d.auxCutReason(panel), /already live/);
  d.selectPreview(panel, 2);
  assert.equal(sent.length, 0);
  assert.equal(d.auxCutReason(panel), '');
  d.cut(panel);
  assert.deepEqual(sent[0], { command: 'dashboard_cut_aux', aux_channel: 2, input_source: 2, expected_live: 1 });
  d.cut(panel);
  assert.equal(sent.length, 1);
  assert.equal(panel.onAirSourceId, 1);
  assert.equal(panel.queuedPreviewSourceId, 2);
  d.updateState(hardware({ aux3: 2 }));
  assert.equal(panel.onAirSourceId, 2);
  assert.equal(panel.queuedPreviewSourceId, 1);
  assert.equal(panel.pending, false);
  d.updateState(hardware({ aux3: 3 }));
  assert.equal(panel.onAirSourceId, 3);
  assert.equal(panel.queuedPreviewSourceId, 1);
  assert.equal(sent.length, 1);
});

test('timeout stays unconfirmed and a late route never creates a stale Preview swap', () => {
  const { dashboard: d, sent, timers } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  d.selectPreview(panel, 2);
  d.cut(panel);
  for (const callback of [...timers.values()]) callback();
  assert.equal(panel.unconfirmed, true);
  assert.equal(panel.onAirSourceId, 1);
  assert.equal(panel.queuedPreviewSourceId, 2);
  d.cut(panel);
  assert.equal(sent.length, 1);
  d.updateState(hardware({ aux3: 2 }));
  assert.equal(panel.onAirSourceId, 2);
  assert.equal(panel.queuedPreviewSourceId, 2);
  assert.equal(panel.unconfirmed, false);
});

test('unavailable queue, external diversion, and server guard reason block AUX CUT', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  panel.queuedPreviewSourceId = 999;
  assert.match(d.auxCutReason(panel), /directly routable/);
  d.cut(panel);
  assert.equal(sent.length, 0);
  d.selectPreview(panel, 2);
  d.updateState(hardware({ aux3: 3, auxReason: 'Previous command is unconfirmed.' }));
  assert.match(d.auxCutReason(panel), /unconfirmed/);
  d.cut(panel);
  assert.equal(sent.length, 0);
});

test('external route during a pending AUX CUT never swaps an invented prior Preview', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  d.selectPreview(panel, 2);
  d.cut(panel);
  d.updateState(hardware({ aux3: 3 }));
  assert.equal(panel.pending, false);
  assert.equal(panel.queuedPreviewSourceId, 2);
  d.updateState(hardware({ aux3: 2 }));
  assert.equal(panel.queuedPreviewSourceId, 2);
  assert.equal(sent.length, 1);
});

test('direct AUX Program selection is pending until observed and does not swap Preview', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  d.programSelectionMode = 'direct';
  d.selectPreview(panel, 3);
  d.selectProgramDirect(panel, 2);
  assert.equal(panel.pending, true);
  assert.equal(panel.onAirSourceId, 1);
  d.selectProgramDirect(panel, 3);
  assert.equal(sent.length, 1);
  d.updateState(hardware({ aux3: 2 }));
  assert.equal(panel.pending, false);
  assert.equal(panel.onAirSourceId, 2);
  assert.equal(panel.queuedPreviewSourceId, 3);
});

test('dashboard role uses the same observed AUX route as live state', () => {
  const { dashboard: d } = controller();
  const state = hardware();
  state.auxOutputs.aux3 = 1; // older projection from a separate state read
  state.dashboardSafety.aux['2'].live = 10010;
  d.updateState(state);
  assert.equal(d.panels[2].isME, true);
  assert.equal(d.panels[2].onAirSourceId, 1);
});

test('command-specific rejection leaves an unrelated pending AUX operation intact', () => {
  const { dashboard: d } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  d.selectPreview(panel, 2);
  d.cut(panel);
  d.handleMessage({ type: 'error', command: 'set_preview', message: 'Rejected' });
  assert.equal(panel.pending, true);
  d.handleMessage({ type: 'error', command: 'dashboard_cut_aux', aux_channel: 2, message: 'Rejected' });
  assert.equal(panel.pending, false);
  assert.equal(panel.unconfirmed, true);
});

test('disconnect makes pending command unconfirmed and reconnect waits for fresh state', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  const panel = d.panels[2];
  d.selectPreview(panel, 2);
  d.cut(panel);
  d.handleMessage({ type: 'connection_status', connected: false });
  assert.equal(panel.unconfirmed, true);
  assert.match(d.auxCutReason(panel), /disconnected/i);
  d.cut(panel);
  assert.equal(sent.length, 1);
  d.handleMessage({ type: 'connection_status', connected: true });
  assert.equal(d.hardwareReady, false);
  d.updateState(hardware({ aux3: 2 }));
  assert.equal(panel.onAirSourceId, 2);
  assert.equal(panel.queuedPreviewSourceId, 2);
});

test('live source remains hardware-derived, including a source outside the grid', () => {
  const { dashboard: d } = controller();
  d.updateState(hardware({ program: 2, aux3: 1000 }));
  assert.equal(d.panels[0].onAirSourceId, 2);
  assert.equal(d.panels[2].onAirSourceId, 1000);
  assert.equal(d.categorizedSources.some((source) => source.source === 1000), false);
  assert.equal(d.getSourceNameById(1000), 'Color Bars');
  d.updateState(hardware({ program: 1, aux3: 3 }));
  assert.equal(d.panels[0].onAirSourceId, 1);
  assert.equal(d.panels[2].onAirSourceId, 3);
});

test('one upstream keyer turns on then off after its own observed confirmations', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  const keyer = d.upstreamKeyers[0];
  d.toggleUSK(0);
  assert.deepEqual(sent[0], { command: 'dashboard_toggle_usk', key_index: 0, expected_on_air: false, target_on_air: true, me: 0 });
  assert.equal(d.upstreamKeyers[0].pending, true);
  d.updateState(hardware({ usk: [true, false] }));
  assert.equal(d.upstreamKeyers[0], keyer);
  assert.equal(d.upstreamKeyers[0].pending, false);
  assert.equal(d.upstreamKeyers[0].statusText, 'ON AIR');
  assert.equal(d.keyerToggleReason(d.upstreamKeyers[0]), '');
  d.toggleUSK(0);
  assert.deepEqual(sent[1], { command: 'dashboard_toggle_usk', key_index: 0, expected_on_air: true, target_on_air: false, me: 0 });
  d.updateState(hardware({ usk: [false, false] }));
  assert.equal(d.upstreamKeyers[0].pending, false);
  assert.equal(d.upstreamKeyers[0].statusText, 'OFF AIR');
});

test('upstream keyers retain independent pending targets and reconcile separately', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(hardware());
  d.toggleUSK(0);
  d.toggleUSK(1);
  assert.equal(sent.length, 2);
  d.updateState(hardware({ usk: [true, false] }));
  assert.equal(d.upstreamKeyers[0].pending, false);
  assert.equal(d.upstreamKeyers[1].pending, true);
  d.updateState(hardware({ usk: [true, true] }));
  assert.equal(d.upstreamKeyers[1].pending, false);
  assert.equal(d.upstreamKeyers[0].statusText, 'ON AIR');
});

function projectedHardware(overrides = {}) {
  const state = hardware({ program: 2, preview: 3 });
  state.dashboardRouting = {
    deviceId: 'a'.repeat(32),
    revision: 4,
    stateFresh: true,
    capabilities: { outputMappingStatus: 'ready', outputMappingReason: null },
    outputs: [
      { outputId: 1, auxIndex: 0, displayName: 'OUT 1', owner: 'primary', observedRouteOwner: 'primary', routeStatus: 'observed', liveSourceId: 10010, conflicts: [] },
      { outputId: 2, auxIndex: 1, displayName: 'OUT 2', owner: 'virtual1', routeStatus: 'observed', liveSourceId: 1, conflicts: [] },
      { outputId: 3, auxIndex: 2, displayName: 'OUT 3', owner: 'other', routeStatus: 'observed', liveSourceId: 3, conflicts: [] },
      { outputId: 4, auxIndex: 3, displayName: 'OUT 4', owner: 'unknown', routeStatus: 'stale', liveSourceId: null, lastObservedSourceId: 2, conflicts: [{ type: 'route_stale', reason: 'Route observation is stale' }] },
      { outputId: 5, auxIndex: 4, displayName: 'OUT 5', owner: 'unresolved', routeStatus: 'observed', liveSourceId: 1, conflicts: [{ type: 'duplicate_ownership', reason: 'Ownership conflict' }] },
      { outputId: 6, auxIndex: 5, displayName: 'OUT 6', owner: 'virtual1', routeStatus: 'observed', liveSourceId: 2, conflicts: [] },
    ],
    primaryOutputIds: [1],
    groups: {
      virtual1: { outputIds: [2, 6], outputs: [
        { outputId: 2, liveSourceId: 1, lastObservedSourceId: null, routeStatus: 'observed' },
        { outputId: 6, liveSourceId: 2, lastObservedSourceId: null, routeStatus: 'observed' },
      ], previewSourceId: 3, previewSourceValid: true, savedProgramTargetId: 1, routeStatus: 'mixed', liveSourceId: null, programStatus: 'mixed' },
      virtual2: { outputIds: [], outputs: [], previewSourceId: null, previewSourceValid: true, savedProgramTargetId: 3, routeStatus: 'empty', liveSourceId: null, programStatus: 'no_outputs' },
    },
    conflicts: [{ type: 'duplicate_ownership', group: 'virtual1', reason: 'Ownership conflict' }],
    ...overrides,
  };
  return state;
}

test('Milestone 3B projection keeps hardware M/E state separate from saved virtual state', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(projectedHardware());
  assert.equal(d.hardwareProgramSourceId, 2);
  assert.equal(d.hardwarePreviewSourceId, 3);
  assert.deepEqual(d.primarySwitcherOutputs.map(output => output.displayName), ['OUT 1']);
  const virtual = d.virtualSwitcherViews[0];
  assert.deepEqual(virtual.outputs.map(output => output.displayName), ['OUT 2', 'OUT 6']);
  assert.equal(virtual.group.previewSourceId, 3);
  assert.equal(virtual.group.savedProgramTargetId, 1);
  assert.equal(virtual.group.routeStatus, 'mixed');
  assert.deepEqual(d.otherOutputViews.map(output => output.displayName), ['OUT 3', 'OUT 4', 'OUT 5']);
  assert.equal(d.outputSourceId(d.otherOutputViews[1]), 2); // stale is labeled last-observed
  assert.match(d.outputConflictText(d.otherOutputViews[2]), /Ownership conflict/);
  assert.deepEqual(sent, [{ command: 'dashboard_config_get' }]);
});

test('Milestone 3B custom names use revision-checked software config only', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(projectedHardware());
  d.acceptDashboardConfig({
    type: 'dashboard_config', deviceId: 'a'.repeat(32), revision: 4,
    config: { schemaVersion: 1, customNames: { primary: null, virtual1: null, virtual2: 'Studio Feed' }, preferences: {}, virtualSwitchers: {}, minimumPrimaryDestinations: true },
  });
  assert.equal(d.virtualSwitcherViews[1].title, 'Studio Feed');
  d.beginNameEdit('virtual1', 'Virtual Switcher 1');
  d.nameDraft = 'Stage';
  d.saveSwitcherName('virtual1');
  assert.deepEqual(sent[1], {
    command: 'dashboard_config_update', expected_revision: 4,
    config: { schemaVersion: 1, customNames: { primary: null, virtual1: 'Stage', virtual2: 'Studio Feed' }, preferences: {}, virtualSwitchers: {}, minimumPrimaryDestinations: true },
  });
  assert.equal(sent.some(message => ['dashboard_cut_me', 'dashboard_cut_aux', 'set_aux_output', 'cut'].includes(message.command)), false);
});

test('Milestone 3B reloads device config when the observed projection revision advances', () => {
  const { dashboard: d, sent } = controller();
  d.updateState(projectedHardware());
  d.acceptDashboardConfig({ type: 'dashboard_config', deviceId: 'a'.repeat(32), revision: 4,
    config: { schemaVersion: 1, customNames: { primary: null, virtual1: null, virtual2: null } } });
  const newer = projectedHardware();
  newer.dashboardRouting.revision = 5;
  d.updateState(newer);
  assert.deepEqual(sent.map(message => message.command), ['dashboard_config_get', 'dashboard_config_get']);
});

test('Milestone 3B reports output topology mismatch without presenting routes as known', () => {
  const { dashboard: d } = controller();
  const state = projectedHardware({
    capabilities: { outputMappingStatus: 'topology_mismatch', outputMappingReason: 'Expected six AUX channels; found four.' },
    outputs: [{ outputId: 1, auxIndex: 0, displayName: 'OUT 1', owner: 'unresolved', routeStatus: 'topology_mismatch', liveSourceId: null, conflicts: [] }],
    primaryOutputIds: [],
  });
  d.updateState(state);
  assert.equal(d.outputMappingError, 'Expected six AUX channels; found four.');
  assert.equal(d.primarySwitcherOutputs.length, 0);
  assert.equal(d.outputSourceId(d.otherOutputViews[0]), null);
  assert.match(d.outputStatus(d.otherOutputViews[0]), /topology mismatch/i);
});

test('Milestone 3B marks stale M/E state and hides it as current after disconnect', () => {
  const { dashboard: d } = controller();
  d.updateState(projectedHardware({ stateFresh: false }));
  assert.equal(d.meObservationStale, true);
  assert.equal(d.hardwareProgramSourceId, 2);
  d.handleMessage({ type: 'connection_status', connected: false });
  assert.equal(d.hardwareProgramSourceId, null);
  assert.equal(d.hardwarePreviewSourceId, null);
});

test('keyer timeout acts on the current reconciled object and blocks repeat toggles', () => {
  const { dashboard: d, sent, timers } = controller();
  d.updateState(hardware());
  d.toggleUSK(0);
  d.updateState(hardware()); // replaces the keyer object before timeout
  for (const callback of [...timers.values()]) callback();
  assert.equal(d.upstreamKeyers[0].unconfirmed, true);
  assert.equal(d.upstreamKeyers[0].pending, false);
  d.toggleUSK(0);
  assert.equal(sent.length, 1);
  d.updateState(hardware({ usk: [true, false] }));
  assert.equal(d.upstreamKeyers[0].unconfirmed, false);
  assert.equal(d.upstreamKeyers[0].statusText, 'ON AIR');
});

test('unknown keyer state blocks a hardware toggle', () => {
  const { dashboard: d, sent } = controller();
  const state = hardware();
  delete state.dashboardSafety.usk['0'];
  d.updateState(state);
  assert.match(d.keyerToggleReason(d.upstreamKeyers[0]), /not been observed/);
  d.toggleUSK(0);
  assert.equal(sent.length, 0);
});

function threeCProjection({ routes = [90010, 1, 2, 1, 2, 1], virtual1 = [], virtual2 = [] } = {}) {
  const owners = routes.map((route, index) => route === 90010 ? 'primary' :
    (virtual1.includes(index) ? 'virtual1' : virtual2.includes(index) ? 'virtual2' : 'other'));
  const outputs = routes.map((liveSourceId, index) => ({
    outputId: index + 1, auxIndex: index, displayName: `OUT ${index + 1}`,
    liveSourceId, lastObservedSourceId: null, routeStatus: 'observed', owner: owners[index],
    observedRouteOwner: liveSourceId === 90010 ? 'primary' : 'other', savedOwners: [],
    available: true, conflicts: [],
  }));
  const group = (key, channels) => {
    const live = channels.map(channel => routes[channel]);
    const uniform = live.length > 0 && live.every(source => source === live[0]);
    const cfg = { virtual1: { previewSource: 3, programTarget: 1 },
      virtual2: { previewSource: 3, programTarget: 1 } }[key];
    return {
      outputIds: channels.map(channel => channel + 1), routeStatus: channels.length === 0 ? 'empty' : uniform ? 'uniform' : 'mixed',
      liveSourceId: uniform ? live[0] : null, savedProgramTargetId: cfg.programTarget,
      previewSourceId: cfg.previewSource, previewSourceValid: true, outputs: channels.map(channel => outputs[channel]),
    };
  };
  return {
    deviceId: 'a'.repeat(32), revision: 7, stateFresh: true,
    capabilities: { outputMappingStatus: 'ready', outputMappingReason: '', programOutputSourceId: 90010 },
    outputs, groups: { virtual1: group('virtual1', virtual1), virtual2: group('virtual2', virtual2) },
    conflicts: [], programBackgroundSourceId: 1,
  };
}

function configureThreeC(d, options = {}) {
  const state = hardware({ program: 1, preview: 2, aux3: 2 });
  state.mes[0].transition.position = 0;
  state.mes[0].transition.style = 0;
  state.dashboardRouting = threeCProjection(options);
  d.updateState(state);
  const config = {
    schemaVersion: 1,
    virtualSwitchers: {
      virtual1: { outputs: options.virtual1 || [], previewSource: 3, programTarget: 1 },
      virtual2: { outputs: options.virtual2 || [], previewSource: 3, programTarget: 1 },
    },
    customNames: { primary: null, virtual1: null, virtual2: null },
    minimumPrimaryDestinations: true, preferences: {},
  };
  d.dashboardConfigDeviceId = 'a'.repeat(32);
  d.dashboardConfig = { deviceId: 'a'.repeat(32), revision: 7, config };
}

test('3C Primary Preview and AUTO use guarded server commands; keyed AUTO needs explicit operator confirmation', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  sent.length = 0;
  d.selectPrimaryPreview(3);
  assert.deepEqual(sent[0], { command: 'dashboard_set_preview_me', me: 0, source: 3, expected_preview: 2 });
  d.updateState(hardware({ program: 1, preview: 3, aux3: 2 }));
  const safeState = hardware({ program: 1, preview: 3, aux3: 2 });
  safeState.mes[0].transition.position = 0;
  safeState.mes[0].transition.style = 0;
  safeState.mes[0].transition.selection.key1 = true;
  safeState.dashboardRouting = threeCProjection();
  d.updateState(safeState);
  d.primaryAuto();
  assert.equal(d.keyedAutoConfirmOpen, true);
  d.dispatchPrimaryAuto(true);
  assert.equal(sent[1].command, 'dashboard_auto_me');
  assert.equal(sent[1].allow_keyed, true);
  assert.deepEqual(sent[1].expected_selection, { background: true, key1: true, key2: false, key3: false, key4: false });
});

function keyOnlyAutoState({ keyOnAir = false, inTransition = false } = {}) {
  const state = hardware({ program: 1, preview: 2, usk: [keyOnAir, false] });
  state.mes[0].transition.style = 0;
  state.mes[0].transition.position = inTransition ? 500 : 0;
  state.mes[0].transition.in_transition = inTransition;
  state.mes[0].transition.selection = { background: false, key1: true, key2: false, key3: false, key4: false };
  return state;
}

test('3C key-only Primary AUTO confirms from the observed keyer after M/E returns to rest', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  const initial = keyOnlyAutoState();
  initial.dashboardRouting = threeCProjection();
  d.updateState(initial);
  sent.length = 0;

  d.primaryAuto();
  assert.equal(d.keyedAutoConfirmOpen, true);
  d.dispatchPrimaryAuto(true);
  assert.deepEqual(sent[0].expected_key_states, { '0': false });
  assert.equal(JSON.stringify(d.primaryActionPending.keyTargets), JSON.stringify({ '0': true }));

  const keyTransitioning = keyOnlyAutoState({ keyOnAir: true, inTransition: true });
  keyTransitioning.dashboardRouting = threeCProjection();
  d.updateState(keyTransitioning);
  assert.ok(d.primaryActionPending, 'key state during an active transition is not completion');

  const confirmed = keyOnlyAutoState({ keyOnAir: true });
  confirmed.dashboardRouting = threeCProjection();
  d.updateState(confirmed);
  assert.equal(d.hardwareProgramSourceId, 1, 'key-only AUTO leaves the background unchanged');
  assert.equal(d.primaryActionPending, null);
  assert.equal(d.actionNotice, 'Primary key-only AUTO confirmed by observed keyer state.');
});

test('3C key-only AUTO with unknown key state is blocked before dispatch', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  const state = keyOnlyAutoState();
  state.dashboardSafety.usk['0'].onAir = null;
  state.dashboardRouting = threeCProjection();
  d.updateState(state);
  sent.length = 0;

  assert.match(d.primaryAutoReason(), /keyer on-air state has not been observed/i);
  d.primaryAuto();
  assert.equal(sent.length, 0);
});

test('3C reviewed key-only AUTO with unchanged key state is not reported successful', () => {
  const { dashboard: d, sent, timers } = controller();
  configureThreeC(d);
  const initial = keyOnlyAutoState();
  initial.dashboardRouting = threeCProjection();
  d.updateState(initial);
  sent.length = 0;
  d.dispatchPrimaryAuto(true);
  timers.get(d.primaryActionTimer)();
  assert.equal(d.primaryActionPending.unconfirmed, true);
  d.reviewPrimaryOperation();
  assert.equal(sent.at(-1).command, 'dashboard_review_me');
  d.handleMessage({ type: 'dashboard_reviewed', kind: 'me' });
  const unchanged = keyOnlyAutoState();
  unchanged.dashboardRouting = threeCProjection();
  d.updateState(unchanged);

  assert.equal(d.primaryActionPending, null);
  assert.match(d.actionError, /no transition was confirmed/i);
  assert.notEqual(d.actionNotice, 'Primary key-only AUTO confirmed by observed keyer state.');
  assert.equal(sent.filter(message => message.command === 'dashboard_auto_me').length, 1);
});

test('3C Preview is saved in revisioned configuration without a routing command', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  sent.length = 0;
  d.setVirtualPreview('virtual1', 2);
  assert.deepEqual(sent[0], {
    command: 'dashboard_config_update', expected_revision: 7,
    config: { ...d.dashboardConfig.config,
      virtualSwitchers: { ...d.dashboardConfig.config.virtualSwitchers,
        virtual1: { outputs: [], previewSource: 2, programTarget: 1 } } },
  });
  assert.equal(sent.some(item => item.command === 'set_aux_output' || item.command === 'dashboard_cut_aux'), false);
});

test('3D TAKE ALL sends selected Primary action once and reports each participant after confirmation', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 2, 1, 2, 1], virtual1: [1], virtual2: [2] });
  d.dashboardConfig.config.virtualSwitchers.virtual1 = { outputs: [1], previewSource: 3, programTarget: 1 };
  d.dashboardConfig.config.virtualSwitchers.virtual2 = { outputs: [2], previewSource: 3, programTarget: 1 };
  sent.length = 0;
  assert.equal(d.takeAllReason(), '');
  d.takeAll();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].command, 'dashboard_take_all');
  assert.equal(sent[0].primary_action, 'cut');
  assert.deepEqual(sent[0].groups, { virtual1: { live: 1, preview: 3 }, virtual2: { live: 2, preview: 3 } });
  d.handleMessage({ type: 'dashboard_take_all_started', device_id: 'a'.repeat(32),
    primary: { ok: true, action: 'cut', command: 'cut', before: 1, target: 2, style: 0 },
    virtual: {
      virtual1: { status: 'pending', target: 3, previous: 1, outcomes: [{ channel: 1, ok: true }] },
      virtual2: { status: 'pending', target: 3, previous: 2, outcomes: [{ channel: 2, ok: true }] },
    } });
  const confirmed = hardware({ program: 2, preview: 1, aux3: 3 });
  confirmed.dashboardRouting = threeCProjection({ routes: [90010, 3, 3, 1, 2, 1], virtual1: [1], virtual2: [2] });
  d.updateState(confirmed);
  const save = sent.find(message => message.command === 'dashboard_config_update');
  assert.ok(save, 'confirmed group CUTs are saved together once');
  assert.equal(save.config.virtualSwitchers.virtual1.programTarget, 3);
  assert.equal(save.config.virtualSwitchers.virtual2.programTarget, 3);
  d.handleMessage({ type: 'dashboard_config', deviceId: 'a'.repeat(32), revision: 8, config: save.config });
  assert.equal(d.takeAllOperation.status, 'complete');
  assert.equal(d.takeAllOperation.primary.status, 'confirmed');
  assert.equal(d.takeAllOperation.virtual1.status, 'confirmed');
  assert.equal(d.takeAllOperation.virtual2.status, 'confirmed');
  assert.equal(sent.filter(message => message.command === 'dashboard_take_all').length, 1);
});

test('3D keyed AUTO requires separate confirmation and uncertain results prevent retries', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 2, 1, 2, 1], virtual1: [1], virtual2: [2] });
  d.dashboardConfig.config.virtualSwitchers.virtual1 = { outputs: [1], previewSource: 3, programTarget: 1 };
  d.dashboardConfig.config.virtualSwitchers.virtual2 = { outputs: [2], previewSource: 3, programTarget: 1 };
  const state = hardware();
  state.mes[0].transition.position = 0;
  state.mes[0].transition.style = 2;
  state.mes[0].transition.selection.key1 = true;
  state.dashboardRouting = threeCProjection({ routes: [90010, 1, 2, 1, 2, 1], virtual1: [1], virtual2: [2] });
  d.updateState(state);
  d.takeAllPrimaryAction = 'auto';
  sent.length = 0;
  d.takeAll();
  assert.equal(d.takeAllKeyedConfirmOpen, true);
  assert.equal(sent.length, 0);
  d.dispatchTakeAll(true);
  assert.equal(sent[0].command, 'dashboard_take_all');
  assert.equal(sent[0].primary_action, 'auto');
  assert.equal(sent[0].allow_keyed, true);
  d.takeAllOperation.status = 'unconfirmed';
  assert.match(d.takeAllReason(), /previous TAKE ALL/i);
  d.takeAll();
  assert.equal(sent.filter(message => message.command === 'dashboard_take_all').length, 1);
});

test('3D TAKE ALL key-only AUTO reports Primary confirmed from observed keyer state', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  const initial = keyOnlyAutoState();
  initial.dashboardRouting = threeCProjection();
  d.updateState(initial);
  d.takeAllPrimaryAction = 'auto';
  sent.length = 0;

  d.takeAll();
  assert.equal(d.takeAllKeyedConfirmOpen, true);
  d.dispatchTakeAll(true);
  const command = sent.find(message => message.command === 'dashboard_take_all');
  assert.deepEqual(command.expected_key_states, { '0': false });
  d.handleMessage({ type: 'dashboard_take_all_started', device_id: 'a'.repeat(32),
    primary: { ok: true, action: 'auto', command: 'auto', before: 1, target: 2, style: 0,
      key_before: { '0': false }, key_targets: { '0': true } },
    virtual: { virtual1: { status: 'skipped', outcomes: [] },
      virtual2: { status: 'skipped', outcomes: [] } } });
  const confirmed = keyOnlyAutoState({ keyOnAir: true });
  confirmed.dashboardRouting = threeCProjection();
  d.updateState(confirmed);

  assert.equal(d.takeAllOperation.primary.status, 'confirmed');
  assert.equal(d.takeAllOperation.status, 'complete');
  assert.equal(d.hardwareProgramSourceId, 1);
});

test('3D key-only TAKE ALL stays unconfirmed when reviewed key state did not change', () => {
  const { dashboard: d, sent, timers } = controller();
  configureThreeC(d);
  const initial = keyOnlyAutoState();
  initial.dashboardRouting = threeCProjection();
  d.updateState(initial);
  d.takeAllPrimaryAction = 'auto';
  sent.length = 0;
  d.dispatchTakeAll(true);
  d.handleMessage({ type: 'dashboard_take_all_started', device_id: 'a'.repeat(32),
    primary: { ok: true, action: 'auto', command: 'auto', before: 1, target: 2, style: 0,
      key_before: { '0': false }, key_targets: { '0': true } },
    virtual: { virtual1: { status: 'skipped', outcomes: [] },
      virtual2: { status: 'skipped', outcomes: [] } } });
  timers.get(d.primaryActionTimer)();
  assert.equal(d.takeAllOperation.status, 'unconfirmed');
  assert.notEqual(d.takeAllOperation.status, 'complete');
  d.reviewPrimaryOperation();
  d.handleMessage({ type: 'dashboard_reviewed', kind: 'me' });
  const unchanged = keyOnlyAutoState();
  unchanged.dashboardRouting = threeCProjection();
  d.updateState(unchanged);

  assert.equal(d.takeAllOperation.primary.status, 'failed');
  assert.equal(d.takeAllOperation.status, 'partial');
  assert.equal(sent.filter(message => message.command === 'dashboard_take_all').length, 1);
});

test('3D an empty virtual group with an unavailable saved source does not block other participants', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  d.dashboardConfig.config.virtualSwitchers.virtual1.previewSource = 999;
  d.state.dashboardRouting.conflicts = [{ type: 'invalid_saved_source', group: 'virtual1', field: 'previewSource' }];
  assert.equal(d.takeAllReason(), '');
  d.takeAll();
  assert.equal(sent.at(-1).command, 'dashboard_take_all');
});

test('3D Primary timeout resolves only after explicit read-only review and fresh observed state', () => {
  const { dashboard: d, sent, timers } = controller();
  configureThreeC(d);
  sent.length = 0;
  d.takeAll();
  d.handleMessage({ type: 'dashboard_take_all_started', device_id: 'a'.repeat(32),
    primary: { ok: true, action: 'cut', command: 'cut', before: 1, target: 2, style: 0 },
    virtual: { virtual1: { status: 'skipped', outcomes: [] }, virtual2: { status: 'skipped', outcomes: [] } } });
  timers.get(d.primaryActionTimer)();
  assert.equal(d.takeAllOperation.primary.status, 'unconfirmed');
  assert.match(d.takeAllReason(), /previous TAKE ALL/i);
  d.takeAll();
  assert.equal(sent.filter(message => message.command === 'dashboard_take_all').length, 1);
  d.reviewPrimaryOperation();
  assert.equal(sent.at(-1).command, 'dashboard_review_me');
  d.handleMessage({ type: 'dashboard_reviewed', kind: 'me' });
  const confirmed = hardware({ program: 2, preview: 1 });
  confirmed.dashboardRouting = threeCProjection();
  d.updateState(confirmed);
  assert.equal(d.takeAllOperation.primary.status, 'confirmed');
  assert.equal(d.takeAllOperation.status, 'complete');
});

test('3D partial result stays partial and never automatically retries a failed destination', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 2, 1, 2, 1], virtual1: [1], virtual2: [2] });
  d.dashboardConfig.config.virtualSwitchers.virtual1 = { outputs: [1], previewSource: 3, programTarget: 1 };
  d.dashboardConfig.config.virtualSwitchers.virtual2 = { outputs: [2], previewSource: 3, programTarget: 1 };
  sent.length = 0;
  d.takeAll();
  d.handleMessage({ type: 'dashboard_take_all_started', device_id: 'a'.repeat(32),
    primary: { ok: true, action: 'cut', command: 'cut', before: 1, target: 2, style: 0 },
    virtual: {
      virtual1: { status: 'pending', target: 3, previous: 1, outcomes: [{ channel: 1, ok: true }] },
      virtual2: { status: 'partial', target: 3, previous: 2, outcomes: [{ channel: 2, ok: false, error: 'not acknowledged' }] },
    } });
  const confirmed = hardware({ program: 2, preview: 1, aux3: 3 });
  confirmed.dashboardRouting = threeCProjection({ routes: [90010, 3, 2, 1, 2, 1], virtual1: [1], virtual2: [2] });
  d.updateState(confirmed);
  const save = sent.find(message => message.command === 'dashboard_config_update');
  assert.ok(save);
  d.handleMessage({ type: 'dashboard_config', deviceId: 'a'.repeat(32), revision: 8, config: save.config });
  assert.equal(d.takeAllOperation.virtual1.status, 'confirmed');
  assert.equal(d.takeAllOperation.virtual2.status, 'partial');
  assert.equal(d.takeAllOperation.status, 'partial');
  assert.equal(sent.filter(message => message.command === 'dashboard_take_all').length, 1);
});

test('3C virtual output assignment waits for observed route before revisioned ownership save', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 2, 1, 2, 1], virtual1: [1] });
  sent.length = 0;
  d.openAssignmentDialog('virtual1');
  d.assignmentSelection['3'] = true;
  d.applyAssignmentChanges();
  assert.equal(sent[0].command, 'dashboard_output_route');
  assert.equal(sent[0].output_id, 3);
  assert.equal(sent[0].input_source, 1);
  d.handleMessage({ type: 'dashboard_output_route_accepted', output_id: 3, input_source: 1 });
  assert.equal(sent.some(item => item.command === 'dashboard_config_update'), false);
  const next = hardware({ program: 1, preview: 2, aux3: 1 });
  next.dashboardRouting = threeCProjection({ routes: [90010, 1, 1, 1, 2, 1], virtual1: [1] });
  d.updateState(next);
  assert.equal(sent[1].command, 'dashboard_config_update');
  assert.ok(sent[1].config.virtualSwitchers.virtual1.outputs.includes(2));
});

test('3C partial assignment preserves the failed-output warning after confirmed ownership is saved', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 2, 2, 2, 1], virtual1: [1] });
  sent.length = 0;
  d.openAssignmentDialog('virtual1');
  d.assignmentSelection['3'] = true;
  d.assignmentSelection['4'] = true;
  d.applyAssignmentChanges();
  assert.equal(sent[0].output_id, 3);
  d.handleMessage({ type: 'error', command: 'dashboard_output_route', output_id: 3, message: 'OUT 3 route failed.' });
  assert.equal(sent[1].command, 'dashboard_output_route');
  assert.equal(sent[1].output_id, 4);
  d.handleMessage({ type: 'dashboard_output_route_accepted', output_id: 4, input_source: 1 });
  const confirmed = hardware({ program: 1, preview: 2, aux3: 2 });
  confirmed.dashboardRouting = threeCProjection({ routes: [90010, 1, 2, 1, 2, 1], virtual1: [1] });
  confirmed.dashboardRouting.outputs[3].liveSourceId = 1;
  confirmed.dashboardRouting.outputs[3].observedRouteOwner = 'other';
  d.updateState(confirmed);
  const save = sent.find(item => item.command === 'dashboard_config_update');
  assert.ok(save);
  d.handleMessage({ type: 'dashboard_config', deviceId: 'a'.repeat(32), revision: 8, config: save.config });
  assert.match(d.actionError, /some output operations failed: OUT 3 route failed/i);
  assert.notEqual(d.actionNotice, 'Output ownership changes saved.');
});

test('3C Primary release routes only the selected destination to current M/E background', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 90010, 2, 1, 2, 1] });
  sent.length = 0;
  d.openAssignmentDialog('primary');
  d.assignmentSelection['2'] = false;
  assert.match(d.stagedAssignmentDescription(d.projectedOutputs[1]), /Release to IN1 \(background only; key overlays removed\)/);
  d.applyAssignmentChanges();
  assert.equal(sent[0].command, 'dashboard_output_route');
  assert.equal(sent[0].mode, 'primary_release');
  assert.equal(sent[0].output_id, 2);
  assert.equal(sent[0].input_source, 1);
  const confirmed = hardware({ program: 1, preview: 2, aux3: 2 });
  confirmed.auxOutputs.aux2 = 1;
  confirmed.dashboardRouting = threeCProjection({ routes: [90010, 1, 2, 1, 2, 1] });
  d.updateState(confirmed);
  assert.equal(d.routeOperations['2'], undefined);
  assert.equal(d.routeBatch, null);
});

test('3C group CUT confirms each physical route before swapping saved target/Preview', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 1, 1, 2, 1], virtual1: [1, 2] });
  sent.length = 0;
  d.cutVirtualGroup('virtual1');
  assert.equal(sent[0].command, 'dashboard_cut_virtual_group');
  d.handleMessage({ type: 'dashboard_group_cut_started', group_id: 'virtual1', target: 3, previous: 1,
    outcomes: [{ channel: 1, ok: true }, { channel: 2, ok: true }] });
  assert.equal(sent.some(item => item.command === 'dashboard_config_update'), false);
  const confirmed = hardware({ program: 1, preview: 2, aux3: 3 });
  confirmed.dashboardRouting = threeCProjection({ routes: [90010, 3, 3, 1, 2, 1], virtual1: [1, 2] });
  d.updateState(confirmed);
  const save = sent.find(item => item.command === 'dashboard_config_update');
  assert.ok(save);
  assert.equal(save.config.virtualSwitchers.virtual1.programTarget, 3);
  assert.equal(save.config.virtualSwitchers.virtual1.previewSource, 1);
});

test('3C late route confirmation reconciles after disconnect without retrying', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  sent.length = 0;
  d.routeOtherOutput(d.projectedOutputs[2], 3);
  assert.equal(sent[0].command, 'dashboard_output_route');
  d.handleMessage({ type: 'connection_status', connected: false });
  assert.equal(d.routeOperations['3'].status, 'unconfirmed');
  const state = hardware({ program: 1, preview: 2, aux3: 3 });
  state.dashboardRouting = threeCProjection({ routes: [90010, 1, 3, 1, 2, 1] });
  d.updateState(state);
  assert.equal(d.routeOperations['3'], undefined);
  assert.equal(sent.length, 1);
});

test('3C timed-out route can be reviewed read-only and cleared when hardware stayed unchanged', () => {
  const { dashboard: d, sent, timers } = controller();
  configureThreeC(d);
  sent.length = 0;
  d.routeOtherOutput(d.projectedOutputs[2], 3);
  const routeTimer = d.routeOperations['3'].timer;
  timers.get(routeTimer)();
  assert.equal(d.routeOperations['3'].status, 'unconfirmed');
  d.reviewOutputOperation(3);
  assert.deepEqual(sent[1], { command: 'dashboard_review_aux', aux_channel: 2 });
  d.handleMessage({ type: 'dashboard_reviewed', kind: 'aux', aux_channel: 2 });
  const state = hardware({ program: 1, preview: 2, aux3: 2 });
  state.dashboardRouting = threeCProjection();
  d.updateState(state);
  assert.equal(d.routeOperations['3'], undefined);
  assert.equal(sent.length, 2);
});

test('3C mixed routing requires explicit alignment review and saves target only after every route confirms', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d, { routes: [90010, 1, 2, 1, 2, 1], virtual1: [1, 2] });
  sent.length = 0;
  assert.equal(d.groupAlignReason('virtual1'), '');
  d.beginVirtualGroupAlign('virtual1');
  assert.equal(JSON.stringify(d.groupAlignDraft.expectedRoutes), JSON.stringify([{ channel: 1, source: 1 }, { channel: 2, source: 2 }]));
  d.confirmVirtualGroupAlign();
  assert.equal(sent[0].command, 'dashboard_align_virtual_group');
  assert.equal(sent[0].input_source, 1);
  d.handleMessage({ type: 'dashboard_group_align_started', group_id: 'virtual1', target: 1,
    outcomes: [{ channel: 1, ok: true, no_op: true }, { channel: 2, ok: true, no_op: false }] });
  assert.equal(sent.some(item => item.command === 'dashboard_config_update'), false);
  const confirmed = hardware({ program: 1, preview: 2, aux3: 2 });
  confirmed.dashboardRouting = threeCProjection({ routes: [90010, 1, 1, 1, 2, 1], virtual1: [1, 2] });
  d.updateState(confirmed);
  assert.equal(sent.find(item => item.command === 'dashboard_config_update').config.virtualSwitchers.virtual1.programTarget, 1);
});

test('3C partial group CUT requires per-output confirmation or review before unlocking', () => {
  const { dashboard: d, sent, timers } = controller();
  configureThreeC(d, { routes: [90010, 1, 1, 1, 2, 1], virtual1: [1, 2] });
  sent.length = 0;
  d.cutVirtualGroup('virtual1');
  d.handleMessage({ type: 'dashboard_group_cut_started', group_id: 'virtual1', target: 3, previous: 1,
    outcomes: [{ channel: 1, ok: true }, { channel: 2, ok: false, error: 'OUT 3 dispatch failed.' }] });
  assert.equal(d.groupCutOperations.virtual1.status, 'partial');
  assert.match(d.groupCutReason('virtual1'), /incomplete/i);

  const resolved = hardware({ program: 1, preview: 2, aux3: 1 });
  resolved.dashboardRouting = threeCProjection({ routes: [90010, 1, 1, 1, 2, 1], virtual1: [1, 2] });
  d.updateState(resolved);
  assert.equal(d.groupCutOperations.virtual1.status, 'partial');
  assert.match(d.groupCutReason('virtual1'), /incomplete/i);

  timers.get(d.groupCutOperations.virtual1.timer)();
  d.reviewOutputOperation(2);
  d.handleMessage({ type: 'dashboard_reviewed', kind: 'aux', aux_channel: 1 });
  d.updateState(resolved);
  assert.equal(d.groupCutOperations.virtual1.status, 'resolved');
  assert.equal(d.groupCutReason('virtual1'), '');
});

test('3C a competing configuration broadcast is not mistaken for this session save', () => {
  const { dashboard: d, sent } = controller();
  configureThreeC(d);
  sent.length = 0;
  d.setVirtualPreview('virtual1', 2);
  const competing = JSON.parse(JSON.stringify(sent[0].config));
  competing.customNames.primary = 'Other Session';
  d.handleMessage({ type: 'dashboard_config_changed', deviceId: 'a'.repeat(32), revision: 8, config: competing });
  assert.match(d.dashboardConfigError, /Another dashboard session/);
  assert.equal(d.assignmentBusy, false);
  assert.equal(d.configSavePurpose, null);
});
