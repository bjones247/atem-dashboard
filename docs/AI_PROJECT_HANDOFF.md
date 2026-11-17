# ATEM Dashboard — AI Project Handoff

**Updated November 17, 2026.** The authoritative Milestone 3 target is [Blueprint v0.6](ATEM_Control_Dashboard_Blueprint.md), with the architectural decision in [ADR 0001](adr/0001-three-logical-switchers.md). Milestone 2.1 hardening is implemented and tested offline; no Milestone 3 implementation or physical hardware test is authorized.

## Immediate assignment and stop line

The operator separately authorized **focused Milestone 2.1 switching hardening**, offline regression tests, and a scoped commit. Review its results before authorizing checkpoint 3A. Do not connect to the physical ATEM, send hardware commands, enable TAKE ALL, or implement the redesigned interface under this authorization.

The next proposed implementation checkpoint after review is **Milestone 3A: state and persistence architecture**. Each checkpoint 3A, 3B, 3C, and 3D requires review before proceeding. Hardware validation requires separate explicit operator approval with affected destinations isolated.

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

The outgoing PROGRAM grid originally lost its live red style to later-loaded disabled-button CSS. The source filter omitted some live source types. OUT 1's CUT hover lost red; OUT 2 shares the M/E engine and should use the same readiness; OUT 3 used gray `btn-primary` styling even when ready. Milestone 2.1 adds dashboard-scoped colors, live-source fallback text, shared M/E readiness, and visible AUX disabled reasons. These are focused validation repairs; the old panel model remains superseded.

**Milestone 2.1 safety correction:** `meKeyTied` and `meInTransition` still serve informational UI only; they previously treated missing data as false, while `atemwire` can synthesize BKGD-only defaults and source ID `0`. The dashboard now projects raw M/E bus, source catalog, transition selection/position, and receive freshness through `dashboardSafety`. Its new server-side `dashboard_cut_me` command rechecks that raw state, requires background-only with no tied keyers or active transition, validates expected buses, and serializes local preflight with dispatch. `dashboard_cut_aux` validates the discovered AUX channel, directly routable target, observed live baseline, freshness, and pending state. Both use the existing pooled connection and stock dispatcher. The browser keeps uncertain timeouts blocked until hardware state changes or an operator requests read-only review; it never retries automatically. The cross-process and external-controller race between preflight and ATEM command execution remains; these guards do not make switching atomic. M3A must replace per-process pending state and the old `outNumber - 1` mapping with verified device identity, output mapping, and shared coordination before assignment features. The fixture M/E source ID `10010` is not universal authority.

The previous documentation review observed **20 passing tests**, mostly Python simulations and text checks. Milestone 2.1 adds tests of the real guard and consumer plus a Node harness exercising the actual Alpine controller. The focused dashboard and related consumer regressions passed offline; they do not establish browser rendering across themes, actual ATEM protocol behavior, or live hardware safety. An earlier Antigravity report of 92 selected passing tests was not independently verified as full-suite or hardware validation.

## Historical reference-hardware observation

During earlier validation, OUT 1 and OUT 2 both carried the **same** M/E Program feed; OUT 3 carried an independent AUX source, once labeled `MAC1 Lyrics`. This was a valid linked M/E configuration, not three independent switchers. The old plan preferred OUT 1 as the M/E control panel. In the new architecture Primary is always the M/E engine; OUT 1 may be a preferred destination but is never hardcoded or silently routed. The device's actual output count, connector mapping, and current routes must be rediscovered before any live action.

## Roadmap and review gates

| Stage | Work | Status |
|---|---|---|
| M1 | Read-only three-output foundation | Historical implementation; operator model superseded |
| M2 / 2.1 | Individual switching infrastructure and focused fail-closed hardening | Implemented and tested offline; not hardware validated; old panel model remains superseded |
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

**Next assistant:** Read `AGENTS.md`, this handoff, Blueprint v0.6, and ADR 0001; inspect code and working tree. Review Milestone 2.1's guarded dashboard command path and offline test results. The next proposed development checkpoint is 3A, subject to explicit operator authorization. Physical ATEM validation remains separately gated.
