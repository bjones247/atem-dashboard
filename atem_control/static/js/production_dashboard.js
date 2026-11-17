/**
 * production_dashboard.js — Production Dashboard (3-Output) Client Controller
 * Milestone 1 (Revised):
 * - Support zero, one, or multiple physical outputs carrying M/E Program.
 * - Linked/mirrored M/E outputs share hardware M/E Program, Preview, and Upstream Keyers.
 * - Operators can designate one M/E-fed output as primary without altering hardware routing.
 * - Independent virtual Preview for direct AUX destinations.
 * - Read-only live state with ZERO live hardware writes.
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
            { outNumber: 1, auxKey: 'aux1', friendlyName: 'Output 1', role: 'VirtualAux', isME: false, isMEPrimary: false, isMEMirrored: false, onAirSourceId: null, queuedPreviewSourceId: null, editingName: false },
            { outNumber: 2, auxKey: 'aux2', friendlyName: 'Output 2', role: 'VirtualAux', isME: false, isMEPrimary: false, isMEMirrored: false, onAirSourceId: null, queuedPreviewSourceId: null, editingName: false },
            { outNumber: 3, auxKey: 'aux3', friendlyName: 'Output 3', role: 'VirtualAux', isME: false, isMEPrimary: false, isMEMirrored: false, onAirSourceId: null, queuedPreviewSourceId: null, editingName: false }
        ],

        // Discovered Upstream Keyers on M/E 1
        upstreamKeyers: [],

        // Settings / Display preferences
        labelStyle: 'both', // 'short', 'long', 'both'
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
                this.reconnecting = true;
                this.statusMessage = 'Disconnected. Reconnecting...';
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
                        this.statusMessage = data.message || 'Connection failed.';
                    }
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

            // 3. Update panel live sources and preview queues
            this.updatePanelSources();

            // 4. Update discovered Upstream Keyers on M/E 1
            this.updateUpstreamKeyers();
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
            // Find which managed outputs (OUT 1..3) route M/E 1 Program
            const meMatches = [];
            if (this.me1ProgramSourceId !== null) {
                this.panels.forEach(p => {
                    const routedSource = this.auxOutputs[p.auxKey];
                    if (routedSource === this.me1ProgramSourceId) {
                        meMatches.push(p.outNumber);
                    }
                });
            }

            this.meOutputCount = meMatches.length;

            // Resolve designated primary M/E panel
            let primaryOut = null;
            if (meMatches.length > 0) {
                if (this.primaryMeOutNumber && meMatches.includes(this.primaryMeOutNumber)) {
                    primaryOut = this.primaryMeOutNumber;
                } else {
                    primaryOut = meMatches[0];
                    this.primaryMeOutNumber = primaryOut;
                    try { localStorage.setItem('webatem_primary_me_out', String(primaryOut)); } catch (e) {}
                }
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

        updatePanelSources() {
            this.panels.forEach(p => {
                const routedAuxSource = this.auxOutputs[p.auxKey] ?? null;

                if (p.isME) {
                    // Hardware M/E feed (both primary and linked/mirrored)
                    const me0 = this.mes[0] || {};
                    p.onAirSourceId = me0.program ?? routedAuxSource;
                    // Both primary and linked outputs share real hardware Preview!
                    // Do NOT maintain misleading independent virtual Preview for M/E-fed outputs.
                    p.queuedPreviewSourceId = me0.preview ?? p.onAirSourceId;
                } else {
                    // Independent Virtual AUX output
                    p.onAirSourceId = routedAuxSource;

                    // Revalidate virtual Preview queue for this browser session
                    const storageKey = `webatem_pvw_${this.ipAddress}_out_${p.outNumber}`;
                    let savedPvw = null;
                    try {
                        const val = sessionStorage.getItem(storageKey);
                        if (val !== null && val !== '') savedPvw = parseInt(val, 10);
                    } catch (e) {}

                    const isSavedValid = (savedPvw !== null) && this.sources.some(s => s.source === savedPvw && s.available_aux !== false);

                    if (isSavedValid) {
                        p.queuedPreviewSourceId = savedPvw;
                    } else if (p.queuedPreviewSourceId === null || !this.sources.some(s => s.source === p.queuedPreviewSourceId)) {
                        p.queuedPreviewSourceId = p.onAirSourceId;
                    }
                }
            });
        },

        updateUpstreamKeyers() {
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

                keyers.push({
                    keyIndex: i,
                    label: `KEY ${i + 1}`,
                    onAir: onAir,
                    statusText: onAir ? 'ON AIR' : 'OFF',
                    fillSourceId: fillSourceId,
                    fillLabel: fillLabel
                });
            }

            this.upstreamKeyers = keyers;
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
        // Source Catalog Filtering & Categorization
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
                return source.available_aux !== false;
            }
        },

        getSourceNameById(sourceId) {
            if (sourceId === null || sourceId === undefined) return 'None';
            const s = this.sources.find(src => src.source === sourceId);
            if (!s) return `Source ${sourceId}`;
            return s.long || s.short || `Source ${sourceId}`;
        },

        // ---------------------------------------------------------------------
        // Milestone 1 Interactions: Read-Only & Preview Selection
        // ZERO hardware switching commands sent!
        // ---------------------------------------------------------------------
        selectPreview(panel, sourceId) {
            if (!this.isSourceUsable(panel, this.sources.find(s => s.source === sourceId))) {
                return;
            }

            if (panel.isME) {
                // Linked M/E outputs share Preview: update all M/E panels synchronously
                this.panels.forEach(p => {
                    if (p.isME) {
                        p.queuedPreviewSourceId = sourceId;
                    }
                });
                // In Milestone 1: software tracking, 0 hardware commands sent.
            } else {
                // Virtual AUX output: strictly independent per-output preview
                panel.queuedPreviewSourceId = sourceId;
                try {
                    sessionStorage.setItem(`webatem_pvw_${this.ipAddress}_out_${panel.outNumber}`, String(sourceId));
                } catch (e) {}
            }
        },

        selectProgramDirect(panel, sourceId) {
            // Milestone 1: Direct switching is disabled to prevent accidental live commands.
        },

        cut(panel) {
            // Milestone 1: CUT is disabled.
        },

        cutAll() {
            // Milestone 1: Master CUT is disabled.
        },

        toggleUSK(keyIndex) {
            // Milestone 1: USK toggle is read-only.
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
