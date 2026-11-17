/**
 * production_dashboard.js — Production Dashboard (3-Output) Client Controller
 * Milestone 2: Individual Output Switching and Upstream Keyer Control.
 *
 * Core capabilities:
 * 1. Independent AUX Preview (software-only until CUT).
 * 2. Independent AUX CUT with confirmed swap (previous live becomes preview).
 * 3. Hardware M/E Preview selection and guarded M/E background CUT.
 * 4. Fails safe: Blocks M/E CUT if any upstream keyer is tied to next transition.
 * 5. Linked/mirrored M/E outputs share Program, Preview, and single deduplicated CUT.
 * 6. Independent on-air toggles for discovered upstream keyers with pending guards.
 * 7. Hardware-confirmed state reconciliation, timeouts, and error reporting.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('productionDashboard', () => ({
        ipAddress: '',
        connected: false,
        reconnecting: false,
        statusMessage: 'Connecting...',
        atemName: '',
        ws: null,
        reconnectTimer: null,
        reconnectAttempts: 0,

        // Feedback / Alerts
        actionError: '',
        actionNotice: '',
        actionNoticeTimer: null,

        // Authoritative ATEM state
        state: null,
        sources: [],
        auxOutputs: {},
        mes: [],

        // Discovered M/E program source ID and multi-output status
        me1ProgramSourceId: null,
        meOutputCount: 0,
        primaryMeOutNumber: null,
        meNotice: '',

        // 3 Managed Output Panels (OUT 1, OUT 2, OUT 3)
        panels: [
            {
                outNumber: 1,
                auxKey: 'aux1',
                friendlyName: 'Output 1',
                role: 'VirtualAux',
                isME: false,
                isMEPrimary: false,
                isMEMirrored: false,
                onAirSourceId: null,
                queuedPreviewSourceId: null,
                pending: false,
                pendingTimeoutId: null,
                pendingTarget: null,
                pendingPrevLive: null,
                pendingSwap: false,
                unconfirmed: false,
                editingName: false
            },
            {
                outNumber: 2,
                auxKey: 'aux2',
                friendlyName: 'Output 2',
                role: 'VirtualAux',
                isME: false,
                isMEPrimary: false,
                isMEMirrored: false,
                onAirSourceId: null,
                queuedPreviewSourceId: null,
                pending: false,
                pendingTimeoutId: null,
                pendingTarget: null,
                pendingPrevLive: null,
                pendingSwap: false,
                unconfirmed: false,
                editingName: false
            },
            {
                outNumber: 3,
                auxKey: 'aux3',
                friendlyName: 'Output 3',
                role: 'VirtualAux',
                isME: false,
                isMEPrimary: false,
                isMEMirrored: false,
                onAirSourceId: null,
                queuedPreviewSourceId: null,
                pending: false,
                pendingTimeoutId: null,
                pendingTarget: null,
                pendingPrevLive: null,
                pendingSwap: false,
                unconfirmed: false,
                editingName: false
            }
        ],

        // Discovered Upstream Keyers on M/E 1
        upstreamKeyers: [],

        // Settings / Display preferences
        labelStyle: 'both',
        programSelectionMode: 'preview_cut_only', // 'preview_cut_only' vs 'direct'
        masterSafetyMode: 'protected', // 'protected' vs 'instant'

        init() {
            // Read initial IP from query params, then fallback to localStorage
            const urlParams = new URLSearchParams(window.location.search);
            const queryIp = urlParams.get('ip');
            if (queryIp && queryIp.trim()) {
                this.ipAddress = queryIp.trim();
                try { localStorage.setItem('atem_ip', this.ipAddress); } catch (e) {}
            } else {
                try { this.ipAddress = localStorage.getItem('atem_ip') || ''; } catch (e) {}
            }

            // Load saved friendly names from localStorage
            this.panels.forEach(p => {
                try {
                    const saved = localStorage.getItem(`webatem_output_name_${p.outNumber}`);
                    if (saved && saved.trim()) {
                        p.friendlyName = saved.trim();
                    }
                } catch (e) {}
            });

            // Load saved primary M/E output preference
            try {
                const savedPrimary = parseInt(localStorage.getItem('webatem_primary_me_out'), 10);
                if (savedPrimary >= 1 && savedPrimary <= 3) {
                    this.primaryMeOutNumber = savedPrimary;
                }
            } catch (e) {}

            // Connect WebSocket
            this.connectWebSocket();

            window.addEventListener('beforeunload', () => {
                if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
                this.clearAllPendingTimeouts();
                if (this.ws) {
                    try { this.ws.close(); } catch (e) {}
                }
            });
        },

        connectWebSocket() {
            if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
                return;
            }

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/atem/`;

            try {
                this.ws = new WebSocket(wsUrl);
            } catch (err) {
                this.statusMessage = 'WebSocket connection failed: ' + err.message;
                this.scheduleReconnect();
                return;
            }

            this.ws.onopen = () => {
                this.statusMessage = 'WebSocket opened. Handshaking...';
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (err) {
                    console.error('Failed to parse WebSocket message:', err);
                }
            };

            this.ws.onclose = () => {
                this.connected = false;
                this.state = null;
                this.reconnecting = true;
                this.statusMessage = 'Disconnected. Reconnecting...';
                this.panels.forEach(p => {
                    if (p.pending) this.markUnconfirmed(p);
                });
                this.clearAllPendingTimeouts();
                this.upstreamKeyers.forEach(k => k.pending = false);
                this.scheduleReconnect();
            };

            this.ws.onerror = (err) => {
                console.warn('WebSocket error:', err);
            };
        },

        scheduleReconnect() {
            if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 10000);
            this.reconnectTimer = setTimeout(() => {
                this.connectWebSocket();
            }, delay);
        },

        handleMessage(data) {
            if (!data || !data.type) return;

            switch (data.type) {
                case 'websocket_ready':
                    if (this.ipAddress) {
                        this.ws.send(JSON.stringify({
                            command: 'connect',
                            ip_address: this.ipAddress
                        }));
                    } else {
                        this.statusMessage = 'No ATEM IP provided. Connect on the main page first.';
                    }
                    break;

                case 'connection_status':
                    if (data.connected) {
                        this.connected = true;
                        this.reconnecting = false;
                        this.reconnectAttempts = 0;
                        this.statusMessage = data.message || `Connected to ${this.ipAddress}`;
                        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                            this.ws.send(JSON.stringify({ command: 'refresh' }));
                        }
                    } else {
                        this.connected = false;
                        this.state = null;
                        this.statusMessage = data.message || 'Connection failed.';
                        this.panels.forEach(p => {
                            if (p.pending) this.markUnconfirmed(p);
                        });
                        this.clearAllPendingTimeouts();
                    }
                    break;

                case 'error':
                    this.showError(data.message || 'ATEM command rejected');
                    this.panels.forEach(p => {
                        const affectsPending = !data.command ||
                            (data.command === 'dashboard_cut_me' && p.isME) ||
                            (data.command === 'dashboard_cut_aux' && !p.isME &&
                                p.outNumber - 1 === data.aux_channel);
                        if (p.pending && affectsPending) this.markUnconfirmed(p);
                    });
                    this.upstreamKeyers.forEach(k => k.pending = false);
                    break;

                case 'dashboard_reviewed':
                    this.panels.forEach(p => {
                        if ((data.kind === 'me' && p.isME) ||
                            (data.kind === 'aux' && !p.isME && p.outNumber - 1 === data.aux_channel)) {
                            p.unconfirmed = false;
                        }
                    });
                    break;

                case 'atem_state':
                    if (data.state) {
                        this.updateState(data.state);
                    }
                    break;
            }
        },

        updateState(state) {
            this.state = state;
            this.connected = !!state.is_connected;
            this.atemName = state.atem_name || (this.connected ? 'Connected ATEM' : 'Disconnected');
            this.sources = state.sources || [];
            this.auxOutputs = state.auxOutputs || {};
            this.mes = state.mes || [];

            // 1. Discover M/E 1 Program source ID dynamically from state.sources
            this.discoverMeProgramSource();

            // 2. Discover M/E assignment among OUT 1–3 (zero, one, or multiple linked outputs)
            this.mapManagedOutputRoles();

            // 3. Update panel live sources, reconcile pending actions, and update preview
            this.reconcilePanelSources();

            // 4. Update discovered Upstream Keyers on M/E 1
            this.reconcileUpstreamKeyers();
        },

        discoverMeProgramSource() {
            let found = this.sources.find(s => {
                if (s.port_type === 128) {
                    const l = (s.long || '').toLowerCase();
                    const sh = (s.short || '').toUpperCase();
                    if (l.includes('program') || l.includes('pgm') || sh === 'PGM') {
                        return true;
                    }
                }
                return false;
            });

            if (!found) {
                found = this.sources.find(s => s.source === 10010);
            }

            this.me1ProgramSourceId = found ? found.source : null;
        },

        mapManagedOutputRoles() {
            const meMatches = [];
            if (this.me1ProgramSourceId !== null) {
                this.panels.forEach(p => {
                    const routedSource = this.state?.dashboardSafety?.aux?.[String(p.outNumber - 1)]?.live ?? null;
                    if (routedSource === this.me1ProgramSourceId) {
                        meMatches.push(p.outNumber);
                    }
                });
            }

            this.meOutputCount = meMatches.length;

            // Resolve designated primary M/E panel (prefers OUT 1 if carrying M/E)
            let primaryOut = null;
            if (meMatches.length > 0) {
                if (this.primaryMeOutNumber && meMatches.includes(this.primaryMeOutNumber)) {
                    primaryOut = this.primaryMeOutNumber;
                } else if (meMatches.includes(1)) {
                    primaryOut = 1;
                    this.primaryMeOutNumber = 1;
                } else {
                    primaryOut = meMatches[0];
                    this.primaryMeOutNumber = primaryOut;
                }
                try { localStorage.setItem('webatem_primary_me_out', String(primaryOut)); } catch (e) {}
            } else {
                this.primaryMeOutNumber = null;
            }

            // Set informative status note
            if (meMatches.length > 1) {
                this.meNotice = `OUT ${meMatches.join(' and OUT ')} both carry M/E Program and are linked (sharing M/E Program and Preview).`;
            } else if (meMatches.length === 1) {
                this.meNotice = '';
            } else {
                this.meNotice = 'M/E Program is not currently routed to OUT 1–3 (all 3 outputs operating as independent AUX).';
            }

            // Update roles and mirror status for each panel
            this.panels.forEach(p => {
                const isME = meMatches.includes(p.outNumber);
                p.isME = isME;
                p.role = isME ? 'HardwareME' : 'VirtualAux';
                p.isMEPrimary = isME && (p.outNumber === primaryOut);
                p.isMEMirrored = isME && (p.outNumber !== primaryOut);
            });
        },

        reconcilePanelSources() {
            const meSafety = this.state?.dashboardSafety?.meCut;
            const meProgram = meSafety?.program ?? null;
            const mePreview = meSafety?.preview ?? null;

            this.panels.forEach(p => {
                const routedAuxSource = this.state?.dashboardSafety?.aux?.[String(p.outNumber - 1)]?.live ?? null;

                if (p.isME) {
                    // M/E Output (Primary or Mirrored)
                    // Check if pending M/E CUT has completed
                    if (p.pending && meProgram !== null) {
                        if (p.pendingTarget !== null && meProgram === p.pendingTarget) {
                            // Hardware confirmed new program source
                            this.clearPendingTimeout(p);
                            p.pending = false;
                            p.pendingTarget = null;
                            p.pendingPrevLive = null;
                        } else if (p.pendingPrevLive !== null && meProgram !== p.pendingPrevLive) {
                            // Program changed away from previous live
                            this.markUnconfirmed(p);
                        }
                    }

                    if (p.unconfirmed && meProgram !== null && meProgram !== p.pendingPrevLive) {
                        p.unconfirmed = false;
                        p.pendingTarget = null;
                        p.pendingPrevLive = null;
                    }
                    p.onAirSourceId = meProgram;
                    p.queuedPreviewSourceId = mePreview;

                } else {
                    // Virtual AUX Output
                    if (p.pending && routedAuxSource !== null) {
                        if (p.pendingTarget !== null && routedAuxSource === p.pendingTarget) {
                            // Hardware confirmed AUX switch! Perform verified SWAP:
                            const prevLive = p.pendingPrevLive;
                            const shouldSwap = p.pendingSwap;
                            this.clearPendingTimeout(p);
                            p.pending = false;
                            p.pendingTarget = null;
                            p.pendingPrevLive = null;
                            p.pendingSwap = false;
                            p.unconfirmed = false;

                            p.onAirSourceId = routedAuxSource;
                            if (shouldSwap && prevLive !== null && this.sources.some(s => s.source === prevLive && s.available_aux === true)) {
                                p.queuedPreviewSourceId = prevLive;
                                try {
                                    sessionStorage.setItem(`webatem_pvw_${this.ipAddress}_out_${p.outNumber}`, String(prevLive));
                                } catch (e) {}
                            }
                            return;
                        } else if (p.pendingPrevLive !== null && routedAuxSource !== p.pendingPrevLive) {
                            // An external route diverged before our target appeared.
                            // Never swap Preview based on a later ambiguous match.
                            this.markUnconfirmed(p);
                        }
                    }

                    // Normal state sync or external switch
                    p.onAirSourceId = routedAuxSource;
                    if (p.unconfirmed && routedAuxSource !== null && routedAuxSource !== p.pendingPrevLive) {
                        p.unconfirmed = false;
                        p.pendingTarget = null;
                        p.pendingPrevLive = null;
                    }

                    // Revalidate virtual Preview queue for this browser session
                    const storageKey = `webatem_pvw_${this.ipAddress}_out_${p.outNumber}`;
                    let savedPvw = null;
                    try {
                        const val = sessionStorage.getItem(storageKey);
                        if (val !== null && val !== '') savedPvw = parseInt(val, 10);
                    } catch (e) {}

                    const isSavedValid = (savedPvw !== null) && this.sources.some(s => s.source === savedPvw && s.available_aux === true);

                    if (isSavedValid) {
                        p.queuedPreviewSourceId = savedPvw;
                    } else if (p.queuedPreviewSourceId === null || !this.sources.some(s => s.source === p.queuedPreviewSourceId && s.available_aux === true)) {
                        p.queuedPreviewSourceId = p.onAirSourceId;
                    }
                }
            });
        },

        reconcileUpstreamKeyers() {
            const me0 = this.mes[0];
            if (!me0 || !me0.usk) {
                this.upstreamKeyers = [];
                return;
            }

            const usk = me0.usk;
            const states = usk.states || [];
            const data = usk.data || [];
            const count = Math.max(states.length, data.length);

            const keyers = [];
            for (let i = 0; i < count; i++) {
                const onAir = !!states[i];
                const keyData = data[i] || {};
                const fillSourceId = keyData.fill_source ?? null;
                const fillSource = this.sources.find(s => s.source === fillSourceId);
                const fillLabel = fillSource ? (fillSource.short || fillSource.long || `IN ${fillSourceId}`) : (fillSourceId !== null ? `Src ${fillSourceId}` : 'None');

                // Preserve pending state across reconcile
                const existing = this.upstreamKeyers.find(k => k.keyIndex === i);
                let pending = existing ? existing.pending : false;
                let pendingTimeoutId = existing ? existing.pendingTimeoutId : null;

                // If state flipped to target, clear pending
                if (pending && existing && existing.onAir !== onAir) {
                    if (pendingTimeoutId) clearTimeout(pendingTimeoutId);
                    pending = false;
                    pendingTimeoutId = null;
                }

                keyers.push({
                    keyIndex: i,
                    label: `KEY ${i + 1}`,
                    onAir: onAir,
                    statusText: onAir ? 'ON AIR' : 'OFF',
                    fillSourceId: fillSourceId,
                    fillLabel: fillLabel,
                    pending: pending,
                    pendingTimeoutId: pendingTimeoutId
                });
            }

            this.upstreamKeyers = keyers;
        },

        // ---------------------------------------------------------------------
        // Safety & Guard Checks
        // ---------------------------------------------------------------------
        get meKeyTied() {
            const sel = this.mes?.[0]?.transition?.selection;
            if (!sel) return false;
            return !!(sel.key1 || sel.key2 || sel.key3 || sel.key4);
        },

        get meTiedKeyList() {
            const sel = this.mes?.[0]?.transition?.selection;
            if (!sel) return [];
            const tied = [];
            if (sel.key1) tied.push('KEY 1');
            if (sel.key2) tied.push('KEY 2');
            if (sel.key3) tied.push('KEY 3');
            if (sel.key4) tied.push('KEY 4');
            return tied;
        },

        get meInTransition() {
            return !!(this.mes?.[0]?.transition?.in_transition);
        },

        get meCutReason() {
            if (!this.hardwareReady) return 'Switcher disconnected or hardware state stale.';
            if (!this.state?.dashboardSafety?.meCut) return 'Waiting for confirmed M/E state.';
            if (this.panels.some(p => p.isME && p.unconfirmed)) return 'Previous M/E CUT unconfirmed. Review hardware state.';
            if (this.panels.some(p => p.isME && p.pending)) return 'M/E CUT awaiting hardware confirmation.';
            return this.state.dashboardSafety.meCut.reason || '';
        },

        auxCutReason(panel) {
            if (!this.hardwareReady) return 'Switcher disconnected or hardware state stale.';
            const safety = this.state?.dashboardSafety?.aux?.[String(panel.outNumber - 1)];
            if (!safety) return 'AUX destination state is unavailable.';
            if (panel.unconfirmed) return 'Previous AUX CUT unconfirmed. Review hardware state.';
            if (panel.pending) return 'AUX CUT awaiting hardware confirmation.';
            if (safety.reason) return safety.reason;
            const target = panel.queuedPreviewSourceId;
            const source = this.sources.find(s => s.source === target);
            if (!Number.isInteger(target) || !source || source.available_aux !== true) return 'Select a directly routable Preview source.';
            if (target === panel.onAirSourceId) return 'Queued Preview source is already live.';
            return '';
        },

        reviewUnconfirmed(panel) {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify(panel.isME ?
                { command: 'dashboard_review_me' } :
                { command: 'dashboard_review_aux', aux_channel: panel.outNumber - 1 }));
        },

        get hardwareReady() {
            return !!(this.connected && this.ws && this.ws.readyState === WebSocket.OPEN &&
                this.state?.is_connected && this.state?.dashboardSafety?.fresh);
        },

        // Designate which M/E-fed output is primary dashboard control panel without altering hardware
        setPrimaryME(outNumber) {
            const target = this.panels.find(p => p.outNumber === outNumber);
            if (target && target.isME) {
                this.primaryMeOutNumber = outNumber;
                try {
                    localStorage.setItem('webatem_primary_me_out', String(outNumber));
                } catch (e) {}
                this.mapManagedOutputRoles();
            }
        },

        // ---------------------------------------------------------------------
        // Milestone 2 Switching Controls
        // ---------------------------------------------------------------------

        selectPreview(panel, sourceId) {
            if (!this.hardwareReady) return;
            if (panel.pending || panel.unconfirmed) return;
            if (!this.isSourceUsable(panel, this.sources.find(s => s.source === sourceId))) return;

            if (panel.isME) {
                // Real hardware M/E Preview command!
                this.ws.send(JSON.stringify({
                    command: 'set_preview',
                    source: parseInt(sourceId, 10),
                    me: 0
                }));
            } else {
                // Independent Virtual AUX output: software-only queue (no hardware write)
                panel.queuedPreviewSourceId = sourceId;
                try {
                    sessionStorage.setItem(`webatem_pvw_${this.ipAddress}_out_${panel.outNumber}`, String(sourceId));
                } catch (e) {}
            }
        },

        selectProgramDirect(panel, sourceId) {
            if (this.programSelectionMode !== 'direct') return;
            if (!this.hardwareReady) return;
            if (panel.pending || panel.unconfirmed) return;
            if (!this.isSourceUsable(panel, this.sources.find(s => s.source === sourceId))) return;
            if (sourceId === panel.onAirSourceId) return;

            if (panel.isME) {
                this.ws.send(JSON.stringify({
                    command: 'set_program',
                    source: parseInt(sourceId, 10),
                    me: 0
                }));
            } else {
                panel.pending = true;
                panel.pendingTarget = sourceId;
                panel.pendingPrevLive = panel.onAirSourceId;
                panel.pendingSwap = false;
                this.armPendingTimeout(panel, `AUX direct Program (${panel.friendlyName})`);
                this.ws.send(JSON.stringify({
                    command: 'dashboard_cut_aux',
                    aux_channel: panel.outNumber - 1,
                    input_source: parseInt(sourceId, 10),
                    expected_live: panel.onAirSourceId
                }));
            }
        },

        cut(panel) {
            if (!this.connected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
                this.showError('Switcher disconnected. CUT unavailable.');
                return;
            }

            if (panel.isME) {
                const reason = this.meCutReason;
                if (reason) { this.showError(reason); return; }

                // Deduplicated M/E CUT across all linked outputs
                const mePanels = this.panels.filter(p => p.isME);
                const targetProgram = panel.queuedPreviewSourceId;
                const prevLive = panel.onAirSourceId;

                mePanels.forEach(p => {
                    p.pending = true;
                    p.pendingTarget = targetProgram;
                    p.pendingPrevLive = prevLive;
                    this.armPendingTimeout(p, 'M/E CUT');
                });

                // Send EXACTLY ONE cut command for the shared M/E 1 engine
                this.ws.send(JSON.stringify({
                    command: 'dashboard_cut_me', me: 0,
                    expected_program: prevLive, expected_preview: targetProgram
                }));

            } else {
                // Virtual AUX CUT
                const target = panel.queuedPreviewSourceId;
                const prevLive = panel.onAirSourceId;

                const reason = this.auxCutReason(panel);
                if (reason) { this.showError(reason); return; }

                panel.pending = true;
                panel.pendingTarget = target;
                panel.pendingPrevLive = prevLive;
                panel.pendingSwap = true;
                this.armPendingTimeout(panel, `AUX CUT (${panel.friendlyName})`);

                this.ws.send(JSON.stringify({
                    command: 'dashboard_cut_aux',
                    aux_channel: panel.outNumber - 1,
                    input_source: target,
                    expected_live: prevLive
                }));
            }
        },

        toggleUSK(keyIndex) {
            if (!this.hardwareReady) {
                this.showError('Switcher disconnected or hardware state stale. Keyer toggle unavailable.');
                return;
            }

            const keyer = this.upstreamKeyers.find(k => k.keyIndex === keyIndex);
            if (!keyer || keyer.pending) return;

            keyer.pending = true;
            if (keyer.pendingTimeoutId) clearTimeout(keyer.pendingTimeoutId);
            keyer.pendingTimeoutId = setTimeout(() => {
                keyer.pending = false;
                keyer.pendingTimeoutId = null;
                this.showError(`KEY ${keyIndex + 1} toggle timed out. Hardware did not confirm.`);
            }, 2500);

            this.ws.send(JSON.stringify({
                command: 'toggle_usk',
                key_index: keyIndex,
                me: 0
            }));
        },

        // Master CUT remains disabled in Milestone 2
        cutAll() {
            this.showNotice('Master CUT is scheduled for Milestone 3.');
        },

        // ---------------------------------------------------------------------
        // Pending Timeout Management & Feedback
        // ---------------------------------------------------------------------
        armPendingTimeout(panel, actionLabel) {
            this.clearPendingTimeout(panel);
            panel.pendingTimeoutId = setTimeout(() => {
                this.markUnconfirmed(panel);
                this.showError(`${actionLabel} timed out. Hardware result is unconfirmed; review current state.`);
            }, 3200);
        },

        markUnconfirmed(panel) {
            this.clearPendingTimeout(panel);
            panel.pending = false;
            panel.unconfirmed = true;
        },

        clearPendingTimeout(panel) {
            if (panel.pendingTimeoutId) {
                clearTimeout(panel.pendingTimeoutId);
                panel.pendingTimeoutId = null;
            }
        },

        clearAllPendingTimeouts() {
            this.panels.forEach(p => this.clearPendingTimeout(p));
            this.upstreamKeyers.forEach(k => {
                if (k.pendingTimeoutId) {
                    clearTimeout(k.pendingTimeoutId);
                    k.pendingTimeoutId = null;
                }
            });
        },

        showError(msg) {
            this.actionError = msg;
            if (this.actionNoticeTimer) clearTimeout(this.actionNoticeTimer);
            this.actionNoticeTimer = setTimeout(() => {
                this.actionError = '';
            }, 5000);
        },

        showNotice(msg) {
            this.actionNotice = msg;
            if (this.actionNoticeTimer) clearTimeout(this.actionNoticeTimer);
            this.actionNoticeTimer = setTimeout(() => {
                this.actionNotice = '';
            }, 3000);
        },

        // ---------------------------------------------------------------------
        // Source Catalog Filtering & Helpers
        // ---------------------------------------------------------------------
        get categorizedSources() {
            const physical = [];
            const black = [];
            const colors = [];
            const media = [];

            this.sources.forEach(s => {
                if (s.port_type === 0) {
                    physical.push(s);
                } else if (s.source === 0 || (s.short || '').toUpperCase() === 'BLK' || (s.long || '').toLowerCase().includes('black')) {
                    black.push(s);
                } else if (s.port_type === 4 || s.source === 2001 || s.source === 2002 || (s.short || '').startsWith('COL')) {
                    colors.push(s);
                } else if (s.port_type === 3 || s.source === 3010 || s.source === 3020 || (s.short || '').startsWith('MP')) {
                    media.push(s);
                }
            });

            physical.sort((a, b) => a.source - b.source);
            colors.sort((a, b) => a.source - b.source);
            media.sort((a, b) => a.source - b.source);

            return [...physical, ...black, ...colors, ...media];
        },

        isSourceUsable(panel, source) {
            if (!source) return false;
            if (panel.isME) {
                return source.available_me1 !== false;
            } else {
                return source.available_aux === true;
            }
        },

        getSourceNameById(sourceId) {
            if (sourceId === null || sourceId === undefined) return 'None';
            const s = this.sources.find(src => src.source === sourceId);
            if (!s) return `Source ${sourceId}`;
            return s.long || s.short || `Source ${sourceId}`;
        },

        saveFriendlyName(panel, newName) {
            const trimmed = (newName || '').trim();
            if (trimmed) {
                panel.friendlyName = trimmed;
                try {
                    localStorage.setItem(`webatem_output_name_${panel.outNumber}`, trimmed);
                } catch (e) {}
            }
            panel.editingName = false;
        }
    }));
});
