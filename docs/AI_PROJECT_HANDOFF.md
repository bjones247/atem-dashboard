# ATEM Dashboard — AI Project Handoff

**Updated for Milestone 3D TAKE ALL.** [Blueprint v0.6](ATEM_Control_Dashboard_Blueprint.md) and [ADR 0001](adr/0001-three-logical-switchers.md) remain authoritative for architecture. Milestone 3D coordinates the selected Primary CUT/AUTO and both virtual group CUTs using the existing 3C dispatch paths. Offline verification and exact commands are recorded below. No physical ATEM commands were sent. Physical rehearsal remains a separate operator-approved step.

## Immediate assignment and stop line

**Milestones 3A–3D are implemented and offline-tested. Stop for review; do not begin another milestone.** The dashboard includes guarded assignment/release, direct output routing, Primary M/E controls, individual virtual group CUT, mixed-route alignment, and TAKE ALL. TAKE ALL preflights every participant before dispatch, then invokes the existing Primary CUT/AUTO path and Virtual Switcher 1/2 CUT paths in order. Each output and switcher result remains separately confirmed; empty virtual groups are reported as skipped. It does not touch Other Outputs, retry uncertain commands, roll back successful actions, or claim frame-synchronous switching. Confirmed virtual results are saved through revision-checked configuration. No physical ATEM commands were sent. Physical validation requires separate explicit operator approval and isolated destinations.

## Approved product model

The outgoing three physical OUT 1–3 columns are superseded. The target dashboard has **Primary Switcher** (the real M/E 1 engine, independent of physical destination), **Virtual Switcher 1**, **Virtual Switcher 2** (separate logical groups with zero or more physical AUX-routable destinations), and **Other Outputs** (every remaining discovered physical output). These are default operator-facing names; Custom Name affects labels only. The reference 1 M/E Constellation 4K has physical SDI connectors OUT 1–6. The operator has specified this installation convention: OUT n is routed through AUX n, addressed by protocol index n−1. Keep AUX indices internal and display OUT numbers to operators. This mapping is an installation convention, not protocol-discovered state; it is usable only when topology reports exactly six AUX channels. The protocol does not independently verify that each physical output still uses its assigned AUX bus. No automatic hardware route changes occur on load or reconnect.

Primary lists every output actually carrying M/E Program, possibly zero or many, and issues one M/E command regardless of destination count. Assigning an output to Primary explicitly routes it to the discovered M/E Program feed after validation and confirmation. Releasing one routes it to the current verified M/E Program **background input**, with operator confirmation and warning that key overlays will not remain; unsafe/unknown cases block. Minimum one Primary destination is a configurable dashboard policy, on by default; external zero-destination state warns without auto-fixing hardware.

A logical AUX group owns saved assignments, queued Preview, and Program target per device. Its red Program is derived from all assigned outputs' actual routes: uniform route = one live source, divergent routes = **MIXED ROUTING**, empty group = saved target but no ON AIR claim. Virtual Preview updates revision-checked configuration and sends no ATEM command. Group CUT, mixed-route alignment, and TAKE ALL may issue one route command per assigned output; each result is confirmed separately. AUX release only changes saved ownership and preserves the physical route. Other Outputs provides immediate, output-specific routing and is excluded from TAKE ALL.

Primary will provide hardware Program/Preview, CUT, AUTO, supported transition-style selection (MIX/WIPE where available), discovered USK/DSK on-air controls, transition/tie status, and an explicit future TAKE ALL action choice. Style selection and transition execution are separate. No software T-bar. Ordinary background-only CUT must fail closed when transition state is missing, tied unexpectedly, or active. Keyed transitions need explicit intent; do not silently alter next-transition settings.

Persist both Virtual Switcher groups' assignments, queued Previews, Program targets, custom names, and dashboard preferences in versioned backend storage keyed only by the active connection's valid protocol `WhoI.device_id` (32 hex characters). One ATEM connection is supported at a time. Do not use mDNS `unique id`, IP, name, model, or pairing as fallback identity; missing or ambiguous protocol identity blocks configuration access. IP is metadata only. Revision-checked compare-and-swap writes prevent stale sessions from silently overwriting a newer configuration. The configured Channels backend is `InMemoryChannelLayer`; revision notifications and the hardware-operation lock are process-local. The supported deployment is one Uvicorn worker. Do not deploy multiple workers until shared revision delivery and cross-process hardware-operation coordination are implemented. The mDNS TXT ID has not been verified against `WhoI.device_id`, and reboot stability must be confirmed against deployed hardware/firmware. Hardware remains authoritative for every physical route. See Blueprint §§2–5 for the model and API.

## Current repository and historical work

- Repo: `C:\Users\bill\Repos\atem-dashboard`, branch observed `feature/three-output-dashboard`; Milestone 2.1 baseline commit observed as `9d2adeb` (`Harden Milestone 2 dashboard switching guards`). Check HEAD and working tree before changing code.
- WebATEM 2.6.0 remains the base. Dashboard files: `atem_control/static/js/production_dashboard.js` and `atem_control/templates/dashboard.html`; existing shared control path: `atem_control/control/consumer.py`, `atem_control/control/commands.py`, `atemwire.state`; tests: `tests/unit/test_production_dashboard_m1.py` and `_m2.py`.
- Milestone 1 supplied read-only OUT 1–3 panels and linked M/E discovery. Milestone 2 added browser-session AUX Preview, individual AUX CUT with confirmed swap, M/E Preview/CUT, linked M/E deduplication, USK toggles, pending state, and initial tests. **This is useful switching infrastructure, not proof of live hardware readiness.** The old panel model and its per-panel queues will be replaced.
- `commands.py` already dispatches `set_aux_output`, `set_program`, `set_preview`, `cut`, `auto`, `set_transition_style`, `toggle_usk`, and `toggle_dsk`; inspect actual payloads, availability, and hardware semantics before reuse. WebSocket `/ws/atem/` and `ATEMInstanceManager` already share a pooled ATEM connection. Do not introduce another UDP client.
- At the start of this documentation turn, `atem_control/templates/dashboard.html` had a pre-existing unrelated uncommitted spacing/footer edit. `AGENTS.md`, this handoff, `.github/copilot-instructions.md`, and `.github/prompts/finish-milestone-2.prompt.md` were untracked. Preserve other operators' edits; inspect `git status` again before implementation.

## Verified code findings and defects

The outgoing PROGRAM grid originally lost its live red style to later-loaded disabled-button CSS. The source filter omitted some live source types. OUT 1's CUT hover lost red; OUT 2 shares the M/E engine and should use the same readiness; OUT 3 used gray `btn-primary` styling even when ready. Milestone 2.1 adds dashboard-scoped colors, live-source fallback text, shared M/E readiness, and visible AUX disabled reasons. These are focused validation repairs; the old panel model remains superseded.

**Milestone 2.1 safety correction:** `meKeyTied` and `meInTransition` still serve informational UI only; they previously treated missing data as false, while `atemwire` can synthesize BKGD-only defaults and source ID `0`. The dashboard now projects raw M/E bus, source catalog, transition selection/position, and receive freshness through `dashboardSafety`. Its new server-side `dashboard_cut_me` command rechecks that raw state, requires background-only with no tied keyers or active transition, validates expected buses, and serializes local preflight with dispatch. `dashboard_cut_aux` validates the discovered AUX channel, directly routable target, observed live baseline, freshness, and pending state. Both use the existing pooled connection and stock dispatcher. The browser keeps uncertain timeouts blocked until hardware state changes or an operator requests read-only review; it never retries automatically. The local preflight-to-command and external-controller races remain; these guards do not make switching atomic. Milestone 3A keeps saved assignments and command channels as zero-based AUX indices internally: 0–5 are AUX 1–6. The operator-provided installation convention maps those to OUT 1–6 for presentation and route projection when exactly six channels are reported. It is not protocol-discovered and the protocol does not independently verify the physical output configuration. The Primary projection also fails closed on ambiguous M/E Program source identity. Cross-process hardware command coordination is a prerequisite to multi-worker deployment; the current supported one-worker deployment uses process-local operation locks. The fixture M/E source ID `10010` is not universal authority.

Milestone 3C adds backend preflight and dispatch for Primary M/E controls, physical output routes, virtual group CUT, and mixed-route alignment. The client waits for observed route/state updates before changing ownership or saved Program targets, supports read-only review after timeouts, and does not retry uncertain hardware commands. Configuration saves are revision checked; competing session changes are not presented as successful local saves. The mixed-route workflow shows each output's current route and chosen target before explicit confirmation. The six-output installation convention and shared WebATEM command path remain unchanged. The UI uses no simulator and adds no hardware connection.

**Reproducible Milestone 3C offline verification (2026-11-18):** The prior checkpoint recorded 83 Python passes but did not preserve its exact command. The following expanded dashboard suite and commands supersede that untraceable count:

Python dashboard suite (89 passed, 2 optional browser tests skipped):

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest-acceptance-python tests/unit/test_dashboard_config.py tests/unit/test_dashboard_ownership.py tests/unit/test_dashboard_sessions.py tests/unit/test_device_identity.py tests/unit/test_production_dashboard_m1.py tests/unit/test_production_dashboard_m2.py tests/unit/test_production_dashboard_m21.py
```

Rendered Edge regressions (2 passed; mocked dashboard WebSocket only):

```powershell
$env:ATEM_RUN_OFFLINE_BROWSER_TEST='1'; .\.venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest-acceptance-browser tests/unit/test_production_dashboard_m21.py -k 'rendered_assignment_and_confirmation_dialogs_use_dashboard_alpine_scope or alpine_keyer_button_dom_with_offline_browser'
```

JavaScript behavioral suite (31 passed):

```powershell
node --test tests/js/production_dashboard_m21.test.cjs
```

Python compilation and whitespace validation:

```powershell
.\.venv\Scripts\python.exe -m compileall -q atem_control tests/unit/test_dashboard_config.py
git diff --check
```

The full Python suite skips the two Edge tests unless `ATEM_RUN_OFFLINE_BROWSER_TEST=1`; those tests passed separately as shown above. Django emits the existing missing `staticfiles/` directory warnings. These offline results do not establish ATEM protocol behavior or live hardware safety.

**Milestone 3D verification (2026-11-18):** The complete dashboard Python suite passed with optional Edge tests skipped (**102 passed, 2 skipped, 5 existing Django warnings** for the absent `staticfiles/` directory). All three rendered Edge browser tests passed separately (**3 passed, 2 Django warnings**):

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest-takeall-python-final2 tests/unit/test_dashboard_config.py tests/unit/test_dashboard_ownership.py tests/unit/test_dashboard_sessions.py tests/unit/test_device_identity.py tests/unit/test_production_dashboard_m1.py tests/unit/test_production_dashboard_m2.py tests/unit/test_production_dashboard_m21.py
```

Rendered Edge tests (real dashboard template/Alpine, mock WebSocket only):

```powershell
$env:ATEM_RUN_OFFLINE_BROWSER_TEST='1'; .\.venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider --basetemp=.pytest-takeall-rendered-final tests/unit/test_production_dashboard_m21.py -k 'alpine_keyer_button_dom_with_offline_browser or rendered_assignment_and_confirmation_dialogs_use_dashboard_alpine_scope or rendered_dashboard_keeps_live_program_visible_and_cut_reasons'
```

Standalone JavaScript suite: **36 passed**:

```powershell
node --test tests/js/production_dashboard_m21.test.cjs
```

Compilation and whitespace checks:

```powershell
.\.venv\Scripts\python.exe -m compileall -q atem_control tests/unit/test_dashboard_config.py tests/unit/test_production_dashboard_m21.py
git diff --check
```

The rendered tests load the real dashboard template, inline dashboard CSS, and Alpine; use an offline mock WebSocket; and check computed dialog/result visibility, TAKE ALL readiness and results, keyed-AUTO confirmation, keyer interaction, and Other Outputs horizontal overflow/direct controls. They send no hardware commands. One combined run encountered a transient Edge process access violation; rerunning all three rendered tests together passed. Tests remain offline; TAKE ALL's real transition skew, AUTO/keyer behavior, external-controller races, and live route confirmations still require controlled hardware rehearsal.

**Operator hardware findings and follow-up:** Individual AUX switching worked. Primary M/E CUT displayed `M/E transition frame count is unknown or not at rest.` The installed `TrPs` parser always supplies a frame-count field; a nonzero residual count can coexist with `in_transition=false` and handle position zero. The extra frame-count-equals-zero guard was removed; packet presence, transition flag, handle position, BKGD/key ties, buses, and connection freshness remain required. An upstream keyer turned on physically and displayed ON AIR, but its button stayed disabled until another keyer caused a new update. The dashboard rebuilt keyer objects on state updates while the timeout closure held an older object; reconciliation also compared the previous UI value instead of an explicit target. Keyer state now tracks each requested target and raw `KeOn` observation, with uncertain results left for read-only review. The outgoing dashboard implements USK controls only; DSK controls belong to the new Primary Switcher in 3C.

**Second keyer finding:** The operator reported that the key button still could not be clicked again until any other control was used. An offline headless Edge test with the real Alpine library reproduced it: the keyer's observed state was ON AIR, pending and unconfirmed were false, readiness was true, and the native button remained `disabled`. The keyer button now uses an ARIA disabled indicator and a guarded click handler, so a stale DOM property cannot block an otherwise ready action. The dashboard sends an explicit on/off target through the existing `set_usk_on_air` ATEM command path instead of asking the worker to reread state and invert it.

**Third keyer finding:** The operator then saw KEY 1 switch physically and display ON AIR while its button stayed gray with a no-symbol cursor. The same offline Alpine browser fixture reproduced a stale class and ARIA state: `reconcileUpstreamKeyers` replaced the keyer object on every hardware update, but Alpine reused the keyed button DOM. Reconciliation now updates each existing keyer object in place and replaces the array only when the discovered keyer set changes. The dashboard-scoped active style also disables the generic button color transition so hardware-confirmed ON AIR appears red immediately. The browser regression checks the red computed color, cleared ARIA disabled state, and the next OFF command without clicking another control. Physical retest remains required; no automated command was sent to the ATEM. Milestone 3C adds dynamically discovered DSK controls alongside USKs.

## Historical reference-hardware observation

During earlier validation, OUT 1 and OUT 2 both carried the **same** M/E Program feed; OUT 3 carried an independent AUX source, once labeled `MAC1 Lyrics`. This was a valid linked M/E configuration, not three independent switchers. The old plan preferred OUT 1 as the M/E control panel. In the new architecture Primary is always the M/E engine; OUT 1 may be a preferred destination but is never hardcoded or silently routed. The device's actual output count, connector mapping, and current routes must be rediscovered before any live action.

## Roadmap and review gates

| Stage | Work | Status |
|---|---|---|
| M1 | Read-only three-output foundation | Historical implementation; operator model superseded |
| M2 / 2.1 | Individual switching infrastructure and focused fail-closed hardening | AUX switching observed working on hardware; M/E CUT and USK corrections offline tested, awaiting controlled retest; old panel model superseded |
| **M3A** | Dynamic output/route projection, protocol device identity, persistent group config with revisions, mixed/conflict detection, transition completeness | Implemented and offline tested. Fixed OUT 1–6/AUX 1–6 installation convention is guarded by exact six-channel topology. Protocol does not verify physical connector setup; customized M/E Program-feed identification and cross-process coordination remain documented limitations |
| **M3B** | Read-only Primary + Virtual Switchers 1/2 + Other Outputs, live/saved state distinctions, dynamic ownership badges, Custom Name, stale/unresolved/conflict/mixed presentation | Implemented and reused by 3C |
| **M3C** | Explicit assignment/release, mixed-route alignment, group CUT, Other Outputs direct route, M/E Program/Preview/CUT/AUTO/style, USK/DSK, confirmation and fail-closed guards | Implemented; offline behavioral suite passes. Awaiting review and separate hardware rehearsal |
| M3D | TAKE ALL coordination, deduplication, partial results, controlled validation | Software implementation complete; review this checkpoint. Physical testing requires separate explicit approval |
| Later | Advanced settings, operational refinements, packaging, independent SDI multiview video/thumbnails | Deferred |

**3D implementation notes and risks:** server-side `dashboard_switching.py` validates current raw switcher state, six-channel installation topology, configuration revision, exclusive output ownership, route/source availability, and pending operations before dispatching anything. Primary executes first, followed by virtual1 and virtual2; each uses the existing guarded command path. Empty virtual groups are skipped. The browser displays per-switcher and per-output states and only saves a virtual group's swapped Preview/Program after observed confirmation. A partial failure remains visible and reviewable; no automatic retry or rollback occurs. The coordinated sequence is not atomic and external-controller races remain possible. Configuration notification and hardware-operation locks remain process-local, so deployment must stay single-worker. The OUT-to-AUX installation convention, actual transition/keyer semantics, and other protocol assumptions still require controlled hardware verification. No hardware commands were sent in 3D.

Blueprint §7 lists acceptance criteria A01–A31, including A28–A31 for switcher names, badges, Custom Name identity safety, top alignment, and combined compact USK/DSK row and equal-height aligned cards. Tests should exercise real JS/backend behavior rather than only search for template strings.

## Environment and unresolved verification

- Windows 11, Python 3.12 `.venv`, PowerShell. Launch with `.\.venv\Scripts\python.exe -m webatem` and use the launcher-selected port (previously 8880). Do not assume port 8000.
- `.venv/Lib/site-packages/atemwire/_socketqueue.py` has a local Windows fix replacing unsupported `socket.MSG_DONTWAIT` with `select.select` readiness; do not rebuild/reinstall the venv or overwrite `atemwire` without preserving it. Separate patched checkout: `C:\Users\bill\Repos\bmdwire` branch `fix/windows-udp-socket`; upstream status unverified.
- Default `%LOCALAPPDATA%\WebATEM\db.sqlite3` was previously found invalid (1 byte). Do not delete a backup. A separate dev directory may be set with `$env:WEBATEM_DATA_DIR = "$env:LOCALAPPDATA\WebATEM-Dev-M1"` before launching; this has not been verified here.
- Verify protocol device-ID stability across reboot/IP changes; preservation of the installed OUT n-to-AUX n setup; M/E Program feed identification when renamed; raw transition completeness; AUTO/WIPE/keyer behavior; route confirmation under external races; and shared Channels infrastructure if deploying multiple workers. `AuxS` and `CAuS` use the same zero-based AUX channel index. The projection maps that index to OUT n+1 only under the operator-provided convention and exact-six-topology guard; it does not discover physical SDI routing independently. The operator reported AUX switching success and the M/E/keyer corrections have not been physically retested.

**Next assistant:** Read `AGENTS.md`, this handoff, Blueprint v0.6, and ADR 0001; inspect code and working tree. Review the 3D code and test record above. Stop for operator review before physical rehearsal or later milestone work. Hardware rehearsal requires explicit operator approval, isolation of affected destinations, and the action checklist in the Blueprint. Do not deploy more than one worker until cross-process notifications and command coordination are implemented.
