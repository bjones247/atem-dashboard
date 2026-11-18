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
