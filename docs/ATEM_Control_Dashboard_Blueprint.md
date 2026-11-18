# ATEM Control Dashboard
## Product and Technical Blueprint — Version 0.6

**Decision date:** November 17, 2026

**Status:** Approved architecture and planning specification; Milestone 3 implementation is not authorized by this document

**Base:** WebATEM 2.6.0, extended in this repository

**Reference device:** Blackmagic ATEM 1 M/E Constellation 4K

**Decision record:** [ADR 0001](adr/0001-three-logical-switchers.md)

**Implementation status:** Current code is still the Milestone 2 three-physical-output dashboard. This blueprint describes the next architecture.

This document supersedes version 0.5's operator model of three fixed physical output panels and its old Milestone 3 plan. Preserve WebATEM's existing `/atem/control/` surface, shared connection, command dispatcher, media, audio, settings, macros, profiles, and HyperDeck features. Hardware observations and later explicit operator decisions take precedence over assumptions here. **MUST** is an acceptance requirement; **VERIFY ON DEVICE** requires a controlled rehearsal with operator approval. No automated test may send commands to the physical ATEM by default.

## 1. Product model and scope

The Production Dashboard presents three **switching controls**, not three physical destinations:

1. **PRIMARY SWITCHER** controls the real hardware M/E 1 Program and Preview buses, transitions, and keyers. It exists even when no physical output carries M/E Program.
2. **VIRTUAL SWITCHER 1** is a software-defined Preview/Program group for zero or more physical AUX-routable outputs.
3. **VIRTUAL SWITCHER 2** is a separate software-defined group with its own assignments, queue, target, pending state, and errors.
4. **OTHER OUTPUTS**, below the columns, lists every discovered physical output not effectively controlled by those groups and offers direct routing where the device exposes a validated command path.

A physical output is a hardware routing destination. A virtual switcher is an application control group using AUX routing; it is not another M/E. The current source routed to each physical output is always ATEM-owned. Logical ownership, queues, targets, and presentation preferences are application-owned. Neither a saved assignment nor a transmitted command proves the physical route changed. Use **Primary Switcher**, **Virtual Switcher 1**, and **Virtual Switcher 2** as default operator-facing names; AUX remains the correct hardware/protocol term.

Discover physical output count, identity, connector label, route, controllability, and available source IDs at runtime. The reference model may expose six assignable SDI outputs; that is a hardware expectation to verify, never a loop bound or fallback. Show an output with an unknown or unsupported route as read-only with its actual observed status and a reason. Do not invent output-to-AUX channel mappings. OUT 1 is a preferred initial Primary destination **when appropriate and explicitly selected**, never a mandatory or automatically routed destination.

The new dashboard remains text/source-state based. Live multiview video and thumbnails require separate SDI capture or encoding in a later phase; they are not prerequisites. Use source IDs, not names, for routing. Preserve source labels and availability from the device; support duplicate, blank, renamed, and unavailable source labels without confusing identities.

## 2. Architecture and state ownership

### 2.1 Existing integration to reuse

The current dashboard is `atem_control/templates/dashboard.html` and `atem_control/static/js/production_dashboard.js`. WebATEM serves `/atem/dashboard/` alongside stock `/atem/control/`. `atem_control/control/consumer.py` receives commands through `/ws/atem/`, uses the pooled `ATEMInstanceManager`, and dispatches through `atem_control/control/commands.py`. The installed `atemwire.state` builds `sources`, `auxOutputs`, `mes`, `dsks`, and `topology`. The command map already names `set_aux_output`, `set_program`, `set_preview`, `cut`, `auto`, `set_transition_style`, `toggle_usk`, and `toggle_dsk`; verify payloads and device support at implementation time. Do not open a second UDP connection or bypass WebATEM's permissions and command transport.

The current `topology.outputs` is derived from output port metadata and `auxOutputs` is keyed `aux1..auxN`. This does **not** itself prove that physical OUT number N maps to AUX channel N-1 on every switcher. The dashboard must establish a verified connector-to-command-channel map or refuse writes for unmapped outputs. The installed `atemwire` readers can return source ID `0` when a Program/Preview/AUX field is missing, and the transition reader supplies safe-looking BKGD-only defaults when settings are absent. ID `0` may also be the real Black source, so neither default is **proof of observed state**. Expose separate field-presence/completeness signals from actual received packets before enabling affected actions.

### 2.2 Conceptual state model

| Record | Required fields and owner |
|---|---|
| Device identity | Verified stable device key, current address, model, capability snapshot, connected/readiness time; hardware/integration owned |
| Physical output | Stable connector key, display name, validated AUX command channel if controllable, observed source ID, observation time; hardware owned |
| Source | Hardware source ID, short/long names, type, per-destination availability; hardware owned |
| Primary | M/E 1 Program background, Preview, transition style/status/selection completeness, discovered USKs and DSKs; hardware owned |
| Primary destinations | **Derived** from all observed physical routes equal to the discovered M/E 1 Program feed source ID; no saved ownership list |
| Virtual switcher configuration | Stable group ID 1 or 2, assigned output keys, queued Preview source ID, saved Program target, custom display name, preferences, revision; application owned |
| Effective AUX group state | Per-output observed routes, uniform live ID or MIXED ROUTING, conflicts, readiness; derived from hardware plus configuration |
| Operation | Intended target per engine/output, initiating configuration and hardware revisions, pending/confirmed/unconfirmed/error status; application runtime, journaled where needed |

Keep **observed hardware**, **saved configuration**, **queued operator choice**, **pending command**, and **confirmed outcome** separate in APIs and UI. Program red means a currently observed live hardware source. An AUX group with no assigned output may show `Saved target: IN X`, but must show `No live group output`, not a red ON AIR claim. A mixed group shows each destination's observed source and no single red Program source. On disconnect, last values are labeled **STALE / LAST OBSERVED**, not current truth.

Do not assume that the M/E background source label describes the fully composited Program signal. Upstream and downstream keys may be present on the M/E Program feed. Releasing a Primary output to a direct input preserves only the background input, not key overlays.

### 2.3 Persistence and identity

Milestone 3A should add a small, versioned Django/SQLite dashboard configuration model keyed by a **verified per-device identity**, with an optimistic revision number. Persist AUX 1 and AUX 2 assignments, queued Previews, saved Program targets, minimum-Primary-destination policy (default **on**), and relevant dashboard preferences. Keep original WebATEM connection history and stock settings in their existing owners. A browser's `sessionStorage` alone is insufficient for group configuration.

First inspect whether the ATEM/WebATEM state provides a stable hardware identifier. mDNS may advertise a unique ID, but its availability and match to a direct-IP connection must be verified. If a stable hardware ID is unavailable, require an explicit device-pairing record with a locally generated ID and confirmed address/device details; do not silently load another device's configuration based only on a recycled IP, mutable name, or model. Identity ambiguity blocks configuration writes and live group actions until resolved. Address changes should use a reviewed rebind, not an implicit new identity.

Configuration writes use compare-and-swap by revision in a backend transaction. Reject stale browser edits and broadcast the new revision to other sessions through existing app infrastructure. A queued Preview is shared per logical group and device, so every tab sees the same queue and its author/revision; this supersedes the old per-tab virtual Preview rule. No browser may silently overwrite another operator's queue. Pending operations need server-side coordination by physical output and M/E engine so multiple tabs cannot issue duplicate writes. Deployment with multiple worker processes must use coordination that works across those processes, not only an in-memory lock.

On startup/reconnect, load configuration, rediscover capabilities/routes, and compute effective ownership. Never send hardware routing commands merely to make saved configuration match the device. Mark invalid or missing outputs/sources as conflicts and request operator review. Persisting a Program target does not make it live.

### 2.4 Backend/API changes required in Milestone 3

Extend the **existing** WebSocket/state path or a narrowly scoped authenticated Django endpoint with: (a) a read-only dashboard projection of output identities, validated command-channel mapping, observed routes, source availability, M/E bus and transition-data completeness, and state age; (b) per-device configuration plus revision; (c) compare-and-swap queue/configuration updates; (d) explicit assignment/release and group-operation requests with per-output results. Keep existing `atem_state` and stock consumers compatible. Do not claim a command was confirmed merely because `dispatch_command` accepted it for transmission.

Before each hardware-affecting request, the backend must re-read shared connection state, check freshness/identity/ownership/source availability and relevant pending operations, then send through existing dispatch. A preflight narrows races but cannot be atomic against an external ATEM panel; reconcile subsequent hardware state and report uncertainty. Each multi-output operation needs an operation ID, exact intended route per output, independent confirmation or timeout, and no automatic replay of an uncertain command. Define and test idempotent request handling before exposing these endpoints to multiple tabs. Use the existing audit hook for operator-visible actions where available.

## 3. Ownership and assignment rules

### 3.1 Effective ownership

1. Any physical output **observed** to carry the discovered M/E 1 Program feed is a Primary destination, regardless of saved AUX membership. There may be zero, one, or many. One M/E command changes the engine once and affects all such destinations.
2. An output saved in AUX 1 or AUX 2 belongs to that group only when the output exists, is controllable, is not observed as a Primary destination, and has no conflicting saved ownership.
3. A saved AUX output observed to route M/E Program is an **ownership conflict**: show its actual Primary route, suspend that output's AUX-group writes, and ask the operator to explicitly release it from the group or transfer it after reviewing the route change. Never silently overwrite the external action.
4. A discovered output with no effective group owner appears in Other Outputs. Unknown/unsupported outputs still appear there with read-only status.

The assignment dialog lists all discovered physical outputs with observed route, effective owner, capability, and checkbox state. Outputs owned by another logical group are unavailable for direct assignment. A requested transfer is a separate, explicit reviewed operation; it must not be a side effect of checking a box. Stage a multi-checkbox diff and show the intended command for each output before applying; a batch is not atomic.

### 3.2 Assigning or releasing Primary destinations

Checking an eligible output for Primary explicitly routes it to the **discovered** M/E 1 Program feed ID, waits for confirmed physical routing, then displays it under Primary. Confirm the requested route can be set on that output. A saved AUX owner must first be explicitly transferred; do not erase its configuration silently.

Unchecking a Primary output follows this exact sequence:

1. Read current authoritative M/E 1 **Program background** source and actual physical output route. Require fresh, complete state, a stable M/E with no transition in progress, and no conflicting pending operation.
2. Verify the background source is directly available on that physical AUX destination and is not just an M/E feed or unsupported substitute. Explain that key overlays will be lost.
3. Enforce the configurable minimum Primary destination policy. It defaults to one destination; block removal of the last one while enabled.
4. Present `OUT N: M/E Program → IN X (background only; keys removed)` for explicit operator confirmation. Recheck the source, transition, destination, policy, and route immediately before dispatch.
5. Send one route command for that output through the shared dispatcher. Wait for an observed route to IN X. Only then consider it released and display it in Other Outputs. Timeout or ambiguous state is **unconfirmed**; keep the observed ownership until hardware proves a change.

If the background source is unknown, not directly routable, or the M/E is transitioning, block and explain why. Never substitute Black or a color source. If another controller externally leaves zero Primary destinations, show a warning and keep the M/E panel usable subject to its own safety rules; do not force a route or falsely claim policy compliance. Turning the minimum policy off is a deliberate saved configuration change, not an automatic response.

### 3.3 Assigning or releasing logical AUX destinations

For an available output checked into AUX group G, require a directly routable source, known current route, and unconflicted identity. If the group has a uniform live route, **that observed live source** is the proposed assignment target, even when a saved target is stale after an external change. If the group is empty, use its explicitly selected saved Program target. A mixed group must first be resolved. Show the old-to-new route. Route the output only after explicit confirmation; add the saved assignment **after** observed hardware confirmation. Until then show pending or unconfirmed, never a live Program claim. A group may have zero outputs and a saved target.

Unchecking a group output removes its saved membership with a revision-checked configuration update, **without any ATEM routing command**. Its observed physical source remains unchanged and it appears under Other Outputs unless actual hardware says it is Primary. If a group has multiple outputs, one release does not change the remaining outputs. Neither logical group may own the same output. A transfer between groups requires an explicit diff, destination target, routing confirmation, and coordinated configuration update; partial results must remain visible for reconciliation.

### 3.4 External changes and mixed routing

For an AUX group with assigned outputs, derive live state from **all** their observed routes. If they match, show one red Program source and the per-output list. If they differ, show **MIXED ROUTING**, every output's true source, and no single red Program. Do not rewrite divergent outputs automatically. Suspend ordinary group CUT while mixed.

The explicit resolution workflow is: choose a target source, review a per-output route diff and any ownership conflict, confirm an **Align group outputs** operation, then track each physical result independently. This is a deliberate routing action, not an implicit CUT. A uniform post-confirmation route may become the saved Program target; partial success remains MIXED. If the operator wants to retain divergent routes, they may release selected outputs to Other Outputs without changing hardware. External M/E reassignment, source rename, source loss, disconnect, and another browser's configuration change all recompute readiness and ownership rather than restoring old routes.

## 4. Operator interface

### 4.1 PRIMARY SWITCHER column

Always show M/E 1 Program background, Preview, transition state/style, next-transition background/key selections, all discovered upstream keyers and downstream keyers, and `OUTPUTS: OUT …` derived from actual M/E Program feed routes. The compact **Change** button opens the assignment dialog. Zero destinations yields a conspicuous warning, not a missing Primary panel. No software T-bar.

At the top, show **Primary Switcher** (or its Custom Name), then compact badges for every output actually routed to M/E Program, followed by **Change**. Show `M/E PROGRAM` directly beneath the header to identify the hardware engine. Badge examples such as `[OUT 1] [OUT 5]` are illustrative; derive all output names and membership from observed device routes. Custom Name changes presentation only, never the M/E identity, ownership, or routing.

Program buttons identify the authoritative live M/E background in red. Hardware Preview buttons identify the actual M/E Preview in green and send `set_preview` only when selected. A protected direct Program mode may expose `set_program` after explicit operator enablement; in normal Preview/CUT mode the Program row is an indicator and remains visibly red. CUT sends one native M/E CUT. AUTO sends one native M/E AUTO. MIX/WIPE selection, where supported, changes **transition style**; it does not execute a transition. Show unsupported styles disabled rather than guessing the device can perform them.

Provide an explicit Primary **take action** choice for future TAKE ALL (`CUT` or `AUTO`, default `CUT`), separately from transition style (`MIX`, `WIPE`, etc.). The operator must see both choices before TAKE ALL. Ordinary background-only CUT requires known BKGD selection, no tied keyer, no active transition, fresh state, and no engine pending action. Missing/malformed transition data blocks it. An AUTO with keyed next-transition selection is allowed only in a separately explicit keyed-transition workflow that identifies affected keys and has appropriate readiness and confirmation; never silently clear or modify key ties. Until verified, fail closed. Keyer on-air toggles use observed state, suppress duplicate pending toggles, and reconcile late results.

Show discovered upstream keyers in one compact row or wrapping grid, and discovered downstream keyers in a separate compact row immediately below. Match their button footprint to Preview/Program source buttons. Keep labels, fill-source information where available, and ON AIR/OFF AIR text readable. Give ON AIR, OFF AIR, pending, disabled, and hover distinct appearances. Reconcile each keyer independently against its observed target so a confirmed on-air toggle immediately permits an off-air toggle; one keyer's action must not unlock another. Use the existing WebATEM USK and DSK command paths with appropriate readiness checks.

### 4.2 VIRTUAL SWITCHER 1 and VIRTUAL SWITCHER 2 columns

Each column shows its saved output list, **Change**, queued green Preview, live red Program only when all assigned routes are uniform, saved target when empty, and independent pending/error status. An empty group's **Set target** action saves an explicitly chosen Program target without claiming any live hardware change. Preview selection is software-only and persists per device/group with revision checks. Program is read-only in normal mode. A direct Program mode, if retained, requires an explicit operator choice and the same per-output validation/confirmation as a group routing action.

Each header shows **Virtual Switcher 1** or **Virtual Switcher 2** (or its Custom Name), compact badges for validated persistent assignments, and a compact **Change** button. Examples such as `[OUT 2]` or `[OUT 3]` do not imply fixed assignments. A custom display name must not alter the stable group ID, ownership, queued source, or command target.

CUT routes queued Preview to **each** assigned physical output, one command per distinct destination as needed. Require a nonempty, conflict-free, uniform group; a valid different queued target; current observed routes; and no pending or stale state. Track each output independently and never describe the batch as atomic or frame synchronous. If all routes confirm, set saved Program target to the confirmed source. Swap the single known prior live source into Preview only after all expected routes confirm. On partial failure or late confirmation, show actual per-output routes, retain or mark the queue explicitly, and never invent one prior Program source. A mixed group must use the explicit resolution workflow first. A zero-output group has no live CUT action.

### 4.3 OTHER OUTPUTS

Show all discovered outputs without an effective owner in compact horizontally scrollable cards. Each card displays connector name/number, observed live source, source buttons using discovered labels and per-destination availability, pending/unconfirmed/error feedback, and a clear red active-source indicator even when selection is disabled. Selecting a valid source sends an immediate route command **for that output only** after safety checks and waits for hardware confirmation. Routing to the M/E Program feed is an ownership change; require the Primary assignment workflow and its explicit confirmation instead of making it an ordinary direct-source click. Unsupported output controls remain read-only with a reason.

### 4.4 Common presentation

Use source IDs under labels; order physical inputs, Black, color sources, then media players where available. Keep a currently live but otherwise filtered source visible as an observed status, never mislabel it. Green means queued or hardware Preview; red means **observed** live Program. Add ON AIR/NEXT text so color is not the only cue. Ready, hovered, pending, blocked, disconnected, stale, and unconfirmed states must be visually distinct and explain their reason. Brand styling must not erase a live red indicator when direct Program clicking is disabled, or make a ready CUT look disabled on hover. Preserve existing WebATEM page styles by scoping dashboard CSS.

Align all three panel bodies at the **top**. Each panel grows according to its own content; a shorter panel must not be vertically centered or bottom-aligned or push another panel downward. Retain the Custom Name control. Default names are Primary Switcher, Virtual Switcher 1, and Virtual Switcher 2; names are labels only and do not change internal identity or hardware routing.

### 4.5 TAKE ALL (3D only)

Keep a prominent **TAKE ALL** control visibly disabled through 3A–3C. Its eventual operation applies the selected Primary action (one M/E CUT or AUTO, if ready) and each AUX group's queued source to its assigned outputs. Preflight **every participating engine and physical output**, including ownership, mixed routing, source availability, key ties, transition status, freshness, and pending actions. A zero-output AUX group is an explicit nonparticipant; a group with outputs and no valid queue blocks. Prevent duplicate M/E commands and duplicate routing of any destination. Present the intended per-destination plan and confirmation appropriate to its impact.

Dispatch through the shared command path in a controlled sequence. Record independent confirmation, partial success/failure, and unknown outcomes. Do not auto-retry uncertain commands or attempt an automatic rollback. Never imply frame-accurate simultaneity. Controlled device rehearsal must measure and describe switching skew. TAKE ALL implementation and hardware testing require separate approval after 3A–3C review.

## 5. Safety and reconciliation contract

Before every hardware write, require a ready shared connection, fresh and sufficient state, validated device/output identity, a routable target, no ownership or pending conflict, and operation-specific guards. Disable action when data are missing or stale. Server-side preflight must re-read raw/shared state, because UI checks alone cannot protect against another tab. External hardware controls may race between preflight and command; do not promise atomicity against them.

The original M/E UI guard treated absent transition data as safe, and `atemwire` can synthesize BKGD-only defaults. Milestone 2.1 added raw-state server preflight. Hardware validation then showed an overstrict guard: `frames_remaining` could be nonzero while the observed `in_transition` flag was false and the handle position was zero. The remediation relies on the received transition packet, known BKGD/key selection, `in_transition === false`, and position zero; a residual frame count alone does not mark an active transition. Retain this fail-closed policy for redesigned CUT/AUTO/TAKE ALL, and verify the corrected CUT on isolated hardware. Do not change ATEM next-transition settings as a workaround. For intentional keyed transitions, require explicit intent and verify actual device semantics.

For all writes, distinguish accepted/enqueued, pending, confirmed by observed state, rejected, and timed out/unconfirmed. A timeout does not prove the route stayed unchanged. Continue reconciling late state; avoid a stale AUX Preview swap or false success when another operator selected the same target. A matching target route alone may be ambiguous if external changes occurred; retain operation generation/baseline and report uncertainty where causality cannot be established. On disconnect disable writes, label last observation stale, and resync before re-enabling. Never issue a catch-up route on reconnect.

Preserve stock `/atem/control/`, existing WebATEM hosting/authentication assumptions, `atemwire` Windows `select.select` workaround in the current `.venv`, and the current shared pool. Do not reinstall the venv without preserving the patch. Use the launcher-selected HTTP port, not a hardcoded port. Tests use fake/offline states by default. Physical rehearsal requires isolated destinations and explicit operator approval.

## 6. Milestones and implementation checkpoints

| Stage | Status and deliverable | Review gate |
|---|---|---|
| Milestone 0 | Historical integration inventory and WebATEM extension choice | Retained |
| Milestone 1 | Historical read-only three-physical-output foundation | Completed code, superseded UI model |
| Milestone 2 / 2.1 | Historical individual switching infrastructure and focused safety/reconciliation hardening | AUX operation observed working on physical ATEM; M/E CUT and USK follow-up corrections tested offline, awaiting controlled retest; old panel model superseded |
| **3A State and persistence** | Dynamic output/capability map, identity binding, saved logical assignments/queues/targets, revisions, mixed/conflict projection, server-side state freshness and transition completeness | Review design, migrations, fake-state behavior before 3B |
| **3B New interface** | Top-aligned Primary Switcher and two Virtual Switcher columns, output badges/Change, Custom Name, compact separate USK/DSK rows, Other Outputs, live indicators; TAKE ALL disabled | Review rendered/offline interaction behavior before 3C |
| **3C Assignment and individual control** | Primary assign/release, AUX assign/release, Other Outputs direct route, group CUT, M/E Program/Preview/CUT/AUTO/style, USK/DSK, per-output confirmation, fail-closed guards | Review fake-protocol results and plan controlled hardware rehearsal before 3D |
| **3D TAKE ALL** | Coordinated readiness, deduplicated dispatch, partial outcomes, controlled device validation | Separate implementation authorization after 3A–3C; explicit operator approval for hardware tests |
| Milestone 4+ / Later | Advanced settings, operational refinements, release hardening, optional packaging, SDI multiview capture/video thumbnails, and optional ATEM protocol simulator integration (evaluate pyAtemSim or equivalent for hardware-independent development and testing) | Separately scoped and authorized; simulator testing supplements, never replaces, physical hardware validation |

This document update authorizes **no Milestone 3 code**. Review each checkpoint before the next. Do not spend significant effort polishing the outgoing three-physical-output UI. Reuse Milestone 2's transport and tested behaviors where safe; replace assumptions tied to `panels[0..2]`, `aux1..aux3`, `outNumber - 1`, per-output session queues, and UI-only preflight.

## 7. Acceptance criteria and offline test plan

Every test that could send a command must run against a fake connection unless the operator explicitly opts into an isolated hardware rehearsal. Favor tests of actual JS/backend behavior over Python copies of controller logic or text-only template searches.

| ID | Acceptance condition |
|---|---|
| A01 | Discover zero, one, and many physical outputs from real topology/route metadata; never use a fixed count or guessed AUX channel map for writes. |
| A02 | Show Primary even with no M/E Program destination; list all observed M/E Program-fed outputs and use one M/E engine command. |
| A03 | Match source IDs to changing short/long labels, duplicate names, availability, and unsupported or unlisted live sources. |
| A04 | Persist each AUX group's distinct assignments, queue, Program target, and preferences per verified device across reload and restart. |
| A05 | Two tabs see the same configuration revision and queued Preview; stale edits are rejected without overriding another operator. |
| A06 | AUX Preview changes saved queue only; it sends no hardware route command. |
| A07 | Primary assignment routes an eligible output to discovered M/E Program feed only after explicit approval and observed route confirmation. |
| A08 | Primary release routes to the current M/E Program **background input**, confirms the route, then moves the output to Other Outputs; document loss of keys. |
| A09 | Block Primary release for unknown/unroutable background, transition in progress, stale state, pending conflict, or the last destination while policy is on. |
| A10 | External removal of every Primary destination produces a warning and no automatic hardware write. |
| A11 | AUX assignment routes an eligible output to the group's valid target and saves membership only after route confirmation. |
| A12 | AUX release changes saved ownership only; its physical route is unchanged and it appears under Other Outputs. |
| A13 | Prevent duplicate ownership; ownership transfers display reviewed old/new routes and reconcile partial outcomes. |
| A14 | Uniform AUX routes show a single hardware-derived red Program; empty groups show saved target without claiming ON AIR. |
| A15 | Divergent routes show MIXED ROUTING and every live source, no single Program highlight, no automatic rewrite, and no ordinary group CUT. |
| A16 | Explicit mixed-route alignment shows a per-output diff, requires confirmation, and reports each observed result. |
| A17 | Group CUT sends one command per assigned destination, suppresses duplicates, reports per-output confirmation, and swaps one known prior source only after complete confirmed success. |
| A18 | Other Outputs cards cover all remaining discovered outputs; direct route affects only the chosen output and displays confirmed state. |
| A19 | Primary Program and Preview indicators follow hardware and external changes even when Program clicks are disabled. |
| A20 | CUT and AUTO are distinct from transition-style selection; supported MIX/WIPE selection configures style without taking a transition; no T-bar is added. |
| A21 | Missing/malformed transition settings, active transition, unintended tied key, or stale state blocks background-only CUT; keyed AUTO requires explicit intent. |
| A22 | Discover USK and DSK counts dynamically; each keyer independently follows observed on-air state, clears pending on its own confirmed target, permits immediate on/off retoggle, and suppresses genuine duplicate pending actions. |
| A23 | Ready, hover, disabled, pending, blocked, mixed, disconnected, and unconfirmed UI states have clear distinct styling and reasons. |
| A24 | Late confirmation, command error, timeout, external route change, reconnect, and partial multi-output failure never claim unobserved success or trigger automatic retry. |
| A25 | TAKE ALL stays disabled through 3A–3C. In 3D, preflight every participant, dispatch at most one M/E action and one route per destination, and report partial results without claiming atomicity. |
| A26 | Stock WebATEM `/atem/control/`, AUX/M/E/keyer, audio, media, macros, profiles, HyperDeck, and settings routes still work; the new page shares the pooled connection. |
| A27 | Device identity ambiguity, unsupported output mapping, or mismatched saved capabilities blocks writes and does not apply another device's configuration. |
| A28 | Headers use default names Primary Switcher, Virtual Switcher 1, and Virtual Switcher 2; Custom Name changes only the displayed label, never stable identity or routing. Primary badges reflect observed M/E Program destinations; virtual badges reflect validated persistent assignments; each header has a compact Change control. |
| A29 | All three panel bodies align at the top and size independently; a short panel never shifts another panel down. |
| A30 | Primary shows compact source-sized USK buttons in one row/wrapping grid and DSK buttons immediately below in a separate row, with readable key/fill labels and distinct ON AIR, OFF AIR, pending, disabled, and hover states. |

**Hardware rehearsal, only with operator approval:** verify physical connector ↔ AUX command mapping; real M/E Program feed discovery; safe background-only CUT/USK behavior with keys tied and untied; transition-style and AUTO semantics; DSK control; Primary release background versus keyed composite; external route and multi-tab races; disconnect/reconnect; individual and TAKE ALL partial outcomes; stock control cross-view synchronization. Isolate every affected live destination before any write. Record observations separately from offline test results.

## 8. Decisions retained, revised, superseded, and deferred

| Earlier requirement | Disposition |
|---|---|
| Extend WebATEM, preserve all stock functions, use pooled ATEM connection and existing WebSocket/dispatch | **Retained** |
| Three columns representing physical OUT 1–3, with one designated M/E panel | **Superseded** by Primary hardware M/E plus two logical AUX groups; physical assignments are dynamic |
| Mirrored M/E Program outputs share one engine | **Retained** as Primary destinations; zero or many are valid |
| Per-browser AUX virtual Preview in `sessionStorage` | **Superseded** by persistent per-device/group queue with revisioned multi-session updates |
| One AUX CUT command per old panel | **Revised** to one command per assigned destination with independent confirmation |
| Reassigning M/E Program required operator-selected replacement | **Revised**: Primary release uses current verified M/E Program background; overlays are explicitly lost; block unsafe/unknown cases |
| Phase 1 USK toggles; DSK read-only | **Revised**: Primary includes discovered USK and DSK on-air controls |
| CUT ALL / Master CUT | **Superseded** by TAKE ALL, deferred to checkpoint 3D |
| Dynamic source labels, IDs, availability, and actual hardware state synchronization | **Retained** across all switchers and Other Outputs |
| Custom switcher display names | **Retained** in the new interface with defaults Primary Switcher, Virtual Switcher 1, and Virtual Switcher 2; labels never determine internal switcher identity or routes |
| Local output friendly names, button label style, source visibility/order | **Deferred** to a later dashboard preferences checkpoint; existing local names may be reused without replacing stock settings |
| Direct Program mode | **Revised** to an explicit protected action; normal Program rows remain read-only indicators while Primary still supports deliberate hardware Program selection |
| Staged input renames and broad ATEM settings editing | **Deferred**; reuse stock WebATEM settings and add focused staged updates only where needed |
| Automatically changing next-transition settings to force BKGD-only CUT | **Superseded**; missing or unsafe selection blocks ordinary CUT, and intentional keyed transitions need explicit intent |
| Protected/Instant Master safety slider | **Deferred** UX choice for TAKE ALL; no implied permission to enable it now |
| Live SDI multiview/video thumbnails | **Deferred** to independent video phase |
| Local ATEM protocol simulator for hardware-independent testing | **Deferred (Milestone 4+)**. Evaluate pyAtemSim or comparable simulators as optional development/testing infrastructure when physical hardware is unavailable. Not required for Milestones 2.1 or 3; simulator testing supplements rather than replaces physical hardware validation. |

The earlier architecture required an explicit replacement source on an output losing M/E Program. This revision resolves that conflict with a **specific, conditional** replacement: the current confirmed M/E Program background input, after routability and transition checks and operator approval. It cannot preserve key overlays; if that result is unacceptable, the operation must be cancelled. The old OUT 1–3 hardware observation (OUT 1 and OUT 2 both on M/E Program, OUT 3 on AUX) remains a historical observation, not a default configuration.

## 9. Open verification questions and references

1. Does this ATEM/WebATEM expose a stable device identifier through direct-IP and discovery paths? Determine the safe identity-binding mechanism before persistence is used for live actions.
2. Which discovered physical outputs have validated `set_aux_output` channel mappings on the reference hardware? What routes are read-only or unsupported?
3. Can raw transition packets distinguish a truly received BKGD-only selection from `atemwire` defaults before enabling CUT/AUTO? How fresh must state be under the actual polling cadence?
4. Which M/E Program feed ID and source availability flags apply on this hardware? Do not treat fixture ID `10010` as universal.
5. What are actual AUTO, MIX/WIPE, USK, and DSK semantics with tied keyers on the device? Verify before live use.
6. Can a route confirmation be distinguished from a concurrent external command to the same target? Define conservative unconfirmed reporting for ambiguous cases.
7. Which WebATEM deployment modes use multiple workers or hosts, and what shared coordination/broadcast mechanism is available for revisions and pending operations?
8. How should a deliberately keyed TAKE ALL action be confirmed and presented after controlled operator rehearsal?

References retained from version 0.5: [WebATEM source](https://github.com/lucas-romanenko/webatem), [bmdwire source](https://github.com/lucas-romanenko/bmdwire), [ATEM Constellation specifications](https://www.blackmagicdesign.com/products/atemconstellation/techspecs/W-APS-40), [Blackmagic ATEM SDK manual](https://documents.blackmagicdesign.com/DeveloperManuals/ATEMSDKManual.pdf), and [ATEM Software Control](https://www.blackmagicdesign.com/products/atemsdi/software). These are protocol and hardware references; inspected repository code and verified device state determine implementation details.

**Definition of done:** The new dashboard presents Primary Switcher and Virtual Switchers 1 and 2 over all discovered supported physical outputs, accurately shows remaining outputs and live routes, guards and confirms every write, preserves stock WebATEM, and passes offline behavioral tests plus an explicitly authorized isolated hardware rehearsal. The virtual switchers remain independent, persistent logical AUX groups internally. Milestone 3D TAKE ALL and the independent video phase are not implied by completion of 3A–3C.
