# ATEM Dashboard — Copilot Workspace Instructions

Read the repository-root `AGENTS.md` and `docs/AI_PROJECT_HANDOFF.md` before planning changes. Also read `docs/ATEM_Control_Dashboard_Blueprint.md` if present. These documents carry the prior ChatGPT/Antigravity decisions; verify all assumptions against current source code.

This is a real ATEM video switcher: treat state accuracy and safe hardware writes as non-negotiable. Do not send commands to a connected physical switcher, change AUX mappings, or execute hardware integration tests without explicit operator approval. Reuse WebATEM's existing ATEM connection; preserve stock WebATEM functionality.

Current approved direction is **Milestone 3: Three-Switcher Architecture**: Primary is the hardware M/E; AUX Switchers 1 and 2 are persistent logical groups with dynamic physical output assignments; Other Outputs shows remaining discovered destinations. The old three-physical-output UI is superseded. Read Blueprint v0.6 and `docs/adr/0001-three-logical-switchers.md`. Milestone 2 switching code is reusable foundation, but its UI defects and fail-open missing-transition guard are unresolved. TAKE ALL remains disabled through 3A–3C.

The November 17 instruction authorizes **documentation and planning changes only**. Do not implement Milestone 3 code until the operator approves the next checkpoint, 3A. Before any later code change: inspect actual code and uncommitted work, explain the focused plan, use offline/fake tests, and report changed files, results, and remaining risks. Require separate operator approval before any physical ATEM command or hardware rehearsal.
