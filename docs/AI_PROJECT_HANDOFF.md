# ATEM Dashboard — AI Project Handoff

**Updated November 17, 2026.** This summarizes the approved **documentation direction**. The authoritative target specification is [Blueprint v0.6](ATEM_Control_Dashboard_Blueprint.md), with the reason for the change in [ADR 0001](adr/0001-three-logical-switchers.md). Current code remains Milestone 2; no Milestone 3 implementation or physical hardware test has been authorized by this update.

## Immediate assignment and stop line

The operator authorized **documentation and planning only**: revise the blueprint, handoff, agent instructions, architecture decision, roadmap, acceptance criteria, state/persistence/API plan, and open hardware questions. Stop after those changes and await review before implementing checkpoint 3A. Do not connect to the physical ATEM, send hardware commands, enable TAKE ALL, or start redesign code under this authorization.

The next deliverable after approval is **Milestone 3A: state and persistence architecture**. Each checkpoint 3A, 3B, 3C, and 3D requires review before proceeding. Hardware validation requires separate explicit operator approval with affected destinations isolated.

## Approved product model

The outgoing three physical OUT 1–3 columns are superseded. The target dashboard has **PRIMARY** (the real M/E 1 engine, independent of physical destination), **AUX SWITCHER 1**, **AUX SWITCHER 2** (separate logical groups with zero or more physical AUX-routable destinations), and **OTHER OUTPUTS** (every remaining discovered physical output). Physical output count, routability, and command-channel mapping must be discovered and verified. No automatic hardware route changes occur on load or reconnect.

Primary lists every output actually carrying M/E Program, possibly zero or many, and issues one M/E command regardless of destination count. Assigning an output to Primary explicitly routes it to the discovered M/E Program feed after validation and confirmation. Releasing one routes it to the current verified M/E Program **background input**, with operator confirmation and warning that key overlays will not remain; unsafe/unknown cases block. Minimum one Primary destination is a configurable dashboard policy, on by default; external zero-destination state warns without auto-fixing hardware.

A logical AUX group owns saved assignments, queued Preview, and Program target per device. Its red Program is derived from all assigned outputs' actual routes: uniform route = one live source, divergent routes = **MIXED ROUTING**, empty group = saved target but no ON AIR claim. Virtual Preview sends no ATEM command. Group CUT may need one route command per assigned output with independent confirmation; mixed routing requires an explicit reviewed alignment workflow. AUX release only changes saved ownership and preserves the physical route. Other Outputs provides immediate, output-specific routing where a validated command path exists. TAKE ALL remains disabled until 3D.

Primary will provide hardware Program/Preview, CUT, AUTO, supported transition-style selection (MIX/WIPE where available), discovered USK/DSK on-air controls, transition/tie status, and an explicit future TAKE ALL action choice. Style selection and transition execution are separate. No software T-bar. Ordinary background-only CUT must fail closed when transition state is missing, tied unexpectedly, or active. Keyed transitions need explicit intent; do not silently alter next-transition settings.

Persist both logical AUX groups' assignments, queued Previews, Program targets, and dashboard preferences in versioned per-device backend storage. Use a verified stable hardware ID or explicit safe pairing when no stable ID is exposed. Use revision-checked writes and shared multi-session pending coordination; a browser `sessionStorage` queue is insufficient. Hardware remains authoritative for every physical route. See Blueprint §§2–5 for the planned model and API.

## Current repository and historical work

- Repo: `C:\Users\bill\Repos\atem-dashboard`, branch observed `feature/three-output-dashboard`, HEAD observed `a758e93` (`Milestone 2: Individual output switching, guarded M/E CUT, and USK toggles`). Check again before changing code.
- WebATEM 2.6.0 remains the base. Dashboard files: `atem_control/static/js/production_dashboard.js` and `atem_control/templates/dashboard.html`; existing shared control path: `atem_control/control/consumer.py`, `atem_control/control/commands.py`, `atemwire.state`; tests: `tests/unit/test_production_dashboard_m1.py` and `_m2.py`.
- Milestone 1 supplied read-only OUT 1–3 panels and linked M/E discovery. Milestone 2 added browser-session AUX Preview, individual AUX CUT with confirmed swap, M/E Preview/CUT, linked M/E deduplication, USK toggles, pending state, and initial tests. **This is useful switching infrastructure, not proof of live hardware readiness.** The old panel model and its per-panel queues will be replaced.
- `commands.py` already dispatches `set_aux_output`, `set_program`, `set_preview`, `cut`, `auto`, `set_transition_style`, `toggle_usk`, and `toggle_dsk`; inspect actual payloads, availability, and hardware semantics before reuse. WebSocket `/ws/atem/` and `ATEMInstanceManager` already share a pooled ATEM connection. Do not introduce another UDP client.
- At the start of this documentation turn, `atem_control/templates/dashboard.html` had a pre-existing unrelated uncommitted spacing/footer edit. `AGENTS.md`, this handoff, `.github/copilot-instructions.md`, and `.github/prompts/finish-milestone-2.prompt.md` were untracked. Preserve other operators' edits; inspect `git status` again before implementation.

## Verified code findings and defects

The current PROGRAM grid compares `panel.onAirSourceId` to a source ID, but Preview + CUT mode disables the buttons. A later-loaded brand CSS `:disabled` rule overrides the live red style. The source filter can omit some live source types. OUT 1's red CUT turns gray on hover because shared brand hover styling overrides `btn-error`. OUT 2 uses the same M/E CUT markup as OUT 1; its gray appearance may indicate tied keys, pending/disconnect, or the same CSS behavior, not an intentionally read-only secondary panel. OUT 3's `btn-primary` is styled gray even when enabled, and its disabled predicate omits no-queue/same-as-live readiness. These old-layout defects are documented for the 3B presentation work; avoid a large retroactive Milestone 2 UI polish.

**Critical safety defect:** `meKeyTied` and `meInTransition` currently treat missing data as false, and the installed `atemwire` transition reader can synthesize BKGD-only defaults before receiving real settings. Source readers can also return ID `0` for absent bus/route fields, which is ambiguous with actual Black. The current frontend guard can fail open. Checkpoint 3A must represent raw field completeness; 3C must block hardware M/E CUT/AUTO/TAKE ALL when safety cannot be certified. The current `outNumber - 1` AUX-channel assumption and fixture source ID `10010` are also not universal authority. Verify the actual physical connector ↔ AUX-channel map before any reassignment command.

The previous focused offline command passed **20 tests** after using a workspace-local pytest temp directory. These tests include Python simulations and text checks; they do not establish browser styling, actual JS behavior, full-suite health, or hardware validation. An earlier Antigravity report of 92 selected passing tests was not an independently verified full-suite or hardware result.

## Historical reference-hardware observation

During earlier validation, OUT 1 and OUT 2 both carried the **same** M/E Program feed; OUT 3 carried an independent AUX source, once labeled `MAC1 Lyrics`. This was a valid linked M/E configuration, not three independent switchers. The old plan preferred OUT 1 as the M/E control panel. In the new architecture Primary is always the M/E engine; OUT 1 may be a preferred destination but is never hardcoded or silently routed. The device's actual output count, connector mapping, and current routes must be rediscovered before any live action.

## Roadmap and review gates

| Stage | Work | Status |
|---|---|---|
| M1 | Read-only three-output foundation | Historical implementation; operator model superseded |
| M2 | Individual switching infrastructure | Implemented; not hardware validated; known safety/UI defects |
| **M3A** | Dynamic physical output/route projection, verified device identity, persistent group config with revisions, mixed/conflict detection, transition completeness | **Next proposed implementation checkpoint; await approval** |
| M3B | Primary + two AUX group columns, Other Outputs, staged assignment dialogs, accurate indicators | Review after 3A |
| M3C | Explicit assignment/release, group CUT, Other Outputs direct route, M/E Program/Preview/CUT/AUTO/style, USK/DSK, confirmation and fail-closed guards | Review after 3B; hardware rehearsal separately approved |
| M3D | TAKE ALL coordination, deduplication, partial results, controlled validation | Separate approval after 3A–3C |
| Later | Advanced settings, operational refinements, packaging, independent SDI multiview video/thumbnails | Deferred |

Blueprint §7 lists acceptance criteria A01–A27, with fake-state tests for output discovery, Primary assign/release and minimum policy, persistent AUX groups, mixed routes, multiple tabs, truthful indicators, transition safety, keyers, partial outcomes, TAKE ALL, and stock WebATEM preservation. Tests should exercise real JS/backend behavior rather than only search for template strings.

## Environment and unresolved verification

- Windows 11, Python 3.12 `.venv`, PowerShell. Launch with `.\.venv\Scripts\python.exe -m webatem` and use the launcher-selected port (previously 8880). Do not assume port 8000.
- `.venv/Lib/site-packages/atemwire/_socketqueue.py` has a local Windows fix replacing unsupported `socket.MSG_DONTWAIT` with `select.select` readiness; do not rebuild/reinstall the venv or overwrite `atemwire` without preserving it. Separate patched checkout: `C:\Users\bill\Repos\bmdwire` branch `fix/windows-udp-socket`; upstream status unverified.
- Default `%LOCALAPPDATA%\WebATEM\db.sqlite3` was previously found invalid (1 byte). Do not delete a backup. A separate dev directory may be set with `$env:WEBATEM_DATA_DIR = "$env:LOCALAPPDATA\WebATEM-Dev-M1"` before launching; this has not been verified here.
- Verify stable device identity; connector-to-AUX channel mapping; M/E Program feed ID; raw transition-settings completeness; AUTO/WIPE/keyer behavior; route confirmation under external races; and multi-worker coordination. No physical validation has been performed as part of this documentation change.

**Next assistant:** Read `AGENTS.md`, this handoff, Blueprint v0.6, and ADR 0001; inspect code and working tree. Respect the operator's checkpoint approval boundary. Do not treat this planning update as authorization for 3A implementation or live-hardware commands.
