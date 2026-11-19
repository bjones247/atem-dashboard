# ATEM Control Dashboard
## Product and Technical Blueprint — Version 0.7

**Decision date:** November 17, 2026

**Status:** Approved architecture; Milestones 1, 2, 2.1, and 3A–3D are software-complete. The project is stopped before controlled physical ATEM acceptance testing, which requires explicit operator approval.

**Base:** WebATEM 2.6.0, extended in this repository

**Reference device:** Blackmagic ATEM 1 M/E Constellation 4K

**Decision record:** [ADR 0001](adr/0001-three-logical-switchers.md)

**Implementation status:** The dashboard presents the hardware Primary Switcher, Virtual Switcher 1, Virtual Switcher 2, and a horizontally scrolling Unswitched Outputs row. Milestone 3D TAKE ALL is implemented. The final software audit's two identified defects—premature release of a pending routing operation on an unexpected route, and key-only AUTO confirmation based only on M/E Program changes—have been remediated and covered by offline regression tests. Controlled physical ATEM acceptance testing remains pending; software completion does not establish live hardware behavior. Live multiview/video thumbnails, simulator evaluation, multi-worker coordination, and other later-phase work remain deferred as described below. For this installation, the operator has specified a fixed OUT 1–6 ↔ AUX 1–6 convention. It is configuration supplied by the operator, not discovered protocol state, and is enabled only when topology reports exactly six AUX channels.

This document supersedes version 0.5's operator model of three fixed physical output panels and its old Milestone 3 plan. Preserve WebATEM's existing `/atem/control/` surface, shared connection, command dispatcher, media, audio, settings, macros, profiles, and HyperDeck features. Hardware observations and later explicit operator decisions take precedence over assumptions here. **MUST** is an acceptance requirement; **VERIFY ON DEVICE** requires a controlled rehearsal with operator approval. No automated test may send commands to the physical ATEM by default.

## 1. Product model and scope

The Production Dashboard presents three **switching controls**, not three physical destinations:

1. **PRIMARY SWITCHER** controls the real hardware M/E 1 Program and Preview buses, transitions, and keyers. It exists even when no physical output carries M/E Program.
2. **VIRTUAL SWITCHER 1** is a software-defined Preview/Program group for zero or more physical AUX-routable outputs.
3. **VIRTUAL SWITCHER 2** is a separate software-defined group with its own assignments, queue, target, pending state, and errors.
4. **UNSWITCHED OUTPUTS**, below the columns, lists every discovered physical output not effectively controlled by those groups and offers direct routing where the device exposes a validated command path.

A physical output is a hardware routing destination. A virtual switcher is an application control group using AUX routing; it is not another M/E. The current source routed to each physical output is always ATEM-owned. Logical ownership, queues, targets, and presentation preferences are application-owned. Neither a saved assignment nor a transmitted command proves the physical route changed. Use **Primary Switcher**, **Virtual Switcher 1**, and **Virtual Switcher 2** as default operator-facing names; AUX remains the correct hardware/protocol term.

The supported installation has six physical SDI connectors, labeled OUT 1 through OUT 6. For this installation, the operator has specified OUT n uses AUX n, corresponding to protocol AUX index n−1. Keep AUX indices as internal command/configuration keys and show physical OUT labels to operators. This fixed convention is not discovered or confirmed by the ATEM protocol. Require `_top.aux_outputs == 6`; missing, fewer, or extra channels produce a configuration error and block physical-output assignment rather than creating guessed routes. OUT 1 is a preferred initial Primary destination **when appropriate and explicitly selected**, never a mandatory or automatically routed destination.

The new dashboard remains text/source-state based. Live multiview video and thumbnails require separate SDI capture or encoding in a later phase; they are not prerequisites. Use source IDs, not names, for routing. Preserve source labels and availability from the device; support duplicate, blank, renamed, and unavailable source labels without confusing identities.

## 2. Architecture and state ownership

### 2.1 Existing integration to reuse

The current dashboard is `atem_control/templates/dashboard.html` and `atem_control/static/js/production_dashboard.js`. WebATEM serves `/atem/dashboard/` alongside stock `/atem/control/`. `atem_control/control/consumer.py` receives commands through `/ws/atem/`, uses the pooled `ATEMInstanceManager`, and dispatches through `atem_control/control/commands.py`. The installed `atemwire.state` builds `sources`, `auxOutputs`, `mes`, `dsks`, and `topology`. The command map already names `set_aux_output`, `set_program`, `set_preview`, `cut`, `auto`, `set_transition_style`, `toggle_usk`, and `toggle_dsk`; verify payloads and device support at implementation time. Do not open a second UDP connection or bypass WebATEM's permissions and command transport.

For this installation, physical OUT 1–6 use corresponding AUX 1–6, and protocol AUX indices 0–5 address those buses. The installed ATEM is configured by the operator to route each connector through its matching AUX bus. WebATEM/atemwire exposes the selected source for each AUX bus, not independent physical connector routing state, so the projection applies this declared convention and marks its mapping source as `installation_convention`. It cannot verify that the physical output configuration still follows the convention after external changes. The topology must report exactly six AUX channels; otherwise all physical output assignments are unresolved and blocked. `InPr` port type 129 describes AUX output sources. The installed `atemwire` readers can return source ID `0` when a Program/Preview/AUX field is missing, and the transition reader supplies safe-looking BKGD-only defaults when settings are absent. ID `0` may also be the real Black source, so neither default is **proof of observed state**. Expose separate field-presence/completeness signals from actual received packets before enabling affected actions.

### 2.2 Conceptual state model

| Record | Required fields and owner |
|---|---|
| Device identity | Verified stable device key, current address, model, capability snapshot, connected/readiness time; hardware/integration owned |
| Routable AUX destination | Device-scoped zero-based channel ID from `AuxS`/topology, exact command channel, observed source ID; internal key maps by this installation convention to OUT n+1; hardware route is AUX-observed |
| Source | Hardware source ID, short/long names, type, per-destination availability; hardware owned |
| Primary | M/E 1 Program background, Preview, transition style/status/selection completeness, discovered USKs and DSKs; hardware owned |
| Primary destinations | **Derived** from all observed physical routes equal to the discovered M/E 1 Program feed source ID; no saved ownership list |
| Virtual switcher configuration | Stable group ID 1 or 2, assigned output keys, queued Preview source ID, saved Program target, custom display name, preferences, revision; application owned |
| Effective AUX group state | Per-output observed routes, uniform live ID or MIXED ROUTING, conflicts, readiness; derived from hardware plus configuration |
| Operation | Intended target per engine/output, initiating configuration and hardware revisions, pending/confirmed/unconfirmed/error status; application runtime, journaled where needed |

Keep **observed hardware**, **saved configuration**, **queued operator choice**, **pending command**, and **confirmed outcome** separate in APIs and UI. Program red means a currently observed live hardware source. An AUX group with no assigned output may show `Saved target: IN X`, but must show `No live group output`, not a red ON AIR claim. A mixed group shows each destination's observed source and no single red Program source. On disconnect, last values are labeled **STALE / LAST OBSERVED**, not current truth.

The M/E Program feed can contain upstream and downstream keys in addition to the background. Releasing a Primary output replaces that composite with Color Bars.

### 2.3 Persistence and identity

Milestone 3A uses a small, versioned Django/SQLite dashboard configuration model keyed by the active connection's protocol-reported ATEM `WhoI` `device_id` (32 hexadecimal characters), with an optimistic revision number. Persist Virtual Switcher 1 and 2 assignments, queued Previews, saved Program targets, minimum-Primary-destination policy (default **on**), custom switcher names, and relevant dashboard preferences. Keep original WebATEM connection history and stock settings in their existing owners. A browser's `sessionStorage` alone is insufficient for group configuration. This dashboard supports one active ATEM connection at a time; each device's settings remain isolated by its protocol ID.

Persisted destination integers remain zero-based AUX indices for compatibility and command dispatch. The projection translates index n to physical OUT n+1 using the approved installation convention. This translation is not protocol-derived. If AUX topology is not exactly six, the projection reports `installation_topology_mismatch`, marks all six OUT destinations unresolved/unavailable, and rejects configuration updates.

Never substitute IP address, mDNS TXT identity, device name, or model for a missing or malformed `WhoI` ID. The installed protocol parser exposes the `WhoI` field directly; the mDNS listener independently reads the TXT property named `unique id`, and this repository has no evidence proving those values are equal. A missing or ambiguous protocol ID blocks configuration load and save, without blocking unrelated hardware controls or creating a fallback association. The Blackmagic SDK's `GetUniqueId` API describes a switcher-unique identifier, but persistence across reboot/IP changes still requires confirmation against the deployed device/firmware. Address is metadata only and may change without changing the configuration key. No pairing or multi-device management UI is planned.

Configuration writes use atomic compare-and-swap by revision in a backend transaction. Reject stale browser edits. The WebSocket consumer joins a device-ID revision group, broadcasts successful revisions, refreshes other sessions, and includes the projection on state updates. The configured Channels backend is `InMemoryChannelLayer` and deployment is restricted to one Uvicorn worker, so revision notifications and the switching pending-operation lock are process-local. Within that deployment, pending operations are keyed by M/E engine or physical AUX output and suppress conflicting browser commands. Database CAS rejects stale writes against the shared database even when a push is missed. A queued Preview is shared per logical group and device, so every tab sees the same queue and its revision; no browser may silently overwrite another operator's queue. Do not deploy multiple workers or processes until shared revision notifications and cross-process hardware-operation coordination are added and tested.

At startup, reconnect, and on external route changes, the shared WebSocket monitor computes effective ownership from saved configuration, topology, and received `AuxS` routes. OUT labels are physical numbers and AUX indices remain internal. The protocol cannot verify the physical OUT-to-AUX setup. Preserve the installation convention in ATEM Software Control. Stale observations cannot establish current ownership. Ambiguous M/E Program identity and unsupported destinations stay unresolved or read-only. The monitor never sends a hardware route to reconcile settings. A saved target only becomes live when the hardware reports it.

### 2.4 Backend/API changes required in Milestone 3

The existing WebSocket/state path now carries: (a) read-only dashboard projection of output identities, validated command-channel mapping, observed routes, source availability, M/E bus and transition-data completeness, and state age; (b) per-device configuration plus revision; (c) compare-and-swap configuration updates; (d) explicit assignment/release, group CUT, mixed-route alignment, and direct output route requests. Keep existing `atem_state` and stock consumers compatible. Do not claim a command was confirmed merely because dispatch accepted it for transmission.

Before each hardware-affecting request, the backend re-reads the shared connection state, checks freshness/identity/ownership/source availability and relevant pending operations, then sends through existing dispatch. A preflight narrows races but cannot be atomic against an external ATEM panel; reconcile subsequent hardware state and report uncertainty. Multi-output operations use one command per destination with independent observed confirmation, explicit timeout review, and no automatic replay of uncertain commands. The operation lock and route pending records are process-local; their safety relies on the documented single-worker deployment. Cross-process command coordination is required before multi-worker deployment. Use the existing audit hook for operator-visible actions where available.

## 3. Ownership and assignment rules

### 3.1 Effective ownership

1. Any physical output **observed** to carry the discovered M/E 1 Program feed is a Primary destination, regardless of saved AUX membership. There may be zero, one, or many. One M/E command changes the engine once and affects all such destinations.
2. An output saved in AUX 1 or AUX 2 belongs to that group only when the output exists, is controllable, is not observed as a Primary destination, and has no conflicting saved ownership.
3. A fresh, verified M/E Program route supersedes any saved AUX claim. Show that output only in Primary and exclude it from virtual groups immediately. Remove the old virtual membership through a revision-checked settings update and notify open dashboards. This reconciliation never sends an ATEM route command. If a route operation is pending, keep the observation against the current settings revision in the pooled connection until it can be saved. After retirement, an output that leaves Program appears in Unswitched Outputs until explicitly reassigned.
4. A discovered output with no effective group owner appears in Unswitched Outputs. Unknown/unsupported outputs still appear there with read-only status.

The assignment dialog lists all discovered physical outputs with observed route, effective owner, capability, and checkbox state. Outputs owned by another logical group are unavailable for direct assignment. A requested transfer is a separate, explicit reviewed operation; it must not be a side effect of checking a box. Stage a multi-checkbox diff and show the intended command for each output before applying; a batch is not atomic.

### 3.2 Assigning or releasing Primary destinations

Checking an eligible output for Primary explicitly routes it to the **discovered** M/E 1 Program feed ID, waits for confirmed physical routing, then displays it under Primary. Confirm the requested route can be set on that output. A saved AUX owner must first be explicitly transferred; do not erase its configuration silently.

Unchecking a Primary output follows this exact sequence:

1. Verify that the output still carries M/E Program. Require fresh, complete state, a stable M/E with no transition in progress, and no conflicting pending operation.
2. Find the unique Color Bars source in the ATEM input catalog and verify it is AUX-routable. Block release when discovery is ambiguous or Bars is unavailable.
3. Enforce the configurable minimum Primary destination policy. It defaults to one destination; block removal of the last one while enabled.
4. Present `OUT N: M/E Program → Color Bars` for explicit operator confirmation. Recheck the source, transition, destination, policy, and route immediately before dispatch.
5. Send one route command through the shared dispatcher. Confirm release when the ATEM reports Color Bars. Display the actual route if an external change intervenes, and keep the release outcome unconfirmed if the requested result is uncertain.

When another controller leaves zero Primary destinations, show a warning and keep the M/E panel usable subject to its own safety rules. The dashboard minimum applies to deliberate dashboard edits.

### 3.3 Assigning or releasing logical AUX destinations

For a new virtual assignment, require a directly routable source, a current route, and clear ownership. A uniform group uses its observed live source. An empty group uses its saved Program target if it has one. With no saved target, add one unowned output first and save its verified current feed as the target without sending a route command. Resolve a mixed group before adding another output. Show the route change before Apply and require a fresh review if an edited output or target changes. Save membership after observed confirmation, or after verifying an already matching route.

Unchecking a group output removes its saved membership with a revision-checked configuration update, **without any ATEM routing command**. Its observed physical source remains unchanged and it appears under Unswitched Outputs unless actual hardware says it is Primary. If a group has multiple outputs, one release does not change the remaining outputs. Neither logical group may own the same output. A transfer between groups requires an explicit diff, destination target, routing confirmation, and coordinated configuration update; partial results must remain visible for reconciliation.

### 3.4 External changes and mixed routing

An external change between ordinary sources keeps virtual membership. Show a warning beside CUT with each output's observed route and the expected target. When routes differ, the group has no single red Program source. A deliberate CUT can align the outputs to the staged source. The warning clears after all assigned routes confirm.

The explicit resolution workflow is implemented in 3C: choose a directly routable target, review every output's current-to-target route diff, confirm **Align mixed routes**, then track each physical result independently. This is a deliberate routing action, not an implicit CUT. A uniform post-confirmation route becomes the saved Program target only after every route is observed; partial success remains mixed. If the operator wants to retain divergent routes, they may release selected outputs to Unswitched Outputs without changing hardware. External M/E reassignment, source rename, source loss, disconnect, and another browser's configuration change all recompute readiness and ownership rather than restoring old routes.

## 4. Operator interface

### 4.1 PRIMARY SWITCHER column

Show M/E 1 Program background, Preview, transition style, upstream and downstream keyers, and destination badges derived from actual Program routes. CUT and AUTO show the reason when blocked. Keyed AUTO confirmation lists the affected keyers. The assignment pencil opens the output dialog, and zero destinations show a warning while the Primary panel remains available.

At the top, show **Primary Switcher** (or its Custom Name), then compact badges for every output actually routed to M/E Program, followed by **Change**. Show `M/E PROGRAM` directly beneath the header to identify the hardware engine. Badge examples such as `[OUT 1] [OUT 5]` are illustrative; derive all output names and membership from observed device routes. Custom Name changes presentation only, never the M/E identity, ownership, or routing.

Program buttons identify the authoritative live M/E background in red. Hardware Preview buttons identify the actual M/E Preview in green and send `set_preview` only when selected. A protected direct Program mode may expose `set_program` after explicit operator enablement; in normal Preview/CUT mode the Program row is an indicator and remains visibly red. CUT sends one native M/E CUT. AUTO sends one native M/E AUTO. MIX/WIPE selection, where supported, changes **transition style**; it does not execute a transition. Show unsupported styles disabled rather than guessing the device can perform them.

TAKE ALL always uses Primary CUT. Primary AUTO is available in the Primary card. Ordinary background-only CUT requires known BKGD selection, no tied keyer, no active transition, fresh state, and no engine pending action. Missing/malformed transition data blocks it. An AUTO with keyed next-transition selection is allowed only in a separately explicit keyed-transition workflow that identifies affected keys and has appropriate readiness and confirmation; never silently clear or modify key ties. Until verified, fail closed. Keyer on-air toggles use observed state, suppress duplicate pending toggles, and reconcile late results.

Show discovered upstream and downstream keyers together in one compact row or wrapping grid. Match their button height and footprint to Preview/Program source buttons. Keep key labels and fill-source information where available. The active red styling identifies ON AIR; do not spend button space repeating ON AIR/OFF AIR text. Give active, inactive, pending, unknown, disabled, and hover states distinct appearances. Reconcile each keyer independently against its observed target so a confirmed on-air toggle immediately permits an off-air toggle; one keyer's action must not unlock another. Use the existing WebATEM USK and DSK command paths with appropriate readiness checks.

At desktop widths, all three switcher cards have equal height within the row. Their Preview and Program source grids start at the same vertical positions, and their CUT buttons share a horizontal baseline. Reserve the Primary keyer section's space in each Virtual Switcher card so content differences do not move the CUT controls.

### 4.2 VIRTUAL SWITCHER 1 and VIRTUAL SWITCHER 2 columns

Each column shows its saved output list, **Change**, queued green Preview, live red Program only when all assigned routes are uniform, saved target when empty, and independent pending/error status. An empty group's **Set target** action saves an explicitly chosen Program target without claiming any live hardware change. Preview selection is software-only and persists per device/group with revision checks. For assigned outputs, Enable Direct arms live Program selection for that virtual switcher. Selecting a source checks each output and routes the group directly. Confirm every output before saving Program and preserve staged Preview. The toggle resets after disconnect, a device change, or an assignment change.

Each header shows **Virtual Switcher 1** or **Virtual Switcher 2** (or its Custom Name), compact badges for validated persistent assignments, and a compact **Change** button. Examples such as `[OUT 2]` or `[OUT 3]` do not imply fixed assignments. A custom display name must not alter the stable group ID, ownership, queued source, or command target.

CUT routes queued Preview to each assigned output that needs a change. Require a nonempty group with clear ownership, a valid queued target other than M/E Program, a fresh observation and matching baseline for every output, and no conflicting pending operation. A group may start with uniform or mixed routes. Save Program only after all outputs confirm. Swap the single known prior routable source into Preview when one exists, or clear Preview after a successful mixed take. Partial and uncertain results preserve the staged source and show each affected output. An empty group has no live CUT action.

### 4.3 UNSWITCHED OUTPUTS

Show all discovered outputs without an effective owner in compact horizontally scrollable cards. Show the connector label, a light yellow **OUTPUT** badge for ordinary outputs, and the observed source's long name once. Show unresolved and stale states explicitly and label a retained stale source as last seen. Keep the source buttons, red active indicator, and pending, unconfirmed, or error feedback. Selecting an eligible source routes only that output after safety checks and waits for hardware confirmation. Routing to M/E Program requires the Primary assignment workflow.

### 4.4 Common presentation

Use source IDs under labels; order physical inputs, Black, Color Bars, color sources, then media players where available. Show discovered Bars on each bus and disable selection where the ATEM marks it unavailable. Keep a currently live but otherwise filtered source visible as an observed status, never mislabel it. Green means queued or hardware Preview; red means **observed** live Program. Add ON AIR/NEXT text so color is not the only cue. Ready, hovered, pending, blocked, disconnected, stale, and unconfirmed states must be visually distinct and explain their reason. Brand styling must not erase a live red indicator when direct Program clicking is disabled, or make a ready CUT look disabled on hover. Preserve existing WebATEM page styles by scoping dashboard CSS.

Align all three panel bodies at the **top**. Each panel grows according to its own content; a shorter panel must not be vertically centered or bottom-aligned or push another panel downward. Retain the Custom Name control. Default names are Primary Switcher, Virtual Switcher 1, and Virtual Switcher 2; names are labels only and do not change internal identity or hardware routing.

### 4.5 TAKE ALL (Milestone 3D)

On desktop, place TAKE ALL below both virtual switchers and stretch its card down to the bottom of Primary when the content fits. Stack the cards on narrow screens. Use the same red action style as CUT for the TAKE ALL button.

TAKE ALL coordinates one guarded Primary CUT with Virtual Switcher 1 and 2 CUTs. It does not operate on Unswitched Outputs. Before dispatch, the server validates the active connection and protocol device identity, fresh raw state, current configuration revision, six-AUX installation topology, output ownership and routes, queued virtual sources, Primary transition state/key ties, and all conflicting pending operations. A failure in any required preflight check sends no command. Zero-output virtual groups are skipped and reported; the Primary action still participates.

After successful preflight, use the existing guarded Primary and virtual group dispatch paths in deterministic order: Primary, Virtual Switcher 1, then Virtual Switcher 2. This is a coordinated sequence, not an atomic or frame-synchronous operation. Track each participant and each physical virtual output independently. Confirm changes only from observed hardware state; save confirmed virtual Program/Preview results using the current revision check. Preserve successful results when another participant fails. Do not retry uncertain commands or automatically roll back. Keep unresolved outputs locked until explicit read-only review; after review, show the reconciled result before a deliberate new action.

TAKE ALL software work is the 3D checkpoint. Isolated hardware rehearsal remains separate and requires explicit operator approval; measure and describe actual switching skew before claiming operational timing characteristics.

## 5. Safety and reconciliation contract

Before every hardware write, require a ready shared connection, fresh and sufficient state, validated device/output identity, a routable target, no ownership or pending conflict, and operation-specific guards. Disable action when data are missing or stale. Server-side preflight must re-read raw/shared state, because UI checks alone cannot protect against another tab. External hardware controls may race between preflight and command; do not promise atomicity against them.

The original M/E UI guard treated absent transition data as safe, and `atemwire` can synthesize BKGD-only defaults. Milestone 2.1 added raw-state server preflight. Hardware validation then showed an overstrict guard: `frames_remaining` could be nonzero while the observed `in_transition` flag was false and the handle position was zero. The remediation relies on the received transition packet, known BKGD/key selection, `in_transition === false`, and position zero; a residual frame count alone does not mark an active transition. Retain this fail-closed policy for redesigned CUT/AUTO/TAKE ALL, and verify the corrected CUT on isolated hardware. Do not change ATEM next-transition settings as a workaround. For intentional keyed transitions, require explicit intent and verify actual device semantics.

For all writes, distinguish accepted/enqueued, pending, confirmed by observed state, rejected, and timed out/unconfirmed. A timeout does not prove the route stayed unchanged. Continue reconciling late state; avoid a stale AUX Preview swap or false success when another operator selected the same target. A matching target route alone may be ambiguous if external changes occurred; retain operation generation/baseline and report uncertainty where causality cannot be established. On disconnect disable writes, label last observation stale, and resync before re-enabling. Never issue a catch-up route on reconnect.

Preserve stock `/atem/control/`, existing WebATEM hosting/authentication assumptions, `atemwire` Windows `select.select` workaround in the current `.venv`, and the current shared pool. Do not reinstall the venv without preserving the patch. Use the launcher-selected HTTP port, not a hardcoded port. Tests use fake/offline states by default. Physical rehearsal requires isolated destinations and explicit operator approval.

## 6. Milestones and implementation checkpoints

| Stage | Status and deliverable | Review gate |
|---|---|---|
| Milestone 0 | Historical integration inventory and WebATEM extension choice | Retained |
| Milestone 1 | Historical read-only three-physical-output foundation | Software-complete historical foundation; its three-physical-output UI is superseded |
| Milestone 2 / 2.1 | Historical individual switching infrastructure and focused safety/reconciliation hardening | Software-complete; physical acceptance of switching behavior remains pending. The old panel model is superseded |
| **3A State and persistence** | Dynamic AUX route/source projection, protocol identity, saved logical assignments/queues/targets, revisions, ownership and mixed/conflict reconciliation, state freshness | Software-complete and offline-tested. The fixed installation convention maps OUT 1 through OUT 6 to AUX 1 through AUX 6 only with six reported channels; the protocol does not verify physical AUX setup or deployed-device identity/feed behavior, which remain hardware acceptance checks. Multi-worker coordination is deferred |
| **3B New interface** | Read-only Primary Switcher and two Virtual Switcher columns, dynamic ownership badges, Custom Name, live/saved source distinctions, stale/unresolved/conflict/mixed route states, Unswitched Outputs; no assignment or switching controls; TAKE ALL absent | Software-complete and offline-tested; physical acceptance remains pending |
| **3C Assignment and individual control** | Primary assign/release, AUX assign/release, Unswitched Outputs direct route, group CUT and explicit mixed-route alignment, M/E Program/Preview/CUT/AUTO/style, USK/DSK, per-output confirmation, fail-closed guards | Software-complete and offline-tested. Final-audit pending-operation and key-only AUTO confirmation defects are remediated; physical acceptance remains pending |
| **3D TAKE ALL** | Coordinated readiness, deduplicated dispatch, partial outcomes, controlled device validation | Software-complete and offline-tested; physical acceptance remains pending and requires explicit operator approval |
| Milestone 4+ / Later | Advanced settings, operational refinements, release hardening, optional packaging, SDI multiview capture/video thumbnails, and optional ATEM protocol simulator integration (evaluate pyAtemSim or equivalent for hardware-independent development and testing) | Deferred for separate scoping and authorization; simulator evaluation is optional and supplements, never replaces, physical hardware validation |

Milestones 3A–3C provide state projection, the three-switcher interface, and individual guarded operations. The current stop line is **after Milestone 3D software completion and before hardware rehearsal or later work**. Offline tests use fake state and are not physical hardware validation. The configured app remains single-worker because configuration notifications and hardware-operation locks are process-local. Reuse Milestone 2's transport and tested behavior where safe; do not revive old `panels[0..2]`, `aux1..aux3`, or UI-only preflight assumptions.

### Future enhancements

- **View Log** would gather dashboard activity in one place. Show when each action was sent and when the ATEM confirmed it, with per-output outcomes for coordinated actions. Include blocked, failed, and unconfirmed actions so operators can review them alongside successful activity. Keep active warnings and review controls visible where they are needed.

## 7. Acceptance criteria and offline test plan

Every test that could send a command must run against a fake connection unless the operator explicitly opts into an isolated hardware rehearsal. Favor tests of actual JS/backend behavior over Python copies of controller logic or text-only template searches.

| ID | Acceptance condition |
|---|---|
| A01 | Discover AUX channels and source capabilities from actual topology/source catalog. For this installation, require exactly six channels and map protocol AUX index n to physical OUT n+1 by the operator-provided convention; route commands still receive AUX index n. |
| A02 | Show Primary even with no M/E Program destination; list observed Program-fed physical outputs using the declared OUT/AUX convention, while retaining one M/E engine command. |
| A03 | Match source IDs to changing short/long labels, duplicate names, availability, and unsupported or unlisted live sources. |
| A04 | Persist each AUX group's distinct assignments, queue, Program target, and preferences per verified device across reload and restart. |
| A05 | Two tabs on the configured channel layer receive configuration revision changes and the updated configuration; stale edits are rejected without overriding another operator. Multi-worker push delivery requires a shared Channels backend; database compare-and-swap still rejects stale edits. |
| A06 | AUX Preview changes saved queue only; it sends no hardware route command. |
| A07 | Primary assignment routes an eligible output to the discovered M/E Program feed after review, then waits for hardware confirmation. |
| A08 | Primary release routes to verified **Color Bars**, confirms the route, then moves the output to Unswitched Outputs. |
| A09 | Block Primary release for unknown or unroutable Bars, active transition, stale state, pending conflict, or the final destination while policy is on. |
| A10 | External removal of every Primary destination produces a warning and no automatic hardware write. |
| A11 | AUX assignment routes an eligible output to the group's valid target and saves membership only after route confirmation. |
| A12 | AUX release changes saved ownership only; its physical route is unchanged and it appears under Unswitched Outputs. |
| A13 | Prevent duplicate ownership; ownership transfers display reviewed old/new routes and reconcile partial outcomes. |
| A14 | Uniform AUX routes show a single hardware-derived red Program; empty groups show saved target without claiming ON AIR. |
| A15 | Divergent ordinary routes preserve virtual membership and show a warning beside CUT. A deliberate CUT can align current, verified routes to Preview. |
| A16 | Explicit mixed-route alignment shows a per-output diff, requires confirmation, and reports each observed result. |
| A17 | Group CUT sends one command per assigned destination, suppresses duplicates, reports per-output confirmation, and swaps one known prior source only after complete confirmed success. |
| A18 | Unswitched Outputs cards cover all remaining discovered outputs; direct route affects only the chosen output and displays confirmed state. |
| A19 | Primary Program and Preview indicators follow hardware and external changes even when Program clicks are disabled. |
| A20 | CUT and AUTO are distinct from transition-style selection; supported MIX/WIPE selection configures style without taking a transition; no T-bar is added. |
| A21 | Missing/malformed transition settings, active transition, unintended tied key, or stale state blocks background-only CUT; keyed AUTO requires explicit intent. |
| A22 | Discover USK and DSK counts dynamically; each keyer independently follows observed on-air state, clears pending on its own confirmed target, permits immediate on/off retoggle, and suppresses genuine duplicate pending actions. |
| A23 | Ready, hover, disabled, pending, blocked, mixed, disconnected, and unconfirmed UI states have clear distinct styling and reasons. |
| A24 | Late confirmation, command error, timeout, external route change, reconnect, and partial multi-output failure never claim unobserved success or trigger automatic retry. |
| A25 | TAKE ALL preflights all participants before any write; issues one Primary CUT and at most one command per assigned virtual output; skips empty groups; excludes Unswitched Outputs; confirms and reports every result independently; keeps uncertain operations locked for explicit review; never retries or rolls back automatically and never claims atomicity. |
| A26 | Stock WebATEM `/atem/control/`, AUX/M/E/keyer, audio, media, macros, profiles, HyperDeck, and settings routes still work; the new page shares the pooled connection. |
| A27 | Only the connected protocol `WhoI.device_id` selects saved dashboard configuration. Missing, malformed, or ambiguous identity blocks config access without IP/name/model/mDNS fallback; a different ID receives only its own config or defaults. Revision-checked updates reject stale sessions. |
| A28 | Headers use default names Primary Switcher, Virtual Switcher 1, and Virtual Switcher 2; Custom Name changes only the displayed label, never stable identity or routing. Primary badges reflect observed M/E Program destinations; virtual badges reflect validated persistent assignments. Assignment controls are implemented in 3C. |
| A29 | All three panel bodies align at the top and size independently. Primary presents observed hardware M/E Program and Preview. Virtual panels present saved logical Preview/Program targets separately from observed physical routes. |
| A30 | Unswitched Outputs contains every discovered output not effectively owned by one of the three switchers, using physical OUT labels and observed live source values; stale, unresolved, unavailable, and conflicting state is explicit. |
| A31 | Virtual groups show a per-output mismatch warning when routes diverge and omit a single red live source. Missing or unexpected AUX topology blocks output writes. |
| A32 | An external M/E Program takeover moves the output exclusively to Primary and retires its old virtual membership without a hardware write. A later ordinary route appears in Unswitched Outputs. |
| A33 | The first unowned output added to an empty group with no saved target keeps its verified current feed without a hardware write. |

**Hardware rehearsal requires operator approval.** Verify the OUT n to AUX n setup, M/E Program and Color Bars discovery, explicit release to Bars, virtual membership retirement after an external move to Program, and mixed-route CUT and TAKE ALL. Also check keyer and transition behavior, external and multi-tab races, disconnect/reconnect, partial outcomes, and stock control synchronization. Isolate every affected live destination before any write. Record hardware observations separately from offline results.

## 8. Decisions retained, revised, superseded, and deferred

| Earlier requirement | Disposition |
|---|---|
| Extend WebATEM, preserve all stock functions, use pooled ATEM connection and existing WebSocket/dispatch | **Retained** |
| Three columns representing physical OUT 1–3, with one designated M/E panel | **Superseded** by Primary hardware M/E plus two logical AUX groups; physical assignments are dynamic |
| Mirrored M/E Program outputs share one engine | **Retained** as Primary destinations; zero or many are valid |
| Per-browser AUX virtual Preview in `sessionStorage` | **Superseded** by persistent per-device/group queue with revisioned multi-session updates |
| One AUX CUT command per old panel | **Revised** to one command per assigned destination with independent confirmation |
| Reassigning M/E Program required operator-selected replacement | **Revised**: Primary release uses verified Color Bars after explicit review and routability checks |
| Phase 1 USK toggles; DSK read-only | **Revised**: Primary includes discovered USK and DSK on-air controls |
| CUT ALL / Master CUT | **Superseded** by TAKE ALL, deferred to checkpoint 3D |
| Dynamic source labels, IDs, availability, and actual hardware state synchronization | **Retained** across all switchers and Unswitched Outputs |
| Custom switcher display names | **Retained** in the new interface with defaults Primary Switcher, Virtual Switcher 1, and Virtual Switcher 2; labels never determine internal switcher identity or routes |
| Local output friendly names, button label style, source visibility/order | **Deferred** to a later dashboard preferences checkpoint; existing local names may be reused without replacing stock settings |
| Direct Program mode | **Revised** to an explicit protected action; normal Program rows remain read-only indicators while Primary still supports deliberate hardware Program selection |
| Staged input renames and broad ATEM settings editing | **Deferred**; reuse stock WebATEM settings and add focused staged updates only where needed |
| Automatically changing next-transition settings to force BKGD-only CUT | **Superseded**; missing or unsafe selection blocks ordinary CUT, and intentional keyed transitions need explicit intent |
| Protected/Instant Master safety slider | **Deferred** UX choice for TAKE ALL; no implied permission to enable it now |
| Live SDI multiview/video thumbnails | **Deferred** to independent video phase |
| Local ATEM protocol simulator for hardware-independent testing | **Deferred (Milestone 4+)**. Evaluate pyAtemSim or comparable simulators as optional development/testing infrastructure when physical hardware is unavailable. Not required for Milestones 2.1 or 3; simulator testing supplements rather than replaces physical hardware validation. |

The operator selected Color Bars as the replacement when explicitly releasing an output from Primary. Observe the current route, verify Bars availability, and confirm the change before reporting success. The old OUT 1–3 hardware observation remains historical.

## 9. Open verification questions and references

1. Does this ATEM/WebATEM expose a stable device identifier through direct-IP and discovery paths? Determine the safe identity-binding mechanism before persistence is used for live actions.
2. Does the deployed switcher remain configured with OUT n routed through AUX n after external changes or reset? This is an installation assumption, not protocol-observed state; inspect ATEM Software Control before enabling connector-specific routing after a configuration change.
3. Can the M/E Program output feed be identified from capabilities when its source labels have been customized? The projection fails closed if it cannot uniquely classify the discovered M/E output source.
4. Can raw transition packets distinguish a truly received BKGD-only selection from `atemwire` defaults before enabling CUT/AUTO? How fresh must state be under the actual polling cadence?
5. Which M/E Program feed ID and source availability flags apply on this hardware? Do not treat fixture ID `10010` as universal.
6. What are actual AUTO, MIX/WIPE, USK, and DSK semantics with tied keyers on the device? Verify before live use.
7. Can a route confirmation be distinguished from a concurrent external command to the same target? Define conservative unconfirmed reporting for ambiguous cases.
8. Which WebATEM deployments need multiple workers/hosts, and what shared Channels backend is available for revision pushes? 3C currently relies on one worker for revision notifications and command-pending coordination; add and test a shared channel layer plus cross-process hardware-operation coordination before multi-worker deployment.
9. Verify that TAKE ALL blocks when an upstream key is tied to the Primary transition. Verify the standalone keyed AUTO confirmation separately.

References retained from version 0.5: [WebATEM source](https://github.com/lucas-romanenko/webatem), [bmdwire source](https://github.com/lucas-romanenko/bmdwire), [ATEM Constellation specifications](https://www.blackmagicdesign.com/products/atemconstellation/techspecs/W-APS-40), [Blackmagic ATEM SDK manual](https://documents.blackmagicdesign.com/DeveloperManuals/ATEMSDKManual.pdf), and [ATEM Software Control](https://www.blackmagicdesign.com/products/atemsdi/software). These are protocol and hardware references; inspected repository code and verified device state determine implementation details.

**Definition of done:** The new dashboard presents Primary Switcher and Virtual Switchers 1 and 2 over the supported physical outputs, accurately shows remaining outputs and live routes, guards and confirms every write, preserves stock WebATEM, and passes offline behavioral tests. Milestone 3D additionally completes coordinated TAKE ALL with preflight and per-operation outcomes. Physical hardware rehearsal remains separately operator-approved. The virtual switchers remain independent, persistent logical AUX groups internally; independent video work remains later-phase scope.
