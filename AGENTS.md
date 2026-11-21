# ATEM Dashboard — AI Agent Instructions

This repository extends **WebATEM 2.6.0** with a production dashboard for a Blackmagic **ATEM 1 M/E Constellation 4K**. Milestones 1, 2, 2.1, and 3A–3D are software-complete. The dashboard presents **Primary Switcher**, **Virtual Switcher 1**, **Virtual Switcher 2**, and Unswitched Outputs, with TAKE ALL. The pending-routing guard and key-only AUTO confirmation fixes are covered by offline regressions. The project is waiting for controlled physical ATEM acceptance testing, which requires explicit operator approval. Incorrect writes can change video on real displays. Prioritize truthful hardware state, conservative writes, and regression protection.

## Start every task here

1. Read `docs/AI_PROJECT_HANDOFF.md` for the cross-assistant handoff, current milestone, and outstanding defects.
2. Read `docs/ATEM_Control_Dashboard_Blueprint.md` if present; it is the detailed design source, subject to verified hardware behavior and user-approved later decisions.
3. Inspect the actual repository, especially `atem_control/static/js/production_dashboard.js`, `atem_control/templates/dashboard.html`, relevant `atem_control/control/` code, and dashboard tests. **Code and runtime state take precedence over any handoff summary.**
4. Before changes, report the suspected cause and a focused plan. Make narrow changes; add appropriate regression tests; report changed files, test outcomes, and risks.

## Hard safety requirements

- Never silently reconfigure ATEM hardware routing. Discover and display actual state.
- Reuse WebATEM's shared/pool-managed ATEM connection and WebSocket infrastructure; do not open a second competing UDP control connection.
- All red PROGRAM indicators reflect **authoritative current ATEM hardware state** and update on external changes, whether or not direct PROGRAM selection is enabled. A logical AUX group with mixed routes has no single live Program indicator. Green PREVIEW indicators reflect M/E hardware Preview for Primary and persisted queued Preview for each AUX group.
- An AUX virtual PREVIEW selection makes **no hardware write**. A logical AUX CUT may require one routing command per assigned physical output; track each confirmation independently. Swap a single known prior live source into queued Preview only after confirmed hardware state; never invent one for mixed prior routes.
- Physical outputs routed to M/E Program are **linked destinations** of one engine. Primary is always the actual M/E, even with zero physical Program destinations. Shared Preview, Program, keyers, and transitions issue **one M/E command, never one per destination**.
- Prefer OUT 1 as a Primary destination when appropriate, but never hardcode it or silently route it. Discover every controllable physical output and its actual assignment.
- Operator assignment changes require explicit action and observed hardware state. A verified M/E Program route takes precedence over saved virtual membership. Retire the superseded membership through a revision-checked settings update without changing the hardware route. Releasing a Primary output explicitly routes it to verified Color Bars after safety and routability checks. Releasing a logical AUX output preserves its physical route. An external ordinary source change keeps virtual membership and shows a mismatch. A deliberate CUT or TAKE ALL may align a fresh mixed group after checking each output's route and ownership.
- An M/E background CUT must not inadvertently transition upstream keyers. If next-transition includes a keyer, a transition is underway, or state is insufficient to certify safety, fail closed with a clear UI reason. Do not silently change ATEM next-transition settings to work around the guard.
- Independently control discovered USKs and DSKs by authoritative state; prevent duplicate toggles during pending operations. Failed/timed-out commands are **unconfirmed**, not proof nothing happened; reconcile with subsequent hardware state.
- If disconnected or device state is stale, disable dangerous actions. Do not optimistically claim success on command transmit.
- Do not run commands/tests that **transmit to the physical ATEM** without explicit approval from the operator. Tests should use fake/offline states by default.
- Preserve the original `/atem/control/` functionality and all existing WebATEM capabilities.
- **TAKE ALL is Milestone 3D.** Keep it fail-closed, use only the shared WebATEM connection, and preserve per-switcher confirmation. Never call the device from tests or run physical validation without explicit operator approval.

## Development environment

- Windows 11, Python 3.12 virtual environment at repo `.venv`, VS Code, PowerShell.
- Typical launch: `.\\.venv\\Scripts\\python.exe -m webatem` from repository root. Use the launcher-selected actual HTTP port (previously 8880), not an assumed 8000.
- The ATEM communication package has a local Windows fix in `.venv/Lib/site-packages/atemwire/_socketqueue.py`: replace unsupported `socket.MSG_DONTWAIT` with a `select.select` readiness check. **Do not reinstall/recreate the venv or overwrite atemwire without preserving this fix.** The fix also exists in a separate `bmdwire` Git checkout and may not yet be upstreamed.
- For separate development data, PowerShell: `$env:WEBATEM_DATA_DIR = "$env:LOCALAPPDATA\\WebATEM-Dev-M1"` before launch. On 2026-11-18, the default `%LOCALAPPDATA%\\WebATEM\\db.sqlite3` was 167,936 bytes and all migrations were applied. Verify the active `DATA_DIR` and migration state before assuming database health; preserve backups and do not delete them unprompted.
- Run focused dashboard tests before broader regressions: `.\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_production_dashboard_m1.py tests/unit/test_production_dashboard_m2.py`.

## Current task priority

**Current checkpoint: Milestone 3D software implementation complete; stop for review.** TAKE ALL coordinates Primary CUT with Virtual Switcher 1 and 2 CUTs, with all-participant preflight and independent observed confirmation. Do not weaken readiness checks, retry uncertain operations, or claim frame-synchronous behavior. Hardware validation requires explicit operator approval and isolated destinations. The configured deployment is single-worker; do not deploy multiple workers until shared notification and hardware-operation coordination are implemented. The fixed installation convention maps protocol AUX indices 0–5 to OUT 1–6 only when exactly six AUX channels are reported. Keep AUX IDs internal and show physical OUT labels. See `docs/AI_PROJECT_HANDOFF.md` and the Blueprint.

Do not infer that automated tests or hardware validation succeeded merely because a prior assistant reported a passing suite. Verify relevant claims where feasible, and clearly distinguish tests from physical hardware observations.
