---
description: Historical Milestone 2 UI prompt; superseded by the three-switcher roadmap
---

> **Historical prompt, superseded November 17, 2026.** The operator chose Milestone 3: Three-Switcher Architecture and authorized documentation/planning only. Do not run this old physical-output UI implementation prompt as the current task. Read `docs/ATEM_Control_Dashboard_Blueprint.md` v0.6 and `docs/adr/0001-three-logical-switchers.md` for the active roadmap. Milestone 2 defects remain recorded in `docs/AI_PROJECT_HANDOFF.md` for reuse and safety work.

Finish Milestone 2 of this repository's WebATEM three-output dashboard. Read `AGENTS.md`, `docs/AI_PROJECT_HANDOFF.md`, and `docs/ATEM_Control_Dashboard_Blueprint.md` if present. Inspect current code and tests before proposing edits. The existing branch reportedly contains Antigravity's implementation (commit `a758e93`), but verify the checkout.

Operator-observed bugs:

1. PROGRAM rows do not show red highlighting for the ACTUAL live ATEM source on each output. Fix the authoritative state -> derived UI -> CSS/DOM binding; live highlights must work even when direct PROGRAM clicking is disabled. External hardware changes must refresh them.
2. OUT 1 CUT is red normally and turns gray on hover. Diagnose CSS and whether state changes or button is disabled; use distinct consistent enabled/hover, blocked, pending, and disabled styles.
3. OUT 2 CUT (linked M/E) and OUT 3 CUT (direct AUX) appear gray. Determine whether there is a real JS disabled predicate or unexpected missing/stale state. A valid, different queued AUX Preview and healthy connection should permit OUT 3 CUT. Linked M/E CUT must never issue duplicate commands. If a button is intentionally disabled, clearly expose the reason.
4. CUT ALL must remain disabled; it is Milestone 3.

Safety / boundaries: No physical ATEM commands or hardware tests without my explicit permission. Do not alter hardware routing, background-only M/E key-tie checks, connection-pooling, or original WebATEM interface. Avoid cosmetic fixes that mask incorrect state logic. Ensure tests use fakes/fixtures.

Please first explain likely causes and the files/functions responsible. Then implement narrow fixes, create offline regression tests for all identified issues, run focused tests, and report exact results, changed files, and remaining unknowns. Stop for review before implementing Milestone 3.
