/**
 * Production Dashboard client controller.
 * Milestones 2/2.1 switching behavior is retained for regression compatibility;
 * the Milestone 3B dashboard view is read-only; 3C controls use guarded
 * dashboard commands and observed-state confirmation.
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
        outputMappingError: '',
        actionNoticeTimer: null,

        // Authoritative ATEM state
        state: null,
        sources: [],
        auxOutputs: {},
        mes: [],

        // Milestone 3B read-only view and per-device custom switcher names.
        dashboardConfig: null,
        dashboardConfigDeviceId: null,
        dashboardConfigRequestedDeviceId: null,
        dashboardConfigRequestedRevision: null,
        dashboardConfigSaving: false,
        dashboardConfigError: '',
        dashboardConfigSaveTimer: null,
        configSaveExpected: null,
        nameEditingKey: null,
        nameDraft: '',

        // Milestone 3C operation state. Command acceptance is never treated
        // as hardware confirmation.
        previewPending: false,
        previewPendingTarget: null,
        previewPendingTimer: null,
        previewUnconfirmed: false,
        stylePending: false,
        stylePendingTarget: null,
        stylePendingTimer: null,
        primarySetupOperation: null,
        primaryRateEdit: null,
        styleUnconfirmed: false,
        routeOperations: {},
        routeBatch: null,
        assignmentDialogOpen: false,
        assignmentOwner: null,
        assignmentSelection: {},
        assignmentReview: null,
        assignmentBusy: false,
        groupCutOperations: {},
        groupAlignOperations: {},
        groupAlignDraft: null,
        virtualDirect: { virtual1: false, virtual2: false },
        takeAllOperation: null,
        takeAllSequence: 0,
        configSavePurpose: null,

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
        downstreamKeyers: [],

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
                this.upstreamKeyers.forEach(k => {
                    if (k.pending) this.markKeyerUnconfirmed(k);
                });
                this.downstreamKeyers.forEach(k => {
                    if (k.pending) this.markKeyerUnconfirmed(k);
                });
                this.markThreeCOperationsUnconfirmed('Connection closed before the result was confirmed.');
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
                        this.outputMappingError = '';
                        this.statusMessage = data.message || 'Connection failed.';
                        this.panels.forEach(p => {
                            if (p.pending) this.markUnconfirmed(p);
                        });
                        this.clearAllPendingTimeouts();
                        this.upstreamKeyers.forEach(k => {
                            if (k.pending) this.markKeyerUnconfirmed(k);
                        });
                        this.downstreamKeyers.forEach(k => {
                            if (k.pending) this.markKeyerUnconfirmed(k);
                        });
                        this.markThreeCOperationsUnconfirmed('Connection closed before the result was confirmed.');
                    }
                    break;

                case 'error':
                    if (data.command === 'dashboard_take_all' && this.takeAllOperation && !this.takeAllOperation.started) {
                        this.rejectTakeAll(data.message || 'TAKE ALL was blocked. No commands were dispatched.');
                        break;
                    }
                    this.showError(data.message || 'ATEM command rejected');
                    if (data.command === 'dashboard_config_update') {
                        if (this.dashboardConfigSaveTimer !== null) clearTimeout(this.dashboardConfigSaveTimer);
                        this.dashboardConfigSaveTimer = null;
                        this.dashboardConfigSaving = false;
                        this.dashboardConfigError = data.message || 'Configuration update failed.';
                        if (this.routeBatch?.savingConfig) {
                            this.routeBatch.savingConfig = false;
                            this.routeBatch.error = data.message || 'Ownership configuration was not saved.';
                            this.assignmentBusy = false;
                            this.routeBatch = null;
                        }
                        if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('group-cut:')) {
                            const groupId = this.configSavePurpose.split(':')[1];
                            const operation = this.groupCutOperations[groupId];
                            if (operation) {
                                operation.status = 'confirmed_config_failed';
                                operation.error = 'Hardware routes changed, but the saved Preview/Program state was not updated.';
                            }
                        } else if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('group-align:')) {
                            const groupId = this.configSavePurpose.split(':')[1];
                            const operation = this.groupAlignOperations[groupId];
                            if (operation) {
                                operation.status = 'confirmed_config_failed';
                                operation.error = 'Hardware routes changed, but the saved Program target was not updated.';
                            }
                        } else if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('take-all:') && this.takeAllOperation) {
                            this.failTakeAllConfig(data.message || 'Hardware changes were confirmed, but switcher state was not saved.');
                        }
                        this.configSavePurpose = null;
                        this.configSaveExpected = null;
                        this.dashboardConfigRequestedDeviceId = null;
                        this.dashboardConfigRequestedRevision = null;
                    }
                    if (data.command === 'dashboard_output_route' && Number.isInteger(data.output_id)) {
                        this.failRouteOperation(data.output_id, data.message || 'Output route failed.');
                    }
                    if (data.command === 'dashboard_cut_virtual_group' && data.group_id) {
                        const operation = this.groupCutOperations[data.group_id];
                        if (operation) {
                            operation.status = 'blocked';
                            operation.error = data.message || 'Virtual switching was blocked.';
                        }
                    }
                    if (data.command === 'dashboard_align_virtual_group' && data.group_id) {
                        const operation = this.groupAlignOperations[data.group_id];
                        if (operation) {
                            operation.status = 'blocked';
                            operation.error = data.message || 'Mixed-route alignment was blocked.';
                        }
                    }
                    if (data.command === 'dashboard_set_preview_me') {
                        this.previewPending = false;
                        this.previewUnconfirmed = false;
                        if (this.previewPendingTimer !== null) clearTimeout(this.previewPendingTimer);
                        this.previewPendingTimer = null;
                    }
                    if (['dashboard_cut_me', 'dashboard_auto_me', 'dashboard_set_program_me'].includes(data.command)) {
                        this.primaryActionPending = null;
                        if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
                        this.primaryActionTimer = null;
                    }
                    if (data.command === 'dashboard_set_transition_style') {
                        this.stylePending = false;
                        this.styleUnconfirmed = false;
                        if (this.stylePendingTimer !== null) clearTimeout(this.stylePendingTimer);
                        this.stylePendingTimer = null;
                    }
                    if (this.primarySetupOperation && this.primarySetupOperation.command === data.command) {
                        this.clearPrimarySetupOperation();
                    }
                    this.panels.forEach(p => {
                        const affectsPending = !data.command ||
                            (data.command === 'dashboard_cut_me' && p.isME) ||
                            (data.command === 'dashboard_cut_aux' && !p.isME &&
                                p.outNumber - 1 === data.aux_channel);
                        if (p.pending && affectsPending) this.markUnconfirmed(p);
                    });
                    this.upstreamKeyers.forEach(k => {
                        const affectsPending = !data.command ||
                            (data.command === 'dashboard_toggle_usk' && k.keyIndex === data.key_index);
                        if (k.pending && affectsPending) this.markKeyerUnconfirmed(k);
                    });
                    this.downstreamKeyers.forEach(k => {
                        const affectsPending = !data.command ||
                            (data.command === 'dashboard_toggle_dsk' && k.keyIndex === data.dsk);
                        if (k.pending && affectsPending) this.markKeyerUnconfirmed(k);
                    });
                    break;

                case 'dashboard_reviewed':
                    this.panels.forEach(p => {
                        if ((data.kind === 'me' && p.isME) ||
                            (data.kind === 'aux' && !p.isME && p.outNumber - 1 === data.aux_channel)) {
                            p.unconfirmed = false;
                        }
                    });
                    if (data.kind === 'usk') {
                        const keyer = this.upstreamKeyers.find(k => k.keyIndex === data.key_index);
                        if (keyer) {
                            keyer.unconfirmed = false;
                            keyer.pendingTarget = null;
                            keyer.disabledReason = '';
                        }
                    }
                    if (data.kind === 'dsk') {
                        const keyer = this.downstreamKeyers.find(k => k.keyIndex === data.dsk);
                        if (keyer) {
                            keyer.unconfirmed = false;
                            keyer.pendingTarget = null;
                            keyer.disabledReason = '';
                        }
                    }
                    if (data.kind === 'me') {
                        if (this.takeAllOperation?.primary?.status === 'unconfirmed') {
                            this.takeAllOperation.primary.reviewRequested = true;
                        }
                        if (this.primaryActionPending?.keyTargets) {
                            this.primaryActionPending.reviewRequested = true;
                        } else {
                            this.primaryActionPending = null;
                            if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
                            this.primaryActionTimer = null;
                        }
                    }
                    if (data.kind === 'me_preview') {
                        this.previewPending = false;
                        this.previewUnconfirmed = false;
                        if (this.previewPendingTimer !== null) clearTimeout(this.previewPendingTimer);
                        this.previewPendingTimer = null;
                    }
                    if (data.kind === 'style') {
                        this.stylePending = false;
                        this.styleUnconfirmed = false;
                        if (this.stylePendingTimer !== null) clearTimeout(this.stylePendingTimer);
                        this.stylePendingTimer = null;
                    }
                    if (data.kind === 'me_setup') this.clearPrimarySetupOperation();
                    if (data.kind === 'aux' && Number.isInteger(data.aux_channel)) {
                        const outputId = data.aux_channel + 1;
                        const routeOperation = this.routeOperations[String(outputId)];
                        if (routeOperation?.status === 'unconfirmed') routeOperation.reviewRequested = true;
                        for (const operation of Object.values(this.groupCutOperations)) {
                            const item = operation.channels?.find(channel => channel.channel === data.aux_channel);
                            if (item?.status === 'unconfirmed' || (operation.takeAllId && item?.status === 'failed')) item.reviewRequested = true;
                        }
                        for (const operation of Object.values(this.groupAlignOperations)) {
                            const item = operation.channels?.find(channel => channel.channel === data.aux_channel);
                            if (item?.status === 'unconfirmed') item.reviewRequested = true;
                        }
                    }
                    break;

                case 'atem_state':
                    if (data.state) {
                        this.updateState(data.state);
                    }
                    break;

                case 'dashboard_config':
                case 'dashboard_config_changed':
                    this.acceptDashboardConfig(data);
                    break;

                case 'dashboard_primary_destinations_reconciled':
                    if (data.outputs?.length) {
                        this.showNotice('Removed saved virtual assignments for Primary destinations: ' +
                            data.outputs.map(id => `OUT ${id}`).join(', ') + '.');
                    }
                    break;

                case 'dashboard_output_route_accepted':
                    this.acceptOutputRoute(data);
                    break;

                case 'dashboard_group_cut_started':
                    this.acceptGroupCut(data);
                    break;

                case 'dashboard_group_align_started':
                    this.acceptGroupAlign(data);
                    break;

                case 'dashboard_take_all_started':
                    this.acceptTakeAll(data);
                    break;
            }
        },

        updateState(state) {
            for (const groupId of ['virtual1', 'virtual2']) {
                if (!this.virtualDirect[groupId]) continue;
                const previous = this.routingProjection;
                const next = state.dashboardRouting;
                if (!state.is_connected || previous?.deviceId !== next?.deviceId ||
                    JSON.stringify(previous?.groups?.[groupId]?.outputIds) !== JSON.stringify(next?.groups?.[groupId]?.outputIds)) {
                    this.virtualDirect[groupId] = false;
                }
            }
            this.state = state;
            this.connected = !!state.is_connected;
            this.outputMappingError = state.dashboardRouting?.capabilities?.outputMappingReason || '';
            this.atemName = state.atem_name || (this.connected ? 'Connected ATEM' : 'Disconnected');
            this.sources = state.sources || [];
            this.auxOutputs = state.auxOutputs || {};
            this.mes = state.mes || [];
            this.requestDashboardConfig();

            // 1. Discover M/E 1 Program source ID dynamically from state.sources
            this.discoverMeProgramSource();

            // 2. Discover M/E assignment among OUT 1–3 (zero, one, or multiple linked outputs)
            this.mapManagedOutputRoles();

            // 3. Update panel live sources, reconcile pending actions, and update preview
            this.reconcilePanelSources();

            // 4. Update discovered Upstream Keyers on M/E 1
            this.reconcileUpstreamKeyers();
            this.reconcileDownstreamKeyers();
            this.reconcileThreeC();
            this.reconcilePrimarySetup();
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
            const data = usk.data || [];
            const count = Math.max((usk.states || []).length, data.length);

            const previous = this.upstreamKeyers;
            const keyers = [];
            for (let i = 0; i < count; i++) {
                const observed = this.state?.dashboardSafety?.usk?.[String(i)];
                const onAir = typeof observed?.onAir === 'boolean' ? observed.onAir : null;
                const keyData = data[i] || {};
                const fillSourceId = keyData.fill_source ?? null;
                const fillSource = this.sources.find(s => s.source === fillSourceId);
                const fillLabel = fillSource ? (fillSource.short || fillSource.long || `IN ${fillSourceId}`) : (fillSourceId !== null ? `Src ${fillSourceId}` : 'None');

                // Preserve pending state across reconcile
                const existing = previous.find(k => k.keyIndex === i);
                let pending = existing?.pending || false;
                let unconfirmed = existing?.unconfirmed || false;
                let pendingTarget = existing?.pendingTarget ?? null;
                let pendingTimeoutId = existing?.pendingTimeoutId ?? null;

                // Confirm the requested state for this specific keyer.
                if (pendingTarget !== null && onAir === pendingTarget) {
                    if (pendingTimeoutId !== null) clearTimeout(pendingTimeoutId);
                    pending = false;
                    unconfirmed = false;
                    pendingTarget = null;
                    pendingTimeoutId = null;
                }
                const disabledReason = pending ? 'Keyer toggle awaiting hardware confirmation.' :
                    unconfirmed ? 'Previous keyer toggle unconfirmed. Review hardware state.' :
                    onAir === null ? 'Keyer on-air state has not been observed.' :
                    (observed?.reason || '');

                const keyer = existing || {};
                Object.assign(keyer, {
                    keyIndex: i,
                    label: `KEY ${i + 1}`,
                    onAir: onAir,
                    statusText: onAir === null ? 'UNKNOWN' : (onAir ? 'ON AIR' : 'OFF AIR'),
                    fillSourceId: fillSourceId,
                    fillLabel: fillLabel,
                    pending: pending,
                    unconfirmed: unconfirmed,
                    disabledReason: disabledReason,
                    pendingTarget: pendingTarget,
                    pendingTimeoutId: pendingTimeoutId
                });
                keyers.push(keyer);
            }

            // Alpine reuses x-for DOM nodes by key. Replacing their objects
            // left :class and :aria-disabled bound to an older object even
            // though x-text had refreshed. Preserve reactive object identity
            // and replace the array only when the discovered keyer set changes.
            if (keyers.length !== previous.length || keyers.some((k, i) => k !== previous[i])) {
                this.upstreamKeyers = keyers;
            }
        },

        reconcileDownstreamKeyers() {
            const count = this.state?.topology?.dsks;
            if (!Number.isInteger(count) || count < 0) {
                this.downstreamKeyers = [];
                return;
            }
            const previous = this.downstreamKeyers;
            const keyers = [];
            for (let i = 0; i < count; i++) {
                const observed = this.state?.dashboardSafety?.dsk?.[String(i)];
                const onAir = typeof observed?.onAir === 'boolean' ? observed.onAir : null;
                const dsk = this.state?.dsks?.[i] || {};
                const fillSourceId = dsk.fill_source ?? null;
                const fillSource = this.sources.find(s => s.source === fillSourceId);
                const fillLabel = fillSource ? (fillSource.short || fillSource.long || `IN ${fillSourceId}`) :
                    (fillSourceId !== null ? `Src ${fillSourceId}` : 'None');
                const existing = previous.find(k => k.keyIndex === i);
                let pending = existing?.pending || false;
                let unconfirmed = existing?.unconfirmed || false;
                let pendingTarget = existing?.pendingTarget ?? null;
                let pendingTimeoutId = existing?.pendingTimeoutId ?? null;
                if (pendingTarget !== null && onAir === pendingTarget) {
                    if (pendingTimeoutId !== null) clearTimeout(pendingTimeoutId);
                    pending = false;
                    unconfirmed = false;
                    pendingTarget = null;
                    pendingTimeoutId = null;
                }
                const disabledReason = pending ? 'DSK toggle awaiting hardware confirmation.' :
                    unconfirmed ? 'Previous DSK toggle unconfirmed. Review hardware state.' :
                    onAir === null ? 'DSK on-air state has not been observed.' :
                    (observed?.reason || '');
                const keyer = existing || {};
                Object.assign(keyer, {
                    keyIndex: i, label: `DSK ${i + 1}`, onAir,
                    statusText: onAir === null ? 'UNKNOWN' : (onAir ? 'ON AIR' : 'OFF AIR'),
                    fillSourceId, fillLabel, pending, unconfirmed, disabledReason,
                    pendingTarget, pendingTimeoutId
                });
                keyers.push(keyer);
            }
            if (keyers.length !== previous.length || keyers.some((k, i) => k !== previous[i])) {
                this.downstreamKeyers = keyers;
            }
        },

        // ---------------------------------------------------------------------
        // Safety & Guard Checks
        // ---------------------------------------------------------------------
        get meKeyTied() {
            const sel = this.mes?.[0]?.transition?.selection;
            if (!sel) return false;
            return !!(sel.key1 || sel.key2 || sel.key3 || sel.key4);
        },

        get primaryTransitionSelection() {
            return this.primaryTransitionSetup ? this.primaryTransitionSetup.selection :
                this.hardwareMe?.transition?.selection;
        },

        primaryTransitionKeyStates(selection) {
            const before = {};
            const targets = {};
            for (let keyIndex = 0; keyIndex < 4; keyIndex++) {
                if (selection?.[`key${keyIndex + 1}`] !== true) continue;
                const onAir = this.state?.dashboardSafety?.usk?.[String(keyIndex)]?.onAir;
                if (typeof onAir !== 'boolean') return undefined;
                before[String(keyIndex)] = onAir;
                targets[String(keyIndex)] = !onAir;
            }
            return Object.keys(targets).length ? { before, targets } : null;
        },

        primaryKeyedTransitionOutcome(operation) {
            if (!this.hardwareReady) return 'unknown';
            const program = this.hardwareProgramSourceId;
            const transition = this.hardwareMe?.transition;
            if (!transition || transition.in_transition !== false || transition.position !== 0) return 'in-progress';
            const keys = this.state?.dashboardSafety?.usk;
            if (program === operation.target && Object.entries(operation.keyTargets)
                .every(([index, onAir]) => keys?.[index]?.onAir === onAir)) return 'confirmed';
            if (program === operation.before && Object.entries(operation.keyBefore)
                .every(([index, onAir]) => keys?.[index]?.onAir === onAir)) return 'unchanged';
            return 'partial';
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
            const keyer = this.upstreamKeyers.find(k => k.keyIndex === keyIndex);
            if (!keyer) return;
            const reason = this.primaryUskToggleReason(keyer);
            if (reason) { this.showError(reason); return; }

            keyer.pending = true;
            keyer.pendingTarget = !keyer.onAir;
            keyer.disabledReason = 'Keyer toggle awaiting hardware confirmation.';
            if (keyer.pendingTimeoutId !== null) clearTimeout(keyer.pendingTimeoutId);
            keyer.pendingTimeoutId = setTimeout(() => {
                const current = this.upstreamKeyers.find(k => k.keyIndex === keyIndex);
                if (current?.pending) {
                    this.markKeyerUnconfirmed(current);
                    this.showError(`KEY ${keyIndex + 1} toggle timed out. Hardware result is unconfirmed.`);
                }
            }, 3200);

            this.ws.send(JSON.stringify({
                command: 'dashboard_toggle_usk',
                key_index: keyIndex,
                expected_on_air: keyer.onAir,
                target_on_air: keyer.pendingTarget,
                me: 0
            }));
        },

        toggleDSK(keyIndex) {
            const keyer = this.downstreamKeyers.find(k => k.keyIndex === keyIndex);
            if (!keyer) return;
            const reason = this.keyerToggleReason(keyer);
            if (reason) { this.showError(reason); return; }

            keyer.pending = true;
            keyer.pendingTarget = !keyer.onAir;
            keyer.disabledReason = 'DSK toggle awaiting hardware confirmation.';
            if (keyer.pendingTimeoutId !== null) clearTimeout(keyer.pendingTimeoutId);
            keyer.pendingTimeoutId = setTimeout(() => {
                const current = this.downstreamKeyers.find(k => k.keyIndex === keyIndex);
                if (current?.pending) {
                    this.markKeyerUnconfirmed(current);
                    this.showError(`DSK ${keyIndex + 1} toggle timed out. Hardware result is unconfirmed.`);
                }
            }, 3200);

            this.ws.send(JSON.stringify({
                command: 'dashboard_toggle_dsk', dsk: keyIndex,
                expected_on_air: keyer.onAir, target_on_air: keyer.pendingTarget
            }));
        },

        primaryUskToggleReason(keyer) {
            if (typeof this.primaryActionPending?.keyTargets?.[keyer.keyIndex] === 'boolean') {
                return 'This key is part of a pending or unconfirmed Primary transition.';
            }
            return this.keyerToggleReason(keyer);
        },

        keyerToggleReason(keyer) {
            if (!this.hardwareReady) return 'Switcher disconnected or hardware state stale.';
            return keyer.disabledReason || '';
        },

        markKeyerUnconfirmed(keyer) {
            if (keyer.pendingTimeoutId !== null) clearTimeout(keyer.pendingTimeoutId);
            keyer.pendingTimeoutId = null;
            keyer.pending = false;
            keyer.unconfirmed = true;
            keyer.disabledReason = 'Previous keyer toggle unconfirmed. Review hardware state.';
        },

        reviewKeyer(keyIndex) {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({command: 'dashboard_review_usk', key_index: keyIndex}));
        },

        reviewDSK(keyIndex) {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({command: 'dashboard_review_dsk', dsk: keyIndex}));
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
            [...this.upstreamKeyers, ...this.downstreamKeyers].forEach(k => {
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
            const bars = [];
            const colors = [];
            const media = [];

            this.sources.forEach(s => {
                if (s.port_type === 0) {
                    physical.push(s);
                } else if (s.port_type === 2) {
                    bars.push(s);
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

            return [...physical, ...black, ...bars, ...colors, ...media];
        },

        get sourceButtonChoices() {
            return this.categorizedSources.filter(source =>
                source.port_type !== 5 && source.source !== 3011 && source.source !== 3021);
        },

        get meButtonSources() {
            return this.sourceButtonChoices.filter(source => source.available_me1 === true || source.port_type === 2);
        },

        get primaryBusLayout() {
            return this.sourceBusLayout(this.meButtonSources);
        },

        get virtualBusLayout() {
            return this.sourceBusLayout(this.auxButtonSources);
        },

        sourceBusLayout(sources) {
            const inputs = [];
            const black = [];
            const bars = [];
            const colors = [];
            const media = [];
            for (const source of sources) {
                if (source.port_type === 0) inputs.push(source);
                else if (source.port_type === 2) bars.push(source);
                else if (source.source === 0 || source.port_type === 1) black.push(source);
                else if (source.port_type === 3) colors.push(source);
                else media.push(source);
            }

            const split = Math.ceil(inputs.length / 2);
            const inputColumns = Math.max(split, 1);
            const middleColumns = Math.max(black.length, bars.length, 1);
            const rightColumns = Math.max(colors.length, media.length, 1);
            // The spacer tracks separate inputs, Black/Bars, and colors/media.
            const sectionStarts = [1, inputColumns + 2, inputColumns + middleColumns + 3];
            const rows = [[inputs.slice(0, split), black, colors], [inputs.slice(split), bars, media]];
            const buttons = rows.flatMap((sections, row) => sections.flatMap((items, section) =>
                items.map((source, column) => ({ source, row: row + 1, column: sectionStarts[section] + column }))));
            return {
                columns: { '--input-columns': inputColumns, '--middle-columns': middleColumns,
                    '--right-columns': rightColumns },
                buttons,
            };
        },

        primaryKeyerColumn(index) {
            const tracks = this.primaryBusLayout.columns;
            const inputs = tracks['--input-columns'];
            const middle = tracks['--middle-columns'];
            return index + 1 + (index >= inputs ? 1 : 0) + (index >= inputs + middle ? 1 : 0);
        },

        get auxButtonSources() {
            return this.sourceButtonChoices.filter(source => source.available_aux === true || source.port_type === 2);
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

        getSourceShortNameById(sourceId) {
            if (sourceId === null || sourceId === undefined) return 'Not set';
            const source = this.sources.find(item => item.source === sourceId);
            return source ? (source.short || source.long || `Source ${sourceId}`) : `Unavailable source ${sourceId}`;
        },

        get routingProjection() {
            return this.state?.dashboardRouting || null;
        },

        get projectedOutputs() {
            // Projection may retain unexpected AUX indices for diagnostics.
            // Only mapped physical connectors have an outputId/OUT label and
            // are shown as physical outputs in this installation's UI.
            return Array.isArray(this.routingProjection?.outputs)
                ? this.routingProjection.outputs.filter(output => Number.isInteger(output.outputId)) : [];
        },

        get primarySwitcherOutputs() {
            return this.projectedOutputs.filter(output => output.owner === 'primary');
        },

        get virtualSwitcherViews() {
            const projection = this.routingProjection;
            return ['virtual1', 'virtual2'].map((key, index) => {
                const group = projection?.groups?.[key] || {};
                return {
                    key,
                    title: this.switcherName(key, `Virtual Switcher ${index + 1}`),
                    // Only validated ownership is shown as an assignment badge.
                    outputs: this.projectedOutputs.filter(output => output.owner === key),
                    group,
                    routeWarning: this.groupRouteWarning(key),
                    invalidAssignments: this.invalidAssignmentsFor(key),
                };
            });
        },

        get otherOutputViews() {
            return this.projectedOutputs.filter(output =>
                !['primary', 'virtual1', 'virtual2'].includes(output.owner));
        },

        get primarySwitcherName() {
            return this.switcherName('primary', 'Primary Switcher');
        },

        get hardwareMe() {
            return this.mes[0] || null;
        },

        get hardwareProgramSourceId() {
            if (!this.connected || !this.state) return null;
            return this.hardwareMe?.program ?? this.state?.dashboardSafety?.meCut?.program ?? null;
        },

        get hardwarePreviewSourceId() {
            if (!this.connected || !this.state) return null;
            return this.hardwareMe?.preview ?? this.state?.dashboardSafety?.meCut?.preview ?? null;
        },

        get meObservationStale() {
            return this.routingProjection?.stateFresh === false || this.state?.dashboardSafety?.fresh === false;
        },

        switcherName(key, fallback) {
            const config = this.dashboardConfigDeviceId === this.routingProjection?.deviceId
                ? this.dashboardConfig?.config : null;
            const value = config?.customNames?.[key];
            return typeof value === 'string' && value.trim() ? value.trim() : fallback;
        },

        invalidAssignmentsFor(key) {
            const conflicts = this.routingProjection?.conflicts || [];
            return conflicts.filter(conflict => conflict.group === key ||
                (Array.isArray(conflict.groups) && conflict.groups.includes(key)));
        },

        sourceStateLabel(sourceId) {
            if (sourceId === null || sourceId === undefined) return 'Not observed';
            return this.getSourceShortNameById(sourceId);
        },

        requestDashboardConfig() {
            const deviceId = this.routingProjection?.deviceId;
            if (!this.connected || !deviceId || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            const projectionRevision = this.routingProjection?.revision;
            const configRevision = this.dashboardConfigDeviceId === deviceId ? this.dashboardConfig?.revision : null;
            if (configRevision === projectionRevision ||
                (configRevision !== null && projectionRevision != null && configRevision > projectionRevision)) return;
            if (this.dashboardConfigRequestedDeviceId === deviceId &&
                this.dashboardConfigRequestedRevision === projectionRevision) return;
            this.dashboardConfigRequestedDeviceId = deviceId;
            this.dashboardConfigRequestedRevision = projectionRevision;
            this.ws.send(JSON.stringify({ command: 'dashboard_config_get' }));
        },

        acceptDashboardConfig(data) {
            if (!data || !data.deviceId || !data.config) return;
            const projectedDeviceId = this.routingProjection?.deviceId;
            if (projectedDeviceId && data.deviceId !== projectedDeviceId) return;
            if (this.dashboardConfigDeviceId === data.deviceId &&
                this.dashboardConfig && data.revision < this.dashboardConfig.revision) return;
            this.dashboardConfigDeviceId = data.deviceId;
            this.dashboardConfig = { deviceId: data.deviceId, revision: data.revision, config: data.config };
            this.dashboardConfigRequestedDeviceId = data.deviceId;
            const projectionRevision = this.routingProjection?.revision;
            this.dashboardConfigRequestedRevision = (
                projectionRevision === data.revision ||
                (projectionRevision != null && data.revision > projectionRevision)
            ) ? projectionRevision : null;
            this.dashboardConfigSaving = false;
            if (this.dashboardConfigSaveTimer !== null) clearTimeout(this.dashboardConfigSaveTimer);
            this.dashboardConfigSaveTimer = null;
            this.dashboardConfigError = '';
            if (this.configSavePurpose) {
                const matchesPendingSave = JSON.stringify(this.configSaveExpected) === JSON.stringify(data.config);
                if (matchesPendingSave) {
                    const completedSavePurpose = this.configSavePurpose;
                    if (this.routeBatch?.savingConfig) {
                        const batchError = this.routeBatch.error;
                        this.routeBatch = null;
                        this.assignmentBusy = false;
                        this.assignmentDialogOpen = false;
                        if (batchError) {
                            this.showError(`Confirmed ownership changes were saved, but some output operations failed: ${batchError}`);
                        } else {
                            this.showNotice('Output ownership changes saved.');
                        }
                    }
                    if (this.configSavePurpose.startsWith('group-cut:')) this.finishGroupCutConfig(data);
                    else if (this.configSavePurpose.startsWith('group-align:')) this.finishGroupAlignConfig(data);
                    else if (this.configSavePurpose.startsWith('take-all:')) this.finishTakeAllConfig(data);
                    else this.configSavePurpose = null;
                    if (!this.configSavePurpose || this.configSavePurpose === completedSavePurpose) {
                        this.configSaveExpected = null;
                    }
                } else {
                    const message = 'Another dashboard session changed the configuration first. Review the refreshed settings; confirmed hardware routes are shown separately.';
                    if (this.routeBatch?.savingConfig) {
                        this.routeBatch.error = message;
                        this.routeBatch = null;
                        this.assignmentBusy = false;
                    }
                    if (this.configSavePurpose.startsWith('group-cut:')) {
                        const groupId = this.configSavePurpose.split(':')[1];
                        const operation = this.groupCutOperations[groupId];
                        if (operation) {
                            operation.status = 'confirmed_config_failed';
                            operation.error = message;
                        }
                    } else if (this.configSavePurpose.startsWith('group-align:')) {
                        const groupId = this.configSavePurpose.split(':')[1];
                        const operation = this.groupAlignOperations[groupId];
                        if (operation) {
                            operation.status = 'confirmed_config_failed';
                            operation.error = message;
                        }
                    } else if (this.configSavePurpose.startsWith('take-all:') && this.takeAllOperation) {
                        this.failTakeAllConfig(message);
                    }
                    this.dashboardConfigError = message;
                    this.configSavePurpose = null;
                    this.configSaveExpected = null;
                    this.showError(message);
                }
            }
        },

        beginNameEdit(key, currentName) {
            if (!this.dashboardConfig || this.dashboardConfigSaving) return;
            this.nameEditingKey = key;
            this.nameDraft = currentName;
            this.dashboardConfigError = '';
        },

        cancelNameEdit() {
            this.nameEditingKey = null;
            this.nameDraft = '';
        },

        saveSwitcherName(key) {
            if (!this.dashboardConfig || this.dashboardConfigDeviceId !== this.routingProjection?.deviceId || this.dashboardConfigSaving || !this.ws ||
                this.ws.readyState !== WebSocket.OPEN) return;
            const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
            const trimmed = (this.nameDraft || '').trim();
            const defaults = { primary: 'Primary Switcher', virtual1: 'Virtual Switcher 1', virtual2: 'Virtual Switcher 2' };
            config.customNames[key] = trimmed && trimmed !== defaults[key] ? trimmed : null;
            this.dashboardConfigError = '';
            this.sendDashboardConfig(config, 'name');
            this.nameEditingKey = null;
        },

        outputStatus(output) {
            const labels = {
                observed: 'Live route observed', stale: 'Hardware observation is stale',
                unobserved: 'Route has not been observed', topology_mismatch: 'Output mapping unavailable: AUX topology mismatch',
                malformed: 'Hardware route is malformed', source_missing: 'Routed source is unavailable',
            };
            return labels[output?.routeStatus] || 'Output state unresolved';
        },

        outputSourceId(output) {
            if (output?.routeStatus === 'observed') return output.liveSourceId;
            if (output?.routeStatus === 'stale') return output.lastObservedSourceId;
            return null;
        },

        outputConflictText(output) {
            const conflicts = output?.conflicts || [];
            if (!conflicts.length) return '';
            return conflicts.map(item => item.reason || item.type.replaceAll('_', ' ')).join('; ');
        },

        groupOutputOperation(groupId, auxIndex) {
            const alignment = this.groupAlignOperations[groupId];
            const aligned = alignment?.channels?.find(item => item.channel === auxIndex);
            if (aligned && !['complete', 'blocked'].includes(alignment.status)) return aligned;
            return this.groupCutOperations[groupId]?.channels?.find(item => item.channel === auxIndex) || null;
        },

        groupRouteWarning(groupId) {
            const group = this.routingProjection?.groups?.[groupId];
            if (!Array.isArray(group?.outputIds)) return null;
            const alignment = this.groupAlignOperations[groupId];
            const cut = this.groupCutOperations[groupId];
            const active = status => ['pending', 'partial', 'unconfirmed', 'saving'].includes(status);
            const confirmedTakeAllAwaitingSave = cut?.status === 'confirmed' && !cut.configSaved &&
                Number.isInteger(cut.takeAllId) &&
                cut.takeAllId === this.takeAllOperation?.id &&
                ['preflight', 'pending', 'unconfirmed', 'saving'].includes(this.takeAllOperation.status);
            const configFailedOnCurrentRoute = operation => operation?.status === 'confirmed_config_failed' &&
                group.routeStatus === 'uniform' && group.liveSourceId === operation.target;
            const operation = active(cut?.status) || confirmedTakeAllAwaitingSave ? cut : active(alignment?.status) ? alignment
                : configFailedOnCurrentRoute(cut) ? cut
                    : configFailedOnCurrentRoute(alignment) ? alignment : null;
            if (!group.outputIds.length && !operation) return null;
            if (operation?.status === 'pending' && !operation.showMismatchWhilePending &&
                !operation.channels?.some(item => ['failed', 'unconfirmed'].includes(item.status))) return null;
            const savedTarget = this.dashboardConfigDeviceId === this.routingProjection.deviceId &&
                this.dashboardConfig?.revision > this.routingProjection.revision
                ? this.dashboardConfig.config.virtualSwitchers[groupId].programTarget : group.savedProgramTargetId;
            const expectedSourceId = Number.isInteger(operation?.target)
                ? operation.target : savedTarget;
            const expectedKnown = Number.isInteger(expectedSourceId);
            const routes = new Map((group.outputs || []).map(route => [route.outputId, route]));
            for (const { channel } of operation?.channels || []) {
                const outputId = channel + 1;
                if (!routes.has(outputId)) {
                    routes.set(outputId, this.projectedOutputs.find(output => output.outputId === outputId) || { outputId });
                }
            }
            const outputs = [...routes.values()].map(route => {
                const observed = route.routeStatus === 'observed' && Number.isInteger(route.liveSourceId);
                const matchesExpected = observed && expectedKnown ? route.liveSourceId === expectedSourceId : null;
                const channel = Number.isInteger(route.outputId) ? route.outputId - 1 : null;
                const result = operation?.channels?.find(item => item.channel === channel);
                return {
                    outputId: route.outputId,
                    marker: matchesExpected === null ? '?' : matchesExpected ? '✓' : '×',
                    matchesExpected,
                    observed,
                    label: observed ? this.sourceStateLabel(route.liveSourceId)
                        : route.routeStatus === 'stale'
                            ? `stale; last seen ${this.sourceStateLabel(route.lastObservedSourceId)}`
                            : this.outputStatus(route),
                    error: result && ['failed', 'unconfirmed'].includes(result.status) ? result.error : '',
                    reviewable: result?.status === 'unconfirmed',
                };
            });
            const mismatch = outputs.some(output => output.matchesExpected === false);
            const missingOutputs = group.outputIds.some(id => !routes.has(id));
            const unknown = missingOutputs ||
                outputs.some(output => output.matchesExpected === null);
            const operationIssue = operation && ['partial', 'unconfirmed', 'confirmed_config_failed'].includes(operation.status);
            if (!mismatch && !unknown && !operationIssue && expectedKnown && group.routeStatus === 'uniform') return null;
            return {
                title: mismatch ? 'Output mismatch warning:' : unknown || !expectedKnown
                    ? 'Output state warning:' : 'Output confirmation warning:',
                expected: expectedKnown ? this.sourceStateLabel(expectedSourceId) : 'unknown',
                outputs,
                missingOutputs,
                error: operationIssue ? operation.error || '' : '',
            };
        },

        sendDashboardConfig(config, purpose = null) {
            if (!this.dashboardConfig || this.dashboardConfigSaving || !this.ws ||
                this.ws.readyState !== WebSocket.OPEN ||
                this.dashboardConfigDeviceId !== this.routingProjection?.deviceId) return false;
            this.dashboardConfigSaving = true;
            this.configSavePurpose = purpose;
            this.configSaveExpected = JSON.parse(JSON.stringify(config));
            this.ws.send(JSON.stringify({ command: 'dashboard_config_update',
                expected_revision: this.dashboardConfig.revision, config }));
            if (this.dashboardConfigSaveTimer !== null) clearTimeout(this.dashboardConfigSaveTimer);
            this.dashboardConfigSaveTimer = setTimeout(() => {
                this.dashboardConfigSaveTimer = null;
                this.dashboardConfigSaving = false;
                this.dashboardConfigError = 'Configuration save result is unknown. Reloaded settings will show whether it was committed.';
                if (this.routeBatch?.savingConfig) {
                    this.routeBatch.error = this.dashboardConfigError;
                    this.routeBatch = null;
                    this.assignmentBusy = false;
                }
                if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('group-cut:')) {
                    const groupId = this.configSavePurpose.split(':')[1];
                    const operation = this.groupCutOperations[groupId];
                    if (operation) {
                        operation.status = 'confirmed_config_failed';
                        operation.error = 'Output routes are confirmed, but the saved Preview/Program result is unknown.';
                    }
                } else if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('group-align:')) {
                    const groupId = this.configSavePurpose.split(':')[1];
                    const operation = this.groupAlignOperations[groupId];
                    if (operation) {
                        operation.status = 'confirmed_config_failed';
                        operation.error = 'Output routes are confirmed, but the saved Program target result is unknown.';
                    }
                } else if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('take-all:') && this.takeAllOperation) {
                    this.failTakeAllConfig(this.dashboardConfigError);
                }
                this.configSavePurpose = null;
                this.configSaveExpected = null;
                this.dashboardConfigRequestedDeviceId = null;
                this.dashboardConfigRequestedRevision = null;
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ command: 'dashboard_config_get' }));
                }
                this.showError(this.dashboardConfigError);
            }, 5000);
            return true;
        },

        setVirtualPreview(groupId, sourceId) {
            if (!this.hardwareReady || !this.dashboardConfig || this.dashboardConfigSaving ||
                !['virtual1', 'virtual2'].includes(groupId)) return;
            const source = this.sources.find(item => item.source === sourceId);
            if (!Number.isInteger(sourceId) || !source || source.available_aux !== true) return;
            const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
            config.virtualSwitchers[groupId].previewSource = sourceId;
            this.sendDashboardConfig(config, 'preview');
        },

        setEmptyVirtualProgramTarget(groupId, sourceId) {
            if (!this.hardwareReady || !this.dashboardConfig || this.dashboardConfigSaving ||
                !['virtual1', 'virtual2'].includes(groupId) ||
                this.routingProjection?.groups?.[groupId]?.routeStatus !== 'empty') return;
            const source = this.sources.find(item => item.source === sourceId);
            if (!Number.isInteger(sourceId) || !source || source.available_aux !== true ||
                sourceId === this.routingProjection?.capabilities?.programOutputSourceId) return;
            const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
            config.virtualSwitchers[groupId].programTarget = sourceId;
            this.sendDashboardConfig(config, 'program-target');
        },

        primaryPreviewReason(sourceId) {
            if (!this.hardwareReady) return 'Switcher disconnected or state is stale.';
            if (this.previewUnconfirmed) return 'Previous M/E Preview command is unconfirmed; review hardware state.';
            if (this.previewPending) return 'M/E Preview change is awaiting hardware confirmation.';
            if (this.primaryActionPending) return 'A Primary switching operation is pending.';
            const source = this.sources.find(item => item.source === sourceId);
            return source && source.available_me1 === true ? '' : 'Source is not available to M/E 1.';
        },

        selectPrimaryPreview(sourceId) {
            if (this.primaryPreviewReason(sourceId) || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            const current = this.hardwarePreviewSourceId;
            if (!Number.isInteger(current) || current === sourceId) return;
            this.previewPending = true;
            this.previewUnconfirmed = false;
            this.previewPendingTarget = sourceId;
            this.previewPendingTimer = setTimeout(() => {
                if (this.previewPending) {
                    this.previewPending = false;
                    this.previewUnconfirmed = true;
                    this.previewPendingTimer = null;
                    this.showError('M/E Preview selection timed out; hardware result is unconfirmed.');
                }
            }, 3500);
            this.ws.send(JSON.stringify({ command: 'dashboard_set_preview_me', me: 0,
                source: sourceId, expected_preview: current }));
        },

        primaryProgramReason(sourceId) {
            if (this.programSelectionMode !== 'direct') return 'Direct Program mode is not enabled.';
            if (!this.hardwareReady) return 'Switcher disconnected or state is stale.';
            if (this.primaryActionPending || this.previewPending) return 'A Primary switching operation is pending.';
            const source = this.sources.find(item => item.source === sourceId);
            return source && source.available_me1 === true ? '' : 'Source is not available to M/E 1.';
        },

        selectPrimaryProgram(sourceId) {
            if (this.primaryProgramReason(sourceId) || !this.ws || this.ws.readyState !== WebSocket.OPEN ||
                sourceId === this.hardwareProgramSourceId) return;
            this.primaryActionPending = { kind: 'program', target: sourceId, before: this.hardwareProgramSourceId };
            this.armPrimaryOperationTimeout();
            this.ws.send(JSON.stringify({ command: 'dashboard_set_program_me', me: 0,
                source: sourceId, expected_program: this.hardwareProgramSourceId }));
        },

        primaryCutReason() {
            if (!this.hardwareReady) return 'Switcher disconnected or state is stale.';
            if (this.primaryActionPending || this.previewPending) return 'A Primary switching operation is pending.';
            if (this.primarySetupPendingReason) return this.primarySetupPendingReason;
            if (this.primaryTransitionSetup && 'cutReason' in this.primaryTransitionSetup) {
                if (this.upstreamKeyers.some(key => (key.pending || key.unconfirmed) &&
                        this.primaryTransitionSelection?.[`key${key.keyIndex + 1}`] === true)) {
                    return 'A selected keyer has a pending or unconfirmed ON AIR change.';
                }
                return this.primaryTransitionSetup.cutReason || '';
            }
            if (![1, 2, 3, 4].some(i => this.primaryTransitionSelection?.[`key${i}`] === true)) {
                return this.meCutReason;
            }
            return this.primaryTransitionReason();
        },

        primaryCut() {
            const reason = this.primaryCutReason();
            if (reason) { this.showError(reason); return; }
            this.dispatchPrimaryTransition('cut');
        },

        reviewPrimaryOperation() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({ command: 'dashboard_review_me' }));
        },

        reviewPrimaryPreview() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({ command: 'dashboard_review_me_preview' }));
        },

        reviewTransitionStyle() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({ command: 'dashboard_review_style' }));
        },

        get primaryActionPending() { return this._primaryActionPending || null; },
        set primaryActionPending(value) { this._primaryActionPending = value; },

        armPrimaryOperationTimeout() {
            if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
            this.primaryActionTimer = setTimeout(() => {
                if (this.primaryActionPending) {
                    this.primaryActionPending.unconfirmed = true;
                    if (this.primaryActionPending.takeAllId && this.takeAllOperation?.id === this.primaryActionPending.takeAllId) {
                        this.takeAllOperation.primary.status = 'unconfirmed';
                        this.takeAllOperation.primary.error = 'Primary result is unconfirmed; review current M/E state.';
                        this.takeAllOperation.status = 'unconfirmed';
                    }
                    this.showError('Primary operation timed out; hardware result is unconfirmed. Review current state.');
                }
            }, 3500);
        },

        primaryAutoReason() {
            if (!this.hardwareReady) return 'Switcher disconnected or state is stale.';
            if (this.primaryActionPending || this.previewPending) return 'A Primary switching operation is pending.';
            if (this.primarySetupPendingReason) return this.primarySetupPendingReason;
            if (this.stylePending || this.styleUnconfirmed) return 'The transition style is pending or unconfirmed.';
            return this.primaryTransitionReason();
        },

        primaryTransitionReason() {
            const transition = this.hardwareMe?.transition;
            if (!transition || typeof transition.in_transition !== 'boolean' ||
                !Number.isInteger(transition.position) || transition.in_transition || transition.position !== 0) {
                return 'M/E transition state is unknown or not at rest.';
            }
            if (!Number.isInteger(this.hardwareProgramSourceId) || !Number.isInteger(this.hardwarePreviewSourceId)) return 'M/E Program or Preview is unknown.';
            const selection = this.primaryTransitionSelection;
            if (!selection || typeof selection.background !== 'boolean' ||
                [1, 2, 3, 4].some(i => typeof selection[`key${i}`] !== 'boolean')) return 'Next-transition selection is unknown or incomplete.';
            const keys = this.primaryTransitionKeyStates(selection);
            if (keys === undefined) return 'A selected keyer on-air state has not been observed.';
            if (!selection.background && !keys) return 'No M/E background or keyer is selected for the transition.';
            if (!keys && this.hardwareProgramSourceId === this.hardwarePreviewSourceId) return 'M/E Preview is already live.';
            if (keys && this.upstreamKeyers.some(key => key.keyIndex in keys.targets && (key.pending || key.unconfirmed))) {
                return 'A selected keyer has a pending or unconfirmed ON AIR change.';
            }
            return '';
        },

        primaryAuto() {
            const reason = this.primaryAutoReason();
            if (reason) { this.showError(reason); return; }
            this.dispatchPrimaryTransition('auto');
        },

        primaryTransitionRequest() {
            const selection = this.primaryTransitionSelection;
            const keys = this.primaryTransitionKeyStates(selection);
            if (!selection || keys === undefined) return null;
            const before = this.hardwareProgramSourceId;
            const preview = this.hardwarePreviewSourceId;
            return {
                request: { expected_program: before, expected_preview: preview,
                    expected_selection: selection, expected_key_states: keys?.before },
                result: { before, target: selection.background ? preview : before,
                    keyBefore: keys?.before, keyTargets: keys?.targets },
            };
        },

        dispatchPrimaryTransition(kind) {
            if (this.ws?.readyState !== WebSocket.OPEN) return;
            const transition = this.primaryTransitionRequest();
            if (!transition) return;
            this.primaryActionPending = { kind, ...transition.result };
            this.armPrimaryOperationTimeout();
            this.ws.send(JSON.stringify({ command: kind === 'cut' ? 'dashboard_cut_me' : 'dashboard_auto_me', me: 0,
                ...transition.request,
                expected_style: kind === 'auto' ? this.hardwareMe?.transition?.style : undefined }));
        },

        finishPrimaryAction(operation, status, error = '') {
            this.primaryActionPending = null;
            if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
            this.primaryActionTimer = null;
            if (operation.takeAllId && this.takeAllOperation?.id === operation.takeAllId) {
                this.takeAllOperation.primary.status = status;
                this.takeAllOperation.primary.error = error;
                this.tryFinalizeTakeAll();
            }
        },

        transitionStyles: [
            { value: 0, label: 'MIX' }, { value: 1, label: 'DIP' },
            { value: 2, label: 'WIPE' }, { value: 3, label: 'DVE' },
            { value: 4, label: 'STNGR' },
        ],

        get primaryTransitionSetup() {
            return this.state?.dashboardSafety?.meSetup;
        },

        get primarySetupPendingReason() {
            return this.primaryTransitionSetup?.pendingReason ||
                (this.primarySetupOperation?.unconfirmed ? 'Transition settings are unconfirmed. Review current state.' :
                    this.primarySetupOperation ? 'Transition settings are awaiting hardware confirmation.' : '');
        },

        primarySetupReason() {
            if (!this.hardwareReady || this.ws?.readyState !== WebSocket.OPEN) return 'Switcher disconnected or state is stale.';
            if (this.primarySetupPendingReason) return this.primarySetupPendingReason;
            if (this.primaryActionPending || this.stylePending || this.styleUnconfirmed ||
                this.hardwareMe?.transition?.in_transition !== false || this.hardwareMe?.transition?.position !== 0) {
                return 'Wait for the Primary transition controls to settle.';
            }
            return '';
        },

        primaryLayerReason(layer) {
            const reason = this.primarySetupReason();
            if (reason) return reason;
            const selection = this.primaryTransitionSetup?.selection;
            if (typeof selection?.[layer] !== 'boolean') return 'Next-transition layers have not been observed.';
            if (selection[layer] && Object.values(selection).filter(Boolean).length === 1) {
                return 'Keep at least one layer selected for the next transition.';
            }
            return '';
        },

        togglePrimaryLayer(layer) {
            if (this.primaryLayerReason(layer)) return;
            const selection = this.primaryTransitionSetup.selection;
            this.sendPrimarySetup('dashboard_set_transition_layer',
                { layer, expected_selection: selection }, { selection: { ...selection, [layer]: !selection[layer] } });
        },

        primaryRateReason() {
            const reason = this.primarySetupReason();
            if (reason) return reason;
            const { style } = this.primaryTransitionSetup || {};
            return this.primaryRateDisplay && this.transitionStyleSupported(style) ? '' :
                'The selected transition rate has not been observed.';
        },

        get primaryRateDisplay() {
            const { rate, fps } = this.primaryTransitionSetup || {};
            if (!Number.isInteger(rate) || !Number.isInteger(fps) || fps < 1) return null;
            return Math.floor(rate / fps) + ':' + String(rate % fps).padStart(2, '0');
        },

        beginPrimaryRateEdit() {
            if (this.primaryRateReason()) return;
            const { style, rate, fps } = this.primaryTransitionSetup;
            this.primaryRateEdit = { style, rate, fps, initialText: this.primaryRateDisplay };
        },

        finishPrimaryRateEdit(value) {
            const edit = this.primaryRateEdit;
            this.primaryRateEdit = null;
            if (!edit || this.primaryRateReason() || value.trim() === edit.initialText) return;
            const { style, rate: currentRate, fps } = this.primaryTransitionSetup;
            if (edit.style !== style || edit.rate !== currentRate || edit.fps !== fps) {
                this.showError('Transition style, rate or timebase changed while editing. Review the current rate.');
                return;
            }
            const match = /^(\d{1,2}):(\d{1,2})$/.exec(value.trim());
            const frames = match ? Number(match[2]) : NaN;
            const rate = match ? Number(match[1]) * fps + frames : NaN;
            if (!Number.isInteger(rate) || frames >= fps || rate < 1 || rate > 60) {
                this.showError('Enter a rate as seconds:frames, between 1 and 60 total frames.');
                return;
            }
            if (rate === currentRate) return;
            this.sendPrimarySetup('dashboard_set_transition_rate',
                { expected_style: edit.style, expected_rate: edit.rate, rate }, { style: edit.style, rate });
        },

        sendPrimarySetup(command, params, target) {
            const operation = { command, target, unconfirmed: false, timer: null };
            this.primarySetupOperation = operation;
            operation.timer = setTimeout(() => {
                if (this.primarySetupOperation?.command === command) this.primarySetupOperation.unconfirmed = true;
            }, 3500);
            this.ws.send(JSON.stringify({ command, me: 0, ...params }));
        },

        clearPrimarySetupOperation() {
            if (this.primarySetupOperation) clearTimeout(this.primarySetupOperation.timer);
            this.primarySetupOperation = null;
        },

        reconcilePrimarySetup() {
            const target = this.primarySetupOperation?.target;
            const setup = this.primaryTransitionSetup;
            if (!target || !setup || !this.hardwareReady) return;
            const confirmed = target.selection ?
                Object.entries(target.selection).every(([layer, selected]) => setup.selection?.[layer] === selected) :
                setup.style === target.style && setup.rate === target.rate;
            if (confirmed) this.clearPrimarySetupOperation();
        },

        reviewPrimarySetup() {
            if (!this.hardwareReady || this.ws?.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({ command: 'dashboard_review_me_setup' }));
        },

        transitionStyleSupported(style) {
            const topology = this.state?.topology || {};
            if (style === 3) return Number.isInteger(topology.dves) && topology.dves > 0;
            if (style === 4) return Number.isInteger(topology.stingers) && topology.stingers > 0;
            return [0, 1, 2].includes(style);
        },

        selectTransitionStyle(style) {
            if (!this.hardwareReady || this.primaryActionPending || this.stylePending ||
                this.styleUnconfirmed || this.primarySetupPendingReason ||
                !this.transitionStyleSupported(style) || !this.ws || this.ws.readyState !== WebSocket.OPEN ||
                this.hardwareMe?.transition?.style === style) return;
            this.stylePending = true;
            this.styleUnconfirmed = false;
            this.stylePendingTarget = style;
            this.stylePendingTimer = setTimeout(() => {
                if (this.stylePending) {
                    this.stylePending = false;
                    this.styleUnconfirmed = true;
                    this.stylePendingTimer = null;
                    this.showError('Transition style result is unconfirmed; review current hardware state.');
                }
            }, 3500);
            this.ws.send(JSON.stringify({ command: 'dashboard_set_transition_style', style, me: 0 }));
        },

        get physicalOutputs() {
            return this.projectedOutputs.slice().sort((a, b) => a.outputId - b.outputId);
        },

        assignmentChangeReason() {
            if (!this.connected || !this.state?.is_connected) return 'Connect to the ATEM before changing output assignments.';
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return 'Dashboard connection is not ready.';
            if (this.state?.dashboardSafety?.fresh !== true) return 'Hardware state is stale; wait for a fresh ATEM update.';
            if (this.outputMappingError) return this.outputMappingError;
            if (this.dashboardConfigError) return `Switcher configuration unavailable: ${this.dashboardConfigError}`;
            if (this.dashboardConfigSaving) return 'Switcher configuration update is still pending.';
            if (!this.dashboardConfig || this.dashboardConfigDeviceId !== this.routingProjection?.deviceId) {
                return this.routingProjection?.deviceId
                    ? 'Verified switcher configuration is still loading.'
                    : 'Verified switcher identity/configuration is unavailable.';
            }
            if (this.assignmentBusy) return 'An output assignment or route confirmation is still pending.';
            return '';
        },

        openAssignmentDialog(owner) {
            if (!['primary', 'virtual1', 'virtual2'].includes(owner) || !this.dashboardConfig ||
                this.outputMappingError || !this.hardwareReady || this.dashboardConfigSaving || this.assignmentBusy) return;
            this.assignmentOwner = owner;
            const selected = {};
            const outputs = {};
            for (const output of this.physicalOutputs) {
                selected[String(output.outputId)] = owner === 'primary'
                    ? output.owner === 'primary'
                    : output.owner !== 'primary' &&
                      (this.dashboardConfig.config.virtualSwitchers[owner].outputs || []).includes(output.auxIndex);
                outputs[output.outputId] = {
                    selected: selected[output.outputId], owner: output.owner,
                    live: output.liveSourceId, status: output.routeStatus,
                };
            }
            const group = this.routingProjection?.groups?.[owner];
            this.assignmentReview = {
                deviceId: this.dashboardConfig.deviceId,
                revision: this.dashboardConfig.revision,
                programId: this.routingProjection?.capabilities?.programOutputSourceId,
                barsId: this.routingProjection?.capabilities?.colorBarsSourceId,
                groupStatus: group?.routeStatus, groupLive: group?.liveSourceId,
                groupTarget: group?.savedProgramTargetId, outputs,
            };
            this.assignmentSelection = selected;
            this.assignmentDialogOpen = true;
        },

        virtualAssignmentTarget(group, output) {
            if (group?.routeStatus === 'uniform') return group.liveSourceId;
            if (group?.routeStatus !== 'empty') return null;
            if (Number.isInteger(group.savedProgramTargetId)) return group.savedProgramTargetId;
            const source = this.sources.find(item => item.source === output.liveSourceId);
            return output.owner === 'other' && output.routeStatus === 'observed' && source?.available_aux === true
                ? source.source : null;
        },

        stagedAssignmentDescription(output) {
            if (!this.assignmentOwner || !this.dashboardConfig || !output) return '';
            const checked = !!this.assignmentSelection[String(output.outputId)];
            const before = this.assignmentReview?.outputs[output.outputId];
            if (!before || checked === before.selected) return '';
            if (output.owner !== before.owner || output.liveSourceId !== before.live || output.routeStatus !== before.status) {
                return 'Output changed. Reopen the assignment dialog to review.';
            }
            if (this.assignmentOwner === 'primary') {
                if (checked) {
                    return `Route ${this.sourceStateLabel(output.liveSourceId)} → M/E PROGRAM`;
                }
                return Number.isInteger(this.routingProjection?.capabilities?.colorBarsSourceId)
                    ? 'Release to Color Bars' : 'Cannot release: Color Bars unavailable.';
            }
            const group = this.routingProjection?.groups?.[this.assignmentOwner];
            if (checked) {
                const target = this.virtualAssignmentTarget(group, output);
                return Number.isInteger(target)
                    ? target === output.liveSourceId ? `Assign; keep ${this.sourceStateLabel(target)}`
                        : `Route ${this.sourceStateLabel(output.liveSourceId)} → ${this.sourceStateLabel(target)}`
                    : 'Cannot assign: set a valid Program target first.';
            }
            return `Release; preserve ${this.sourceStateLabel(output.liveSourceId)}`;
        },

        closeAssignmentDialog() {
            if (this.assignmentBusy) return;
            this.assignmentDialogOpen = false;
            this.assignmentOwner = null;
            this.assignmentSelection = {};
            this.assignmentReview = null;
        },

        applyAssignmentChanges() {
            if (!this.assignmentDialogOpen || this.assignmentBusy || !this.dashboardConfig ||
                !this.hardwareReady || this.outputMappingError) return;
            const owner = this.assignmentOwner;
            const review = this.assignmentReview;
            if (!review || review.deviceId !== this.dashboardConfig.deviceId ||
                review.revision !== this.dashboardConfig.revision) {
                this.showError('Output assignments changed. Close and reopen the assignment dialog to review.');
                return;
            }
            const ops = [];
            const removals = [];
            const programId = this.routingProjection?.capabilities?.programOutputSourceId;
            const bars = this.routingProjection?.capabilities?.colorBarsSourceId;
            for (const output of this.physicalOutputs) {
                const checked = !!this.assignmentSelection[String(output.outputId)];
                const before = review.outputs[output.outputId];
                if (!before || checked === before.selected) continue;
                if (output.owner !== before.owner || output.liveSourceId !== before.live || output.routeStatus !== before.status) {
                    this.showError(`OUT ${output.outputId} changed. Close and reopen the assignment dialog to review.`);
                    return;
                }
                const channel = output.outputId - 1;
                if (owner === 'primary') {
                    if (checked) {
                        if (!Number.isInteger(programId) || programId !== review.programId) {
                            this.showError('M/E Program feed changed or is unavailable. Reopen the assignment dialog to review.'); return;
                        }
                        ops.push({ outputId: output.outputId, mode: 'primary_assign', targetOwner: 'primary', target: programId,
                            expectedLive: output.liveSourceId,
                            transferFrom: output.owner === 'virtual1' || output.owner === 'virtual2' ? output.owner : null });
                    } else {
                        if (!Number.isInteger(bars) || bars !== review.barsId) {
                            this.showError('Color Bars changed or is unavailable. Reopen the assignment dialog to review.'); return;
                        }
                        ops.push({ outputId: output.outputId, mode: 'primary_release', targetOwner: 'other',
                            target: bars, expectedLive: output.liveSourceId });
                    }
                } else {
                    if (!checked) { removals.push({ groupId: owner, channel }); continue; }
                    const group = this.routingProjection?.groups?.[owner];
                    if (group?.routeStatus !== review.groupStatus || group?.liveSourceId !== review.groupLive ||
                        group?.savedProgramTargetId !== review.groupTarget) {
                        this.showError('The virtual switcher target changed. Reopen the assignment dialog to review.'); return;
                    }
                    if (!group || ['mixed', 'unknown'].includes(group.routeStatus)) {
                        this.showError(`${owner} routing must be uniform and observed before adding an output.`); return;
                    }
                    if (group.routeStatus === 'empty' && group.savedProgramTargetId == null && ops.length) {
                        this.showError('Assign the first output by itself so the virtual switcher can keep its current feed.'); return;
                    }
                    const target = this.virtualAssignmentTarget(group, output);
                    if (!Number.isInteger(target)) { this.showError(`Set a valid ${owner} Program target before assigning an output.`); return; }
                    const transferFrom = ['primary', 'virtual1', 'virtual2'].includes(output.owner) ? output.owner : null;
                    ops.push({ outputId: output.outputId, mode: 'virtual_assign', targetOwner: owner,
                        groupId: owner, target, expectedLive: output.liveSourceId, transferFrom });
                }
            }
            if (!ops.length && !removals.length) { this.closeAssignmentDialog(); return; }
            this.assignmentBusy = true;
            this.routeBatch = { owner, revision: review.revision,
                operations: ops.map(operation => ({ ...operation, status: 'queued' })),
                removals, confirmed: [], savingConfig: false, error: '' };
            this.dispatchNextAssignmentRoute();
        },

        dispatchNextAssignmentRoute() {
            if (!this.routeBatch || this.routeBatch.savingConfig) return;
            const next = this.routeBatch.operations.find(operation => operation.status === 'queued');
            if (!next) { this.persistAssignmentBatch(); return; }
            next.status = 'pending';
            const operation = { ...next, before: next.expectedLive,
                batchIndex: this.routeBatch.operations.indexOf(next), status: 'pending', timer: null, accepted: false };
            this.routeOperations[String(next.outputId)] = operation;
            operation.timer = setTimeout(() => {
                const current = this.routeOperations[String(next.outputId)];
                if (!current || current.status !== 'pending') return;
                current.status = 'unconfirmed';
                next.status = 'unconfirmed';
                this.showError(`OUT ${next.outputId} route timed out; hardware result is unconfirmed. Review it before continuing.`);
            }, 4000);
            this.ws.send(JSON.stringify({ command: 'dashboard_output_route', config_revision: this.routeBatch.revision,
                output_id: next.outputId, mode: next.mode, group_id: next.groupId || null,
                transfer_from: next.transferFrom || null, expected_live: next.expectedLive,
                input_source: next.target }));
        },

        acceptOutputRoute(data) {
            const operation = this.routeOperations[String(data.output_id)];
            if (!operation) return;
            operation.accepted = true;
            if (data.no_op) this.confirmRouteOperation(data.output_id);
        },

        reviewOutputOperation(outputId) {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !Number.isInteger(outputId) || outputId < 1 || outputId > 6) return;
            this.ws.send(JSON.stringify({ command: 'dashboard_review_aux', aux_channel: outputId - 1 }));
        },

        reviewUnconfirmedAssignmentRoutes() {
            if (!this.routeBatch) return;
            const ids = Object.entries(this.routeOperations)
                .filter(([, operation]) => operation.status === 'unconfirmed')
                .map(([id]) => Number(id));
            ids.forEach(id => this.reviewOutputOperation(id));
        },

        confirmRouteOperation(outputId) {
            const key = String(outputId);
            const operation = this.routeOperations[key];
            if (!operation) return;
            if (operation.timer !== null) clearTimeout(operation.timer);
            operation.status = 'confirmed';
            delete this.routeOperations[key];
            if (Number.isInteger(operation.batchIndex) && this.routeBatch) {
                this.routeBatch.operations[operation.batchIndex].status = 'confirmed';
                this.routeBatch.confirmed.push(operation);
                this.dispatchNextAssignmentRoute();
            } else this.showNotice(`OUT ${outputId} route confirmed.`);
        },

        failRouteOperation(outputId, message) {
            const operation = this.routeOperations[String(outputId)];
            if (!operation) return;
            if (operation.timer !== null) clearTimeout(operation.timer);
            operation.status = 'failed';
            delete this.routeOperations[String(outputId)];
            if (Number.isInteger(operation.batchIndex) && this.routeBatch) {
                this.routeBatch.operations[operation.batchIndex].status = 'failed';
                this.routeBatch.error = message;
                this.dispatchNextAssignmentRoute();
            }
            this.showError(message);
        },

        persistAssignmentBatch() {
            if (!this.routeBatch || this.routeBatch.savingConfig) return;
            const batch = this.routeBatch;
            const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
            let changed = false;
            for (const groupId of ['virtual1', 'virtual2']) {
                const outputs = config.virtualSwitchers[groupId].outputs;
                const remove = new Set(batch.removals.filter(item => item.groupId === groupId).map(item => item.channel));
                for (const operation of batch.confirmed) {
                    const channel = operation.outputId - 1;
                    if (operation.targetOwner !== 'primary' &&
                        (operation.transferFrom === groupId || operation.targetOwner === groupId)) remove.add(channel);
                }
                const nextOutputs = outputs.filter(channel => !remove.has(channel));
                if (nextOutputs.length !== outputs.length) changed = true;
                config.virtualSwitchers[groupId].outputs = nextOutputs;
            }
            for (const operation of batch.confirmed) {
                if (operation.targetOwner === 'virtual1' || operation.targetOwner === 'virtual2') {
                    const group = config.virtualSwitchers[operation.targetOwner];
                    const channel = operation.outputId - 1;
                    if (!group.outputs.includes(channel)) group.outputs.push(channel);
                    group.programTarget = operation.target;
                    changed = true;
                }
            }
            if (!changed) {
                this.routeBatch = null; this.assignmentBusy = false; this.assignmentDialogOpen = false;
                if (batch.error) this.showError(batch.error); else this.showNotice('Output routing changes confirmed.');
                return;
            }
            if (batch.revision !== this.dashboardConfig.revision) {
                this.routeBatch = null;
                this.assignmentBusy = false;
                this.showError('The routes changed, but settings were revised during assignment. Reopen the dialog to review.');
                return;
            }
            batch.savingConfig = true;
            if (!this.sendDashboardConfig(config, 'assignment')) {
                batch.savingConfig = false; this.assignmentBusy = false;
                this.showError('Output routes changed, but ownership could not be saved. Reload and resolve the conflict.');
            }
        },

        routeOtherOutput(output, sourceId) {
            if (!this.hardwareReady || this.outputMappingError || !this.dashboardConfig || this.assignmentBusy ||
                !Number.isInteger(output?.liveSourceId) || !Number.isInteger(sourceId) ||
                this.routeOperations[String(output.outputId)]) return;
            const operation = { outputId: output.outputId, mode: 'other_route', targetOwner: 'other', target: sourceId,
                before: output.liveSourceId, status: 'pending', batchIndex: null, accepted: false, timer: null };
            operation.timer = setTimeout(() => {
                const current = this.routeOperations[String(output.outputId)];
                if (current && current.status === 'pending') {
                    current.status = 'unconfirmed';
                    this.showError(`OUT ${output.outputId} route timed out; hardware result is unconfirmed.`);
                }
            }, 4000);
            this.routeOperations[String(output.outputId)] = operation;
            this.ws.send(JSON.stringify({ command: 'dashboard_output_route', config_revision: this.dashboardConfig.revision,
                output_id: output.outputId, mode: 'other_route', expected_live: output.liveSourceId, input_source: sourceId }));
        },

        groupCutReason(groupId) {
            const group = this.routingProjection?.groups?.[groupId];
            return this.groupRouteReason(groupId, group?.previewSourceId);
        },

        virtualProgramReason(groupId, sourceId) {
            const group = this.routingProjection?.groups?.[groupId];
            const source = this.sources.find(item => item.source === sourceId);
            if (!source || source.available_aux !== true) return 'Source is not available to AUX outputs.';
            if (sourceId === this.routingProjection?.capabilities?.programOutputSourceId) return 'A virtual switcher cannot route Primary M/E Program.';
            if (!group) return 'Virtual switcher state is unavailable.';
            if (group.routeStatus === 'empty') {
                return !this.hardwareReady || !this.dashboardConfig || this.dashboardConfigSaving ||
                    this.assignmentBusy ? 'Switcher or saved configuration is unavailable.' : '';
            }
            if (!this.virtualDirect[groupId]) return 'Enable Direct to select a live source.';
            return this.groupRouteReason(groupId, sourceId, true);
        },

        groupRouteReason(groupId, target, direct = false) {
            if (!this.hardwareReady || !this.dashboardConfig) return 'Switcher or saved configuration is unavailable.';
            if (this.dashboardConfigDeviceId !== this.routingProjection?.deviceId) return 'Verified switcher settings are unavailable.';
            if (this.outputMappingError) return this.outputMappingError;
            if (this.takeAllOperation && ['preflight', 'pending', 'unconfirmed', 'saving'].includes(this.takeAllOperation.status)) {
                return this.takeAllOperation.status === 'saving'
                    ? 'TAKE ALL is saving confirmed switcher state.'
                    : 'TAKE ALL is awaiting hardware confirmation.';
            }
            if (this.takeAllOperation?.status === 'confirmed_config_failed') {
                return 'TAKE ALL saved switcher state failed; reload and review before another CUT.';
            }
            if (this.dashboardConfigSaving || this.assignmentBusy) return 'A settings update or output ownership change is pending.';
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return 'Dashboard connection is not ready.';
            const pending = this.groupCutOperations[groupId];
            if (pending && ['pending', 'unconfirmed', 'partial', 'saving'].includes(pending.status)) return 'Previous virtual switch is pending or incomplete; review actual routes.';
            const alignment = this.groupAlignOperations[groupId];
            if (alignment && ['pending', 'unconfirmed', 'partial', 'saving'].includes(alignment.status)) return 'Mixed-route alignment is pending or incomplete; review actual routes.';
            const group = this.routingProjection?.groups?.[groupId];
            if (!group || !Array.isArray(group.outputIds) || !group.outputIds.length) return 'Assign at least one output before CUT.';
            if (!['uniform', 'mixed'].includes(group.routeStatus) ||
                group.outputIds.some(id => !group.outputs?.some(output =>
                    output.outputId === id && output.routeStatus === 'observed' && Number.isInteger(output.liveSourceId)))) {
                return 'All assigned output routes must be current and observed.';
            }
            const savedOutputs = this.dashboardConfig.config.virtualSwitchers[groupId].outputs;
            if (savedOutputs.length !== group.outputIds.length ||
                savedOutputs.some(channel => !group.outputIds.includes(channel + 1))) {
                return 'Output assignments changed; wait for the latest verified settings.';
            }
            if (!direct && (group.previewSourceValid !== true || !Number.isInteger(target))) return 'Select a valid directly routable Preview source.';
            if (target === this.routingProjection.capabilities?.programOutputSourceId) return 'A virtual switcher cannot route Primary M/E Program.';
            if (target === group.liveSourceId) return 'The selected source is already live.';
            const assigned = new Set(group.outputIds);
            if ((this.routingProjection?.conflicts || []).some(item =>
                assigned.has(item.outputId) || assigned.has((item.auxIndex ?? -1) + 1))) return 'Output ownership or routing conflict must be resolved first.';
            return '';
        },

        groupRouteSnapshot(group) {
            return group.outputs.map(output => ({ channel: output.outputId - 1, source: output.liveSourceId }));
        },

        get takeAllBlockers() {
            return this.state?.dashboardSafety?.takeAllBlockers || [];
        },

        reviewTakeAllBlocker(blocker) {
            if (!this.hardwareReady || !blocker?.reviewable) return;
            if (blocker.kind === 'me_preview') this.reviewPrimaryPreview();
            if (blocker.kind === 'usk') this.reviewKeyer(blocker.index);
            if (blocker.kind === 'dsk') this.reviewDSK(blocker.index);
        },

        takeAllReason() {
            if (!this.hardwareReady || !this.dashboardConfig) return 'ATEM connection or saved configuration is unavailable.';
            if (this.primarySetupPendingReason) return this.primarySetupPendingReason;
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return 'Dashboard connection is not ready.';
            if (this.outputMappingError) return this.outputMappingError;
            if (this.dashboardConfigDeviceId !== this.routingProjection?.deviceId) return 'Verified switcher identity/configuration is unavailable.';
            if (this.takeAllOperation && ['preflight', 'pending', 'unconfirmed', 'saving'].includes(this.takeAllOperation.status)) {
                if (this.takeAllOperation.status === 'preflight') return 'A previous TAKE ALL is awaiting server preflight.';
                if (this.takeAllOperation.status === 'saving') return 'A previous TAKE ALL is saving confirmed switcher state.';
                if (this.takeAllOperation.status === 'unconfirmed') return 'A previous TAKE ALL has unconfirmed results; review each affected output.';
                return 'A previous TAKE ALL is awaiting hardware confirmation.';
            }
            if (this.takeAllOperation?.status === 'confirmed_config_failed') {
                return 'TAKE ALL changed hardware routes, but saved switcher state failed; reload and review before another TAKE.';
            }
            if (this.dashboardConfigSaving || this.assignmentBusy) return 'A configuration or output operation is already in progress.';
            const conflicts = this.routingProjection?.conflicts || [];
            const blockingConflicts = conflicts.filter(conflict =>
                !(conflict.type === 'invalid_saved_source' &&
                    ['virtual1', 'virtual2'].includes(conflict.group) &&
                    this.routingProjection?.groups?.[conflict.group]?.outputIds?.length === 0));
            if (blockingConflicts.length) return 'Output ownership or routing conflicts must be resolved before TAKE ALL.';
            if (this.takeAllBlockers.length) return this.takeAllBlockers[0].message;
            if (this.previewPending || this.previewUnconfirmed || this.stylePending || this.styleUnconfirmed) {
                return 'A Primary Preview or transition-style change is pending or unconfirmed.';
            }
            const primaryReason = this.primaryCutReason();
            const primarySkipped = primaryReason === 'M/E Preview is already live; select a different Preview source.' ||
                primaryReason === 'M/E Preview is already live.';
            if (primaryReason && !primarySkipped) return primaryReason;
            let ready = !primarySkipped;
            for (const groupId of ['virtual1', 'virtual2']) {
                const group = this.routingProjection?.groups?.[groupId];
                if (!group || !Array.isArray(group.outputIds)) return `${this.switcherName(groupId, groupId)} routing state is unavailable.`;
                if (group.outputIds.length === 0) continue;
                const operation = this.groupCutOperations[groupId];
                if (operation && ['pending', 'partial', 'unconfirmed', 'saving'].includes(operation.status)) {
                    return `${this.switcherName(groupId, groupId)} has a pending or unresolved route operation.`;
                }
                const reason = this.groupCutReason(groupId);
                if (reason === 'The selected source is already live.') continue;
                if (reason) return `${this.switcherName(groupId, groupId)}: ${reason}`;
                ready = true;
            }
            return ready ? '' : 'Preview is already live on every switcher; select a different Preview source.';
        },

        takeAll() {
            const reason = this.takeAllReason();
            if (reason) { this.showError(reason); return; }
            const transition = this.primaryTransitionRequest();
            if (!transition) { this.showError('M/E next-transition selection is unavailable.'); return; }
            const id = ++this.takeAllSequence;
            const groups = {};
            for (const groupId of ['virtual1', 'virtual2']) {
                const group = this.routingProjection.groups[groupId];
                groups[groupId] = { routes: this.groupRouteSnapshot(group), preview: group.previewSourceId };
            }
            const primarySkipped = !transition.result.keyTargets && transition.result.target === transition.result.before;
            const primary = { status: primarySkipped ? 'skipped' : 'pending',
                before: transition.result.before, target: transition.result.target, error: '' };
            this.takeAllOperation = { id, status: 'preflight', primary,
                virtual1: { status: groups.virtual1 ? 'pending' : 'failed', outputIds: this.routingProjection.groups.virtual1.outputIds.slice(), channels: [] },
                virtual2: { status: groups.virtual2 ? 'pending' : 'failed', outputIds: this.routingProjection.groups.virtual2.outputIds.slice(), channels: [] },
                started: false, configSaved: false, error: '' };
            this.assignmentBusy = true;
            if (!primarySkipped) {
                this.primaryActionPending = { kind: 'take_all', takeAllId: id,
                    ...transition.result };
                this.armPrimaryOperationTimeout();
            }
            for (const groupId of ['virtual1', 'virtual2']) {
                const participant = this.takeAllOperation[groupId];
                const group = this.routingProjection.groups[groupId];
                if (!participant.outputIds.length || group.previewSourceId === group.liveSourceId) {
                    participant.status = 'skipped';
                    continue;
                }
                const operation = this.groupCutOperations[groupId] = {
                        status: 'pending', target: group.previewSourceId, previous: group.liveSourceId,
                        showMismatchWhilePending: groups[groupId].routes.some(route => route.source !== group.savedProgramTargetId),
                    takeAllId: id,
                    channels: groups[groupId].routes.map(({ channel, source }) =>
                        ({ channel, before: source, status: 'dispatching', error: '' })),
                    configSaved: false, timer: null,
                };
                operation.timer = setTimeout(() => {
                    if (!['pending', 'partial'].includes(operation.status)) return;
                    for (const item of operation.channels) {
                        if (['pending', 'dispatching'].includes(item.status)) item.status = 'unconfirmed';
                    }
                    operation.status = operation.channels.some(item => item.status === 'failed') ? 'partial' : 'unconfirmed';
                    operation.timer = null;
                    participant.status = 'unconfirmed';
                    this.takeAllOperation.status = 'unconfirmed';
                    this.showError(`${this.switcherName(groupId, groupId)} TAKE ALL result is unconfirmed; review each output route.`);
                }, 5000);
            }
            this.takeAllOperation.timer = setTimeout(() => {
                if (this.takeAllOperation?.id === id && !this.takeAllOperation.started) {
                    this.takeAllOperation.status = 'unconfirmed';
                    this.takeAllOperation.error = 'TAKE ALL response timed out; all participants require hardware review.';
                    for (const participantId of ['virtual1', 'virtual2']) {
                        if (this.takeAllOperation[participantId].status === 'pending') {
                            this.takeAllOperation[participantId].status = 'unconfirmed';
                            for (const channel of this.groupCutOperations[participantId]?.channels || []) {
                                if (['pending', 'dispatching'].includes(channel.status)) channel.status = 'unconfirmed';
                            }
                        }
                    }
                    if (this.primaryActionPending?.takeAllId === id) {
                        this.primaryActionPending.unconfirmed = true;
                        this.takeAllOperation.primary.status = 'unconfirmed';
                        this.takeAllOperation.primary.error = 'Primary result is unconfirmed; review current M/E state.';
                    }
                    this.showError(this.takeAllOperation.error);
                }
            }, 5500);
            this.ws.send(JSON.stringify({ command: 'dashboard_take_all', device_id: this.dashboardConfigDeviceId,
                config_revision: this.dashboardConfig.revision, primary_action: 'cut', ...transition.request,
                groups }));
        },

        rejectTakeAll(message) {
            const operation = this.takeAllOperation;
            if (!operation || operation.started) return;
            if (operation.timer !== null) clearTimeout(operation.timer);
            if (this.primaryActionPending?.takeAllId === operation.id) this.primaryActionPending = null;
            if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
            this.primaryActionTimer = null;
            for (const groupId of ['virtual1', 'virtual2']) {
                const groupOperation = this.groupCutOperations[groupId];
                if (groupOperation?.takeAllId === operation.id) {
                    if (groupOperation.timer !== null) clearTimeout(groupOperation.timer);
                    delete this.groupCutOperations[groupId];
                }
            }
            operation.status = 'blocked';
            operation.error = message;
            this.assignmentBusy = false;
        },

        acceptTakeAll(data) {
            const operation = this.takeAllOperation;
            if (!operation || operation.started || data.device_id !== this.dashboardConfigDeviceId) return;
            if (operation.timer !== null) clearTimeout(operation.timer);
            operation.timer = null;
            operation.started = true;
            const primary = data.primary || {};
            if (primary.status !== 'skipped') {
                operation.primary.before = primary.before;
                operation.primary.target = primary.target;
            }
            operation.primary.status = primary.status === 'skipped' ? 'skipped' : (primary.ok ? 'pending' : 'failed');
            operation.primary.error = primary.error || '';
            if (!primary.ok && this.primaryActionPending?.takeAllId === operation.id) {
                this.primaryActionPending = null;
                if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
                this.primaryActionTimer = null;
            }
            for (const groupId of ['virtual1', 'virtual2']) {
                const participant = operation[groupId];
                const result = data.virtual?.[groupId] || {};
                if (result.status === 'skipped') {
                    participant.status = 'skipped';
                    const groupOperation = this.groupCutOperations[groupId];
                    if (groupOperation?.takeAllId === operation.id) {
                        if (groupOperation.timer !== null) clearTimeout(groupOperation.timer);
                        delete this.groupCutOperations[groupId];
                    }
                    continue;
                }
                if (result.status === 'failed') {
                    participant.status = 'failed'; participant.error = result.error || 'Not dispatched.';
                    const groupOperation = this.groupCutOperations[groupId];
                    if (groupOperation?.takeAllId === operation.id) {
                        if (groupOperation.timer !== null) clearTimeout(groupOperation.timer);
                        groupOperation.status = 'blocked'; groupOperation.error = participant.error;
                    }
                    continue;
                }
                const groupOperation = this.groupCutOperations[groupId];
                if (!groupOperation || groupOperation.takeAllId !== operation.id) continue;
                groupOperation.status = result.status === 'partial' ? 'partial' : 'pending';
                participant.status = result.status === 'partial' ? 'partial' : 'pending';
                participant.target = result.target;
                participant.previous = result.previous;
                participant.channels = groupOperation.channels;
                this.recordGroupCutAcceptance(groupOperation, result);
            }
            this.reconcileThreeC();
            this.tryFinalizeTakeAll();
        },

        tryFinalizeTakeAll() {
            const operation = this.takeAllOperation;
            if (!operation?.started || ['complete', 'failed', 'saving', 'confirmed_config_failed'].includes(operation.status)) return;
            for (const groupId of ['virtual1', 'virtual2']) {
                const groupOperation = this.groupCutOperations[groupId];
                if (groupOperation?.takeAllId === operation.id &&
                    ['pending', 'partial', 'unconfirmed'].includes(groupOperation.status) &&
                    groupOperation.channels?.some(item =>
                    ['pending', 'dispatching', 'unconfirmed'].includes(item.status))) {
                    operation[groupId].status = groupOperation.channels.some(item => item.status === 'unconfirmed') ? 'unconfirmed' : 'pending';
                }
            }
            const participants = [operation.primary, operation.virtual1, operation.virtual2];
            if (participants.some(item => ['preflight', 'pending', 'unconfirmed'].includes(item.status))) {
                operation.status = participants.some(item => item.status === 'unconfirmed') ? 'unconfirmed' : 'pending';
                return;
            }
            const confirmedGroups = ['virtual1', 'virtual2'].filter(groupId =>
                operation[groupId].status === 'confirmed' && !operation[groupId].configSaved);
            if (confirmedGroups.length) {
                const groupId = confirmedGroups[0];
                const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
                const participant = operation[groupId];
                this.applyConfirmedGroupTake(config.virtualSwitchers[groupId], participant.target, participant.previous);
                operation.status = 'saving';
                operation.configSaveGroup = groupId;
                this.configSavePurpose = `take-all:${operation.id}:${groupId}`;
                if (!this.sendDashboardConfig(config, this.configSavePurpose)) {
                    this.failTakeAllConfig('Hardware changes were confirmed, but the saved virtual switcher state could not be updated.');
                    this.configSavePurpose = null;
                    this.showError(operation.error);
                }
                return;
            }
            this.finishTakeAll();
        },

        finishTakeAllConfig() {
            this.configSavePurpose = null;
            if (this.takeAllOperation) {
                const groupId = this.takeAllOperation.configSaveGroup;
                if (groupId) {
                    this.takeAllOperation[groupId].configSaved = true;
                    const groupOperation = this.groupCutOperations[groupId];
                    if (groupOperation?.takeAllId === this.takeAllOperation.id) groupOperation.configSaved = true;
                }
                this.takeAllOperation.configSaveGroup = null;
                this.takeAllOperation.status = 'pending';
            }
            this.configSaveExpected = null;
            this.tryFinalizeTakeAll();
        },

        failTakeAllConfig(message) {
            const operation = this.takeAllOperation;
            if (!operation) return;
            operation.status = 'confirmed_config_failed';
            operation.error = message;
            const groupId = operation.configSaveGroup;
            if (groupId) {
                operation[groupId].error = message;
                const groupOperation = this.groupCutOperations[groupId];
                if (groupOperation?.takeAllId === operation.id) {
                    groupOperation.status = 'confirmed_config_failed';
                    groupOperation.error = message;
                }
            }
            this.assignmentBusy = false;
        },

        finishTakeAll() {
            const operation = this.takeAllOperation;
            if (!operation) return;
            const successful = [operation.primary, operation.virtual1, operation.virtual2]
                .every(item => ['confirmed', 'skipped'].includes(item.status));
            operation.status = successful ? 'complete' : 'partial';
            if (operation.timer !== null) clearTimeout(operation.timer);
            operation.timer = null;
            this.assignmentBusy = false;
            if (successful) this.showNotice('TAKE ALL confirmed for every participating switcher.');
            else this.showError('TAKE ALL finished with partial results. Review each switcher and output status before another action.');
        },

        cutVirtualGroup(groupId) {
            const reason = this.groupCutReason(groupId);
            if (reason) { this.showError(reason); return; }
            this.startVirtualRoute(groupId, this.routingProjection.groups[groupId].previewSourceId, 'cut');
        },

        selectVirtualProgram(groupId, sourceId) {
            const reason = this.virtualProgramReason(groupId, sourceId);
            if (reason) { this.showError(reason); return; }
            if (this.routingProjection.groups[groupId].routeStatus === 'empty') {
                this.setEmptyVirtualProgramTarget(groupId, sourceId);
                return;
            }
            this.startVirtualRoute(groupId, sourceId, 'direct');
        },

        startVirtualRoute(groupId, target, mode) {
            const group = this.routingProjection.groups[groupId];
            const routes = this.groupRouteSnapshot(group);
            const operation = this.groupCutOperations[groupId] = {
                status: 'pending', target, mode, previous: group.liveSourceId,
                showMismatchWhilePending: routes.some(route => route.source !== group.savedProgramTargetId),
                channels: routes.map(({ channel, source }) =>
                    ({ channel, before: source, status: 'dispatching', error: '' })),
                configSaved: false, timer: null,
            };
            operation.timer = setTimeout(() => {
                if (['pending', 'partial'].includes(operation.status)) {
                    for (const item of operation.channels) {
                        if (['pending', 'dispatching'].includes(item.status)) item.status = 'unconfirmed';
                    }
                    operation.status = operation.channels.some(item => item.status === 'failed') ? 'partial' : 'unconfirmed';
                    operation.timer = null;
                    this.showError(`${this.switcherName(groupId, groupId)} route timed out; review each output route.`);
                }
            }, 5000);
            this.ws.send(JSON.stringify({ command: 'dashboard_cut_virtual_group', group_id: groupId,
                device_id: this.dashboardConfigDeviceId, config_revision: this.dashboardConfig.revision, input_source: target, mode,
                expected_routes: routes }));
        },

        acceptGroupCut(data) {
            const operation = this.groupCutOperations[data.group_id];
            if (!operation) return;
            if (operation.mode === 'direct' && (data.mode !== 'direct' || data.target !== operation.target)) return;
            this.recordGroupCutAcceptance(operation, data);
            this.reconcileThreeC();
        },

        recordGroupCutAcceptance(operation, data) {
            operation.accepted = true;
            operation.target = data.target; operation.previous = data.previous;
            for (const outcome of data.outcomes || []) {
                const item = operation.channels.find(channel => channel.channel === outcome.channel);
                if (!item) continue;
                if (Number.isInteger(outcome.before)) item.before = outcome.before;
                item.status = outcome.ok ? 'pending' : 'failed'; item.error = outcome.error || '';
            }
        },

        finishGroupCutConfig() {
            const groupId = this.configSavePurpose.split(':')[1];
            this.configSavePurpose = null;
            const operation = this.groupCutOperations[groupId];
            if (!operation) return;
            operation.configSaved = true; operation.status = 'complete';
            if (operation.timer !== null) clearTimeout(operation.timer);
            operation.timer = null;
            const action = operation.mode === 'direct' ? 'Direct Program' : 'CUT';
            this.showNotice(`${this.switcherName(groupId, groupId)} ${action} confirmed on all outputs.`);
        },

        applyConfirmedGroupTake(group, target, previous) {
            group.programTarget = target;
            const prior = this.sources.find(source => source.source === previous);
            group.previewSource = prior?.available_aux === true ? previous : null;
        },

        groupAlignReason(groupId) {
            if (!this.hardwareReady || !this.dashboardConfig) return 'Switcher or saved configuration is unavailable.';
            if (this.outputMappingError || this.assignmentBusy) return this.outputMappingError || 'An output ownership change is pending.';
            const operation = this.groupAlignOperations[groupId];
            if (operation?.status === 'pending' || operation?.status === 'unconfirmed' ||
                operation?.channels?.some(item => item.status === 'unconfirmed')) {
                return 'A prior alignment has uncertain output routes; review hardware state before another alignment.';
            }
            const cut = this.groupCutOperations[groupId];
            if (cut && ['pending', 'unconfirmed'].includes(cut.status)) return 'A virtual switcher CUT is still pending.';
            const group = this.routingProjection?.groups?.[groupId];
            if (!group || group.routeStatus !== 'mixed' || !Array.isArray(group.outputs) || !group.outputs.length) {
                return 'Alignment is available only for a mixed group with assigned outputs.';
            }
            if (group.outputs.some(output => output.routeStatus !== 'observed' || output.owner !== groupId)) {
                return 'Every assigned route must be observed and ownership conflict-free.';
            }
            if (group.outputs.some(output => this.routeOperations[String(output.outputId)])) return 'An output route command is pending.';
            return '';
        },

        beginVirtualGroupAlign(groupId) {
            const reason = this.groupAlignReason(groupId);
            if (reason) { this.showError(reason); return; }
            const group = this.routingProjection.groups[groupId];
            const savedTarget = group.savedProgramTargetId;
            const firstLive = group.outputs.find(output => Number.isInteger(output.liveSourceId))?.liveSourceId;
            const source = this.sources.find(item => item.source === savedTarget && item.available_aux === true);
            this.groupAlignDraft = { groupId,
                target: source ? savedTarget : firstLive,
                expectedRoutes: group.outputs.map(output => ({ channel: output.auxIndex, source: output.liveSourceId })) };
        },

        cancelVirtualGroupAlign() {
            this.groupAlignDraft = null;
        },

        confirmVirtualGroupAlign() {
            const draft = this.groupAlignDraft;
            if (!draft || this.groupAlignReason(draft.groupId)) return;
            const source = this.sources.find(item => item.source === draft.target && item.available_aux === true);
            if (!source || draft.target === this.routingProjection?.capabilities?.programOutputSourceId) {
                this.showError('Choose a directly routable source other than the Primary M/E Program feed.');
                return;
            }
            const operation = this.groupAlignOperations[draft.groupId] = {
                status: 'pending', target: draft.target,
                channels: draft.expectedRoutes.map(item => ({ channel: item.channel, before: item.source, status: 'dispatching', error: '' })),
                timer: null,
            };
            operation.timer = setTimeout(() => {
                if (operation.status === 'pending') {
                    operation.status = 'unconfirmed';
                    for (const item of operation.channels) if (item.status === 'pending' || item.status === 'dispatching') item.status = 'unconfirmed';
                    this.showError(`${this.switcherName(draft.groupId, draft.groupId)} alignment timed out; inspect each output before retrying.`);
                }
            }, 5000);
            this.ws.send(JSON.stringify({ command: 'dashboard_align_virtual_group', group_id: draft.groupId,
                config_revision: this.dashboardConfig.revision, input_source: draft.target,
                expected_routes: draft.expectedRoutes }));
            this.groupAlignDraft = null;
        },

        acceptGroupAlign(data) {
            const operation = this.groupAlignOperations[data.group_id];
            if (!operation) return;
            for (const outcome of data.outcomes || []) {
                const item = operation.channels.find(channel => channel.channel === outcome.channel);
                if (!item) continue;
                item.status = outcome.ok ? (outcome.no_op ? 'confirmed' : 'pending') : 'failed';
                item.error = outcome.error || '';
            }
            this.reconcileThreeC();
        },

        finishGroupAlignConfig() {
            const groupId = this.configSavePurpose.split(':')[1];
            const operation = this.groupAlignOperations[groupId];
            if (operation) {
                operation.status = 'complete';
                if (operation.timer !== null) clearTimeout(operation.timer);
                operation.timer = null;
                this.showNotice(`${this.switcherName(groupId, groupId)} outputs aligned and confirmed.`);
            }
            this.configSavePurpose = null;
        },

        reconcileThreeC() {
            if (this.previewPending && this.hardwarePreviewSourceId === this.previewPendingTarget) {
                this.previewPending = false; this.previewPendingTarget = null;
                this.previewUnconfirmed = false;
                if (this.previewPendingTimer !== null) clearTimeout(this.previewPendingTimer);
                this.previewPendingTimer = null;
            }
            if (this.stylePending && this.hardwareMe?.transition?.style === this.stylePendingTarget) {
                this.stylePending = false; this.stylePendingTarget = null;
                this.styleUnconfirmed = false;
                if (this.stylePendingTimer !== null) clearTimeout(this.stylePendingTimer);
                this.stylePendingTimer = null;
            }
            const takeAllPrimary = this.takeAllOperation?.primary;
            if (this.takeAllOperation?.started && takeAllPrimary?.status === 'unconfirmed' &&
                takeAllPrimary.reviewRequested && !this.primaryActionPending?.keyTargets) {
                if (this.hardwareProgramSourceId === takeAllPrimary.target) {
                    takeAllPrimary.status = 'confirmed';
                    takeAllPrimary.error = '';
                } else if (this.hardwareProgramSourceId === takeAllPrimary.before) {
                    takeAllPrimary.status = 'failed';
                    takeAllPrimary.error = 'Primary remains on its previous source after review; no change was confirmed.';
                } else if (this.hardwareProgramSourceId !== null) {
                    takeAllPrimary.error = 'Primary is on an unexpected source; result remains unconfirmed.';
                }
                takeAllPrimary.reviewRequested = false;
                if (takeAllPrimary.status !== 'unconfirmed') this.tryFinalizeTakeAll();
            }
            if (this.primaryActionPending && (!this.primaryActionPending.takeAllId || this.takeAllOperation?.started)) {
                const op = this.primaryActionPending;
                if (op.keyTargets) {
                    const outcome = this.primaryKeyedTransitionOutcome(op);
                    if (outcome === 'confirmed') {
                        this.showNotice('Primary keyed transition confirmed by observed Program and keyer state.');
                        this.finishPrimaryAction(op, 'confirmed');
                    } else if (op.reviewRequested) {
                        op.reviewRequested = false;
                        if (outcome === 'unchanged') {
                            const error = 'Program and selected keys are unchanged after review. No transition was confirmed.';
                            this.showError(error);
                            this.finishPrimaryAction(op, 'failed', error);
                        } else {
                            op.unconfirmed = true;
                            this.showError('Keyed transition remains unconfirmed. Review current Program and keyer state.');
                        }
                    }
                } else if (this.hardwareProgramSourceId === op.target && op.target !== op.before) {
                    this.finishPrimaryAction(op, 'confirmed');
                } else if (this.hardwareProgramSourceId !== null && this.hardwareProgramSourceId !== op.before && this.hardwareProgramSourceId !== op.target) {
                    op.unconfirmed = true;
                    if (op.takeAllId && this.takeAllOperation?.id === op.takeAllId) {
                        this.takeAllOperation.primary.status = 'unconfirmed';
                        this.takeAllOperation.primary.error = 'Primary changed to an unexpected source; inspect the M/E before proceeding.';
                    }
                }
            }
            for (const [id, operation] of Object.entries(this.routeOperations)) {
                if (!['pending', 'unconfirmed'].includes(operation.status)) continue;
                const output = this.projectedOutputs.find(item => item.outputId === Number(id));
                if (output?.routeStatus === 'observed' && output.liveSourceId === operation.target) {
                    this.confirmRouteOperation(Number(id));
                } else if (operation.reviewRequested && output?.routeStatus === 'observed' && output.liveSourceId === operation.before) {
                    if (operation.timer !== null) clearTimeout(operation.timer);
                    operation.status = 'failed';
                    delete this.routeOperations[id];
                    if (Number.isInteger(operation.batchIndex) && this.routeBatch) {
                        this.routeBatch.operations[operation.batchIndex].status = 'failed';
                        this.routeBatch.error = `OUT ${id} remains on its previous route after review.`;
                        this.dispatchNextAssignmentRoute();
                    } else this.showError(`OUT ${id} remains on its previous route after review; no change was confirmed.`);
                } else if (output?.routeStatus === 'observed' && output.liveSourceId !== operation.before) {
                    operation.status = 'unconfirmed';
                    if (operation.timer !== null) clearTimeout(operation.timer);
                    this.showError(`OUT ${id} changed to an unexpected source; operation is unconfirmed.`);
                }
            }
            for (const [groupId, operation] of Object.entries(this.groupCutOperations)) {
                if (!['pending', 'unconfirmed', 'partial'].includes(operation.status) || !Array.isArray(operation.channels)) continue;
                for (const item of operation.channels) {
                    if (!['pending', 'unconfirmed', 'dispatching', 'confirmed'].includes(item.status) &&
                        !(operation.takeAllId && item.status === 'failed' && item.reviewRequested)) continue;
                    if (operation.mode === 'direct' && !operation.accepted && !item.reviewRequested) continue;
                    const output = this.projectedOutputs.find(route => route.auxIndex === item.channel);
                    const observed = output?.routeStatus === 'observed';
                    if (observed && output.owner === groupId && output.liveSourceId === operation.target) item.status = 'confirmed';
                    else if (item.reviewRequested && observed) {
                        item.status = 'failed'; item.reviewed = true;
                        item.error = output.owner !== groupId ? `OUT ${output.outputId} left the virtual switcher.`
                            : `OUT ${output.outputId} is set to ${this.sourceStateLabel(output.liveSourceId)} after review.`;
                    }
                    else if (item.status === 'confirmed' || (observed &&
                        (output.liveSourceId !== item.before || output.owner !== groupId))) {
                        item.status = 'unconfirmed'; item.error = `OUT ${item.channel + 1} no longer matches the expected route or ownership.`;
                    }
                }
                if (operation.status !== 'pending' && operation.channels.some(item => item.status === 'failed') &&
                    operation.channels.every(item => ['confirmed', 'failed'].includes(item.status)) &&
                    (!operation.takeAllId || operation.channels.every(item => item.status === 'confirmed' || item.reviewed))) {
                    // A uniform route alone does not prove a timed-out write
                    // settled: require per-output confirmation or read-only
                    // review before unlocking a later group operation.
                    operation.status = 'resolved';
                    operation.error = '';
                    if (operation.timer !== null) clearTimeout(operation.timer);
                    operation.timer = null;
                    if (operation.takeAllId && this.takeAllOperation?.id === operation.takeAllId) {
                        this.takeAllOperation[groupId].status = operation.channels.some(item => item.status === 'failed') ? 'partial' : 'confirmed';
                        this.takeAllOperation[groupId].error = operation.channels.filter(item => item.status === 'failed').map(item => item.error).filter(Boolean).join(' ');
                        this.tryFinalizeTakeAll();
                    }
                    continue;
                }
                if (operation.takeAllId && this.takeAllOperation?.id === operation.takeAllId) {
                    const participant = this.takeAllOperation[groupId];
                    const unresolved = operation.channels.some(item => ['pending', 'dispatching', 'unconfirmed'].includes(item.status));
                    const failed = operation.channels.some(item => item.status === 'failed');
                    const allConfirmed = operation.channels.length > 0 && operation.channels.every(item => item.status === 'confirmed');
                    if (allConfirmed) {
                        operation.status = 'confirmed';
                        participant.status = 'confirmed';
                        participant.error = '';
                        if (operation.timer !== null) clearTimeout(operation.timer);
                        operation.timer = null;
                        this.tryFinalizeTakeAll();
                        continue;
                    }
                    if (failed) {
                        participant.status = 'partial';
                        participant.error = operation.channels.filter(item => item.status === 'failed' || item.status === 'unconfirmed').map(item => item.error).filter(Boolean).join(' ') || 'One or more output routes did not confirm.';
                    } else if (operation.channels.some(item => item.status === 'unconfirmed')) {
                        participant.status = 'unconfirmed';
                        participant.error = 'One or more output routes are unconfirmed; review each output.';
                    }
                    if (failed && !unresolved) {
                        operation.status = 'partial';
                        if (operation.timer !== null) clearTimeout(operation.timer);
                        operation.timer = null;
                    }
                    this.tryFinalizeTakeAll();
                    if (operation.status !== 'pending' && operation.status !== 'partial') continue;
                }
                if (operation.channels.length && operation.channels.every(item => item.status === 'confirmed') && !operation.configSaved) {
                    operation.status = 'saving';
                    if (operation.timer !== null) clearTimeout(operation.timer);
                    const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
                    const group = config.virtualSwitchers[groupId];
                    if (operation.mode === 'direct') group.programTarget = operation.target;
                    else this.applyConfirmedGroupTake(group, operation.target, operation.previous);
                    this.configSavePurpose = `group-cut:${groupId}`;
                    if (!this.sendDashboardConfig(config, this.configSavePurpose)) {
                        operation.status = 'confirmed_config_failed'; this.configSavePurpose = null;
                        this.showError('All output routes confirmed, but the saved switcher state could not be updated.');
                    }
                } else if (operation.channels.some(item => ['failed', 'unconfirmed'].includes(item.status))) {
                    operation.status = 'partial';
                    if (!operation.channels.some(item => ['pending', 'dispatching'].includes(item.status))) {
                        if (operation.timer !== null) clearTimeout(operation.timer);
                        operation.timer = null;
                    }
                    this.showError('Virtual routing partially completed or was diverted. Review the actual output routes.');
                }
            }
            for (const [groupId, operation] of Object.entries(this.groupAlignOperations)) {
                if (!['pending', 'unconfirmed', 'partial'].includes(operation.status) || !Array.isArray(operation.channels)) continue;
                for (const item of operation.channels) {
                    if (!['pending', 'unconfirmed', 'dispatching'].includes(item.status)) continue;
                    const output = this.projectedOutputs.find(route => route.auxIndex === item.channel);
                    if (output?.routeStatus === 'observed' && output.liveSourceId === operation.target) item.status = 'confirmed';
                    else if (item.reviewRequested && output?.routeStatus === 'observed' && output.liveSourceId === item.before) {
                        item.status = 'failed'; item.error = `OUT ${output.outputId} remains on its previous route after review.`;
                    }
                    else if (output?.routeStatus === 'observed' && output.liveSourceId !== item.before) {
                        item.status = 'unconfirmed'; item.error = `OUT ${output.outputId} changed to an unexpected source.`;
                    }
                }
                if (operation.channels.length && operation.channels.every(item => item.status === 'confirmed')) {
                    operation.status = 'saving';
                    if (operation.timer !== null) clearTimeout(operation.timer);
                    const config = JSON.parse(JSON.stringify(this.dashboardConfig.config));
                    config.virtualSwitchers[groupId].programTarget = operation.target;
                    this.configSavePurpose = `group-align:${groupId}`;
                    if (!this.sendDashboardConfig(config, this.configSavePurpose)) {
                        operation.status = 'confirmed_config_failed'; this.configSavePurpose = null;
                        this.showError('Routes are aligned, but the saved Program target could not be updated.');
                    }
                } else if (operation.channels.some(item => ['failed', 'unconfirmed'].includes(item.status))) {
                    operation.status = 'partial';
                    if (operation.timer !== null) clearTimeout(operation.timer);
                    this.showError('Alignment partially completed or was diverted. Actual routes remain visible; no Program target was saved.');
                }
            }
        },

        markThreeCOperationsUnconfirmed(reason) {
            this.virtualDirect = { virtual1: false, virtual2: false };
            this.primaryRateEdit = null;
            if (this.primarySetupOperation) {
                clearTimeout(this.primarySetupOperation.timer);
                this.primarySetupOperation.unconfirmed = true;
            }
            if (this.dashboardConfigSaveTimer !== null) clearTimeout(this.dashboardConfigSaveTimer);
            this.dashboardConfigSaveTimer = null;
            if (this.dashboardConfigSaving) {
                this.dashboardConfigSaving = false;
                this.dashboardConfigError = 'Configuration save result is unknown after disconnect; reload settings before continuing.';
                if (this.routeBatch?.savingConfig) {
                    this.routeBatch.error = this.dashboardConfigError;
                    this.routeBatch = null;
                    this.assignmentBusy = false;
                }
                if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('group-cut:')) {
                    const groupId = this.configSavePurpose.split(':')[1];
                    const operation = this.groupCutOperations[groupId];
                    if (operation) {
                        operation.status = 'confirmed_config_failed';
                        operation.error = this.dashboardConfigError;
                    }
                } else if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('group-align:')) {
                    const groupId = this.configSavePurpose.split(':')[1];
                    const operation = this.groupAlignOperations[groupId];
                    if (operation) {
                        operation.status = 'confirmed_config_failed';
                        operation.error = this.dashboardConfigError;
                    }
                } else if (typeof this.configSavePurpose === 'string' && this.configSavePurpose.startsWith('take-all:') && this.takeAllOperation) {
                    this.failTakeAllConfig(this.dashboardConfigError);
                }
                this.configSavePurpose = null;
                this.configSaveExpected = null;
                this.dashboardConfigRequestedDeviceId = null;
                this.dashboardConfigRequestedRevision = null;
            }
            if (this.previewPending) {
                this.previewPending = false;
                this.previewUnconfirmed = true;
                if (this.previewPendingTimer !== null) clearTimeout(this.previewPendingTimer);
                this.previewPendingTimer = null;
            }
            if (this.stylePending) {
                this.stylePending = false;
                this.styleUnconfirmed = true;
                if (this.stylePendingTimer !== null) clearTimeout(this.stylePendingTimer);
                this.stylePendingTimer = null;
            }
            if (this.primaryActionPending) {
                this.primaryActionPending.unconfirmed = true;
                    if (this.primaryActionPending.takeAllId && this.takeAllOperation?.id === this.primaryActionPending.takeAllId) {
                        this.takeAllOperation.primary.status = 'unconfirmed';
                        this.takeAllOperation.primary.error = 'Connection closed before Primary confirmation.';
                        this.takeAllOperation.status = 'unconfirmed';
                    }
                if (this.primaryActionTimer !== null) clearTimeout(this.primaryActionTimer);
                this.primaryActionTimer = null;
            }
            for (const operation of Object.values(this.routeOperations)) {
                if (operation.status === 'pending') operation.status = 'unconfirmed';
                if (operation.timer !== null) clearTimeout(operation.timer);
                operation.timer = null;
            }
            for (const [groupId, operation] of Object.entries(this.groupCutOperations)) {
                if (['pending', 'saving'].includes(operation.status)) operation.status = 'unconfirmed';
                for (const item of operation.channels || []) {
                    if (['pending', 'dispatching'].includes(item.status)) item.status = 'unconfirmed';
                }
                if (operation.timer !== null) clearTimeout(operation.timer);
                operation.timer = null;
                if (operation.takeAllId && this.takeAllOperation?.id === operation.takeAllId) {
                    this.takeAllOperation[groupId].status = 'unconfirmed';
                    this.takeAllOperation[groupId].error = 'Connection closed before output confirmation.';
                    this.takeAllOperation.status = 'unconfirmed';
                }
            }
            for (const operation of Object.values(this.groupAlignOperations)) {
                if (['pending', 'saving'].includes(operation.status)) operation.status = 'unconfirmed';
                for (const item of operation.channels || []) {
                    if (['pending', 'dispatching'].includes(item.status)) item.status = 'unconfirmed';
                }
                if (operation.timer !== null) clearTimeout(operation.timer);
                operation.timer = null;
            }
            if (reason) this.showError(reason);
        },

        get primaryActionTimer() { return this._primaryActionTimer ?? null; },
        set primaryActionTimer(value) { this._primaryActionTimer = value; },

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
