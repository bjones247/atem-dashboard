# ADR 0001: Three logical switchers with dynamic physical outputs

**Date:** November 17, 2026

**Status:** Accepted for specification and planning; implementation pending checkpoint approval

**Supersedes:** Blueprint v0.5's three fixed physical OUT 1–3 panel model and old Milestone 3 settings/Master CUT scope

## Context

Milestone 1 and 2 presented three physical output panels. Actual reference hardware showed OUT 1 and OUT 2 both carrying the same M/E Program feed, while OUT 3 carried an independent AUX route. Two panels therefore appeared to be separate switchers but controlled one M/E engine. The fixed three-output layout also hid other discovered destinations and tied a switching workflow to connector numbers. Existing WebATEM connection management, state discovery, and command paths remain useful; the operator-facing model and assignment system need to change.

## Decision

The dashboard presents **Primary** as the actual hardware M/E 1, regardless of which outputs carry it; **AUX Switcher 1** and **AUX Switcher 2** as independent persistent logical groups that may each own zero or more physical AUX outputs; and **Other Outputs** for all remaining discovered destinations. Physical output routes remain hardware-authoritative. Primary destinations are derived from observed M/E Program feed routing; AUX group memberships are saved application configuration. Mixed AUX routing has no single live Program source and must be resolved by explicit operator action before ordinary group CUT. One M/E command controls its shared engine; AUX group actions may require one route command per physical destination.

Output assignment is an explicit, confirmed operation. Assigning Primary routes an eligible output to the discovered M/E Program feed. Releasing Primary routes the output to the current verified M/E Program **background input**, with an explicit warning that composited key overlays are lost. Missing/unroutable input or active transition blocks release. A default-on operational policy prevents dashboard removal of the final Primary destination; external zero-destination state warns but is never auto-corrected. Releasing a logical AUX output changes saved ownership only and preserves its route.

Persist per-device group assignments, queued Previews, Program targets, and preferences in revisioned backend storage. A verified hardware identity or deliberate pairing binds the configuration. Coordinate edits and pending writes across tabs. Use existing pooled WebATEM state and command paths, with backend preflight and hardware-observed confirmation. Replace the outgoing `CUT ALL` concept with **TAKE ALL**, kept disabled until checkpoint 3D and separately approved.

## Consequences and boundaries

- Milestone 1 remains historical read-only work. Milestone 2 remains the switching infrastructure foundation, but its old UI layout is superseded and has unresolved styling and fail-open transition-guard defects. Neither milestone is a claim of successful hardware validation.
- Milestone 3 is split into reviewed checkpoints: 3A state/persistence, 3B UI, 3C assignment/individual control, 3D TAKE ALL. The previous Milestone 3 settings scope moves to later work. The independent SDI video phase remains deferred.
- A saved group does not own the hardware route: external changes must be shown, never overwritten on reconnect. An externally M/E-routed group output produces an ownership conflict; the user resolves it explicitly.
- Multi-output operations are not atomic or frame-synchronous. Confirm each route and report partial or unconfirmed outcomes; never auto-retry uncertain writes.
- The reference model's connector count, source ID `10010`, and `outNumber - 1` AUX-channel mapping are not safe defaults. Discover and verify capabilities and mapping before enabling writes.
- The installed transition reader can supply safe-looking defaults when no transition packet has arrived. A distinct completeness signal and fail-closed guard are prerequisites to live M/E operations.
- Stock `/atem/control/`, the shared ATEM pool/WebSocket, Windows UDP patch, and existing WebATEM capabilities remain protected.

## Alternatives considered

Keeping three fixed physical panels would require special cases whenever two or more panels mirror one M/E and would leave additional outputs outside the dashboard. Treating each M/E-fed output as an independent switcher would issue duplicate engine commands and misrepresent hardware state. Automatically correcting saved group routes after external changes would override another operator's deliberate live action. The selected model reflects actual hardware ownership and requires explicit changes.

## Verification still needed

Confirm a stable device identifier, physical output ↔ AUX command-channel map, M/E feed ID and direct-source availability, raw transition completeness, keyer/AUTO/WIPE behavior, and cross-session command coordination. Hardware tests require isolated destinations and explicit operator approval. The detailed rules and acceptance criteria are in [Blueprint v0.6](../ATEM_Control_Dashboard_Blueprint.md).
