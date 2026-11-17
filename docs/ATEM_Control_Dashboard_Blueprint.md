# ATEM Control Dashboard
## Product and Technical Blueprint — Version 0.5

**Prepared:** November 16, 2026  
**Status:** WebATEM extension specification; replaces v0.4's greenfield implementation plan  
**Base application:** [WebATEM](https://github.com/lucas-romanenko/webatem), validated locally at v2.6.0  
**Protocol dependency:** [bmdwire / atemwire](https://github.com/lucas-romanenko/bmdwire), with a locally tested Windows UDP compatibility patch  
**Working project directory:** `C:\Users\bill\Repos\atem-dashboard` (verify this checkout before editing)  
**Reference device:** Blackmagic Design ATEM 1 M/E Constellation 4K; do not hard-code its current wiring or input names  
**Deployment:** Windows 11 host, browser-based UI; preserve WebATEM's supported deployment options where practical  
**Phase 1:** Existing WebATEM plus specialized three-output switching dashboard; **no new live video capture**  
**Phase 2:** Independent multiview ingest and live thumbnails (explicitly deferred)

> **Purpose:** This is the single product/technical specification for extending an already working WebATEM installation. **Preserve everything WebATEM already does; add a production-optimized view for three physical destinations.** Do not replace its UI, rewrite its protocol layer, or build a separate WPF/.NET application.
>
> **Terms:** **MUST** = Phase 1 acceptance requirement; **SHOULD** = recommended unless an inspected implementation shows a better way; **VERIFY ON DEVICE** = must be demonstrated on the actual switcher before service use; **FUTURE** = out of Phase 1. Function names and data structures below describe required behavior, not promises that the current code exposes those exact names.
>
> **Source of truth:** This document defines desired behavior. The checked-out WebATEM and bmdwire source defines existing implementation, APIs, and supported capabilities. Inspect source and tests before naming modules/functions or editing code; never invent protocol command names or hardware semantics.

---

## 0. Governing decision: extend, don't replace

WebATEM's current pages and operations remain available. The new **Production Dashboard** is an **additional view** integrated into its existing navigation/session. It may reuse or compose existing controls and render a compact view of the M/E, but must not fork independent M/E state or create a second ATEM UDP session.

### 0.1 Existing WebATEM capabilities to protect

At the WebATEM v2.6.0 baseline, preserve working behaviors including:

- Discovering and connecting to ATEM switchers; manual IP, connection status, reconnection, and pooled per-switcher sessions.
- Real M/E Program and Preview selection; CUT, AUTO, transitions, and related switching controls.
- Existing AUX routing controls, input short/long labels, hardware state feedback, and label editing.
- Upstream/downstream keyer operation and their settings, including chroma/luma/pattern/DVE where offered.
- Fairlight audio controls and metering; media pool, still thumbnails/uploads and media-player functions; macros; profiles/XML state import/export; HyperDeck transport and existing configuration screens.
- Browser-based multi-operator functionality, existing WebSocket state delivery, desktop launcher and deployment paths.

These are preservation/regression requirements, **not** additional development scope. The exact controls available on a given switcher remain device-dependent. Existing media-pool still thumbnails are **not** the deferred live multiview thumbnail feature.

### 0.2 Extension boundaries

1. Use one ATEM connection/state authority via WebATEM's existing connection pool and `bmdwire`/`atemwire` dependency. The new UI subscribes to shared state; it does not connect to the switcher separately.
2. Prefer reusing existing command dispatch, connection handling, callback/polling, source catalog, and front-end components. Add narrow capabilities only after confirming they are missing.
3. Add a new route/view for the production dashboard and a minimal amount of local configuration. Preserve the stock WebATEM switcher/control/settings pages and their URL behavior.
4. Existing pages remain authoritative for advanced switcher configuration. The custom dashboard provides a focused operating surface, not an incomplete replacement for full settings.
5. Implement changes in small, reviewable increments. Before each code change, locate existing files, state flow, command handlers, tests, and the lowest-impact integration point. Keep unrelated features untouched.
6. Keep custom features as isolated as practical for tracking upstream WebATEM updates. Document modifications and which repo owns each fix. Avoid vendoring or copying the protocol library into application source.
7. Don't auto-route outputs, rename hardware inputs, trigger a CUT, or change keyer state at startup or reconnect. Any live output-routing change requires an explicit operator action.

### 0.3 Known working baseline

- WebATEM source starts in VS Code with `.\.venv\Scripts\python.exe -m webatem` from `C:\Users\bill\Repos\atem-dashboard` and has connected to and controlled the reference ATEM.
- A verified Windows `bmdwire/atemwire/_socketqueue.py` fix avoids `socket.MSG_DONTWAIT`, which is absent on Windows. The patch resides in the user's `bmdwire` Git checkout and a working Python environment; editable install may require Microsoft C++ Build Tools to compile `atemwire.mediaconvert`.
- The prior test addresses (`192.168.1.114` for the switcher and `192.168.1.155` or `192.168.1.235` for test PCs) are **environment observations only**, never defaults in application code.
- Baseline verification before development: record Git SHA and branch, Python/package versions, resolved `atemwire._socketqueue.__file__`, test-suite result, and a non-destructive device connection smoke test.

---

## 1. Vision and scope

Extend WebATEM with a specialized operator dashboard presenting **three physical output panels**. Conceptually this is WebATEM's **existing real M/E control path plus two additional independent AUX-based Preview/Program/CUT workflows**. The output panels are tied to physical OUT 1, OUT 2, and OUT 3 for Phase 1, but their purpose and source mapping come from actual hardware and local friendly names, not hard-coded signal labels. Whichever one carries M/E Program uses real hardware Preview/Program; the other two are AUX-routed destinations with virtual Preview selections stored by the application.

The standard WebATEM control surface stays operational, including advanced features and existing settings. The Production Dashboard adds the consolidated three-panel experience, four discoverable upstream-key toggles on the M/E panel, one Master CUT, and a clear distinction between local presentation settings and deliberate hardware changes.

### 1.1 Explicit Phase 1 goals

1. Continue using WebATEM's working Ethernet connection/discovery, shared session, and state synchronization.
2. Discover actual physical/internal sources, routable output destinations, M/E state, USK/DSK state, and media-player availability through existing application/protocol structures.
3. Add a **Production Dashboard** with three managed physical panels, initially OUT 1–3. The M/E panel represents an existing WebATEM-controlled M/E; the other two panels add virtual Preview and AUX CUT behavior.
4. Support Preview, Program, and individual CUT for each panel, with state-synchronized source labels, and an operator-safe MASTER CUT.
5. Show all discovered upstream keyers (four on the reference hardware) on the M/E panel, including their current on-air state and configured fill-source name; allow independent toggles.
6. Preserve existing WebATEM input naming and advanced hardware configuration; add intentional local-friendly naming and any necessary focused settings without duplicating WebATEM's full settings pages.
7. Keep new controls synchronized with activity from the stock WebATEM view, ATEM Software Control, and the physical panel.
8. Make failure/partial-cut states visible and never misrepresent unconfirmed actions as live video truth.
9. Maintain test coverage and ensure existing WebATEM features continue to work.
10. Run Phase 1 without adding an SDI capture card, live video ingestion, FFmpeg, cloud service, or subscription.

### 1.2 Scope exclusions apply to the **new dashboard**, not existing WebATEM

- Do not add new audio, media upload, DVE, downstream-keyer settings, chroma/luma tuning, macro editing, or HyperDeck editing interfaces to the Production Dashboard. **Keep those existing WebATEM features intact and accessible.**
- Do not add a second switcher connection manager, alternate ATEM protocol client, .NET/WPF UI, or COM SDK adapter.
- No new live multiview video frames or source/program/preview thumbnails in Phase 1 (existing still-image media pool thumbnails continue to work).
- No guarantee of frame-perfect simultaneous cuts across M/E and AUX; no additional physical M/E engines.
- No new service scene automation, scheduled macros, volunteer profiles, or live/read-only permissions. These may be evaluated later; existing WebATEM macro execution is unchanged.
- No more than three *managed* physical output panels in the first version, though the implementation should make later expansion feasible.

### 1.3 Reference device capabilities (not configuration defaults)

| Capability | ATEM 1 M/E Constellation 4K reference |
|---|---|
| External inputs | 10 SDI |
| Assignable SDI outputs | 6 (Phase 1 manages OUT 1–3) |
| Hardware M/E blocks | 1 |
| Upstream keyers | 4 |
| Downstream keyers | 1 (existing WebATEM controls remain) |
| Color generators | 2 |
| Media players | 2 (verify source availability) |
| Multiview | One 16-window-capable output; future live-video ingest |
| Control | Ethernet through WebATEM/bmdwire |

This is a test fixture, not a device template. Discover real capabilities at connection and avoid assumptions about output routing, filenames, names, signal purposes, or source IDs.

---

## 2. Device-derived source and output mapping

### 2.1 Input discovery: no venue-specific baseline

**The specification intentionally contains no physical-input assignment table.** A connected ATEM is authoritative for its actual input inventory. There must be no built-in assumptions such as a particular computer, camera, lyrics feed, or signal on any numbered connector.

On connection, discover and populate the source catalog from the device:

- Physical input/source IDs, connector numbers (if exposed), source type, short name, and long name.
- Internal sources supported by the device, such as Black, color generators, and media players.
- Availability for the relevant M/E and AUX destinations.
- Names and assignments of keyer fill/key sources by joining their hardware source IDs to the same discovered source catalog.

Any examples elsewhere in this document are **illustrations only**. They are not initial configuration values and must never be automatically written to the ATEM. Input IDs, not labels or their position in a sample list, control routing. Verify actual short/long input-name constraints in the existing WebATEM validation code and on hardware; do not weaken or bypass existing checks.

### 2.2 Physical outputs and software roles

For Phase 1, the Production Dashboard displays **three panels associated with physical OUT 1, OUT 2, and OUT 3**, subject to the device supporting those routable outputs. Their purpose, names, and current source assignments are **not predetermined**.

| Physical connector | Default local heading | Dashboard role at connection |
|---|---|---|
| OUT 1 | Output 1 | Discovered from its current hardware routing |
| OUT 2 | Output 2 | Discovered from its current hardware routing |
| OUT 3 | Output 3 | Discovered from its current hardware routing |

- Internal Settings lets an operator assign a friendly name to each output; these names exist only in this app.
- Determine which configured physical outputs currently carry **M/E Program** by reading the ATEM's routing.
- Support **zero, one, or multiple** physical outputs carrying M/E Program:
  - **Single M/E output:** That panel becomes the **Hardware M/E** output; remaining panels are **Virtual AUX** outputs.
  - **Multiple M/E outputs (Mirrored/Linked):** Multiple physical outputs (e.g., OUT 1 and OUT 2) may legitimately carry the same M/E Program feed. The dashboard recognizes them as linked/mirrored destinations sharing the same underlying M/E Program, Preview, CUT behavior, and upstream keyers. One output is designated as the primary M/E control panel (defaulting to the lowest-numbered M/E output, operator-selectable locally), while other M/E-fed outputs are clearly labeled as linked/mirrored. Neither maintains an independent virtual Preview queue, because their true preview is the shared hardware M/E Preview.
  - **Zero M/E outputs:** If no configured output among OUT 1–3 carries M/E Program, all three panels operate as independent Virtual AUX destinations. The dashboard displays an informational status note, and upstream keyer status remains visible in a switcher status strip.
- Physical output routing is **never automatically changed** to satisfy the dashboard's configuration. Reassignment requires an explicit confirmed operator action.

### 2.3 Header naming rule

Each heading MUST be generated dynamically from the **saved local friendly name**, **physical output number**, and **confirmed hardware M/E assignment**:

```text
OUTPUT: <Friendly Name> (OUT 1, M/E)
OUTPUT: <Friendly Name> (OUT 2, M/E Linked)
OUTPUT: <Friendly Name> (OUT 3)
```

The example above shows the formatting when OUT 1 and OUT 2 both carry M/E Program, with OUT 1 designated as primary and OUT 2 linked/mirrored; it is **not a hardcoded assignment**. If only OUT 2 carries M/E Program, the suffixes are `(OUT 1)`, `(OUT 2, M/E)`, and `(OUT 3)`. On a clean install, local friendly names start as `Output 1`, `Output 2`, and `Output 3` until the user names them.

---

## 3. Functional architecture

### 3.1 Logical signal plan

```text
                         EXISTING WEBATEM
    Browser UI  <---->  Django / WebSockets / shared state
                                  |
                     Existing command dispatch / pool
                                  |
                      bmdwire / atemwire over UDP
                                  |
                       ATEM: discovered inputs
                         /                  \
              Native hardware M/E       AUX destinations
              Program + Preview       OUT 1 / OUT 2 / OUT 3
                   |                    as hardware supports
              USK 1..N                       |
                   |              Two software-held Previews
                   +----------+-------------+
                              |
                    Production Dashboard
                1 M/E panel + 2 virtual AUX panels
                         + Master CUT
```

- This is **one shared switcher session**, not three independent ATEM connections.
- Managed dashboard panels mirror discovered hardware routing: physical outputs routed to M/E Program share genuine hardware M/E state, Preview, and upstream keyers. When multiple outputs mirror M/E Program, one is designated primary control while others reflect linked status without duplicate commands.
- Physical outputs routed to independent sources represent direct routable AUX destinations, with independent Preview in server/application state rather than physical ATEM Preview buses.
- Do not accidentally alter an upstream key's on-air state during dashboard background CUT. Verify interaction with ATEM next-transition/tie selection on hardware.
- Master CUT is best-effort and command-deduplicated: it issues at most one M/E command for the shared M/E engine, plus individual commands for genuine AUX destinations; report per-destination outcomes accurately.

### 3.2 Existing stack, reused services, and extension layers

```text
Existing WebATEM pages         New Production Dashboard page
         |                               |
         +-------- existing browser UI / JS --------+
                           | WebSocket / API
                  atem_control (Django app)
                  state, command dispatch, consumer
                           |
               existing connection pool / bmdwire
                           |
                     physical ATEM

Separate new modules only where required:
  - Virtual Preview storage keyed by switcher + output + operator/session
  - Output/panel mapping and transition coordination
  - Focused local UI preferences
  - Master CUT validation and per-output outcome reporting
  - Regression tests for existing features and new operations
```

**Actual repository landmarks to inspect (not mandates to duplicate):** `atem_control/` holds the Django app, WebSocket consumer, command dispatch, discovery and UI; `webatem/` contains the project, settings and launcher; `tests/` contains existing hardware-free tests; `bmdwire` supplies `atemwire`. `pyproject.toml`, `requirements.txt` and `package.json` define dependencies/build steps. These are documented upstream; examine this checkout for exact function names and paths before implementing.

**Preferred stack:** Existing Python/Django/Channels/Uvicorn, WebSocket-based live state, and the current JavaScript/templates/styles. Reuse the existing persistence mechanism (SQLite is already used for connection history) where appropriate; use separate local preferences for dashboard-only fields if a simple, safe fit exists. No new Python framework, SPA rewrite, COM wrapper, separate server, or standalone Windows UI should be introduced without a compelling documented reason.

### 3.3 Cross-view state and command coordination

1. The actual ATEM state is authoritative for M/E and AUX live routes; the existing connection pool remains the only protocol owner.
2. The dashboard obtains real-time state through WebATEM's existing mechanism. It must not start competing pollers when the current system already publishes the needed fields.
3. Virtual AUX Preview is a separate application concept. It must be isolated from real hardware M/E Preview and never written to the ATEM until an operator executes CUT.
4. Scope virtual Preview safely. The implementation must explicitly define whether it is per browser/operator session or shared per dashboard instance. **Phase 1 default: per operator session**, with an explicit warning that two operators can queue different Next sources for the same AUX; only the first actual hardware CUT is live. Revalidate immediately before execution.
5. Route writes through established command authorization/validation/error handling, then reconcile with actual hardware state before marking ON AIR.
6. Reuse existing UI components/branding where practical; a production-specific layout is allowed, but no existing screen may disappear.
7. Keep data capture/transport boundaries independent of any future video system. Phase 1 outputs source IDs and state; Phase 2 may attach images by matching those IDs.

### 3.4 Implementation decisions to record after code inspection

Before implementation, document exactly which existing classes/functions supply: source catalog and labels; AUX read/write; M/E Program/Preview and CUT; keyer read/toggle; output route identity; WebSocket push/poll; connection pool; persistence; and per-command response/result handling. If a needed property is absent, identify the narrowest extension in `atem_control` or `bmdwire` and add a focused test. Avoid guessing command codes or assuming all outputs can be controlled by the same API.

---

## 4. Screens and navigation

Two **new-dashboard-level destinations** are required, in addition to all stock WebATEM pages:

1. **Production Dashboard** — the new three-output surface with focused switching and keyer operations.
2. **Production Dashboard Settings** — local preferences and, if needed, a deliberate hardware-change workflow. Reuse/link to existing WebATEM Settings for advanced switcher controls rather than replicating them.

The new dashboard's persistent top status bar MUST show: application name, current ATEM connection state, device model or display name, IP address, active screen, and an unmistakable warning if disconnected or configuration is inconsistent.

### 4.1 Dashboard: desktop wireframe

Target a 1920×1080 Windows control laptop/display. Adapt gracefully to smaller windows by scrolling or stacking panels without rearranging source identity unexpectedly.

```text
+--------------------------------------------------------------------------+
| PRODUCTION DASHBOARD | <Device model> @ <ATEM IP> | CONNECTED | Settings |
+----------------------+----------------------+----------------------------+
| OUTPUT: Output 1     | OUTPUT: Output 2     | OUTPUT: Output 3           |
| (OUT 1)              | (OUT 2, M/E)*        | (OUT 3)                    |
| ON AIR: <source>     | ON AIR: <source>     | ON AIR: <source>           |
| NEXT:   <source>     | NEXT:   <source>     | NEXT:   <source>           |
|                      |                      |                            |
| PREVIEW (green)      | PREVIEW (green)      | PREVIEW (green)            |
| [discovered sources] | [discovered sources] | [discovered sources]       |
|                      |                      |                            |
| PROGRAM (red)        | PROGRAM (red)        | PROGRAM (red)              |
| [discovered sources] | [discovered sources] | [discovered sources]       |
|                      |                      |                            |
| [   CUT OUT 1    ]   | [   CUT OUT 2    ]   | [   CUT OUT 3    ]         |
|                      |                      |                            |
|                      | UPSTREAM KEYERS*     |                            |
|                      | [discovered keys]    |                            |
|                      | fill names & status  |                            |
+----------------------+----------------------+----------------------------+
| MASTER CUT Safety: [Persistent slider]         [  CUT ALL OUTPUTS  ]   |
+--------------------------------------------------------------------------+
```

`*` Illustrative placement only: the keyer strip and M/E suffix belong to **whichever output currently carries M/E Program**, not permanently to OUT 2. Names and source buttons come from device discovery and local preferences, not sample values.

This is a schematic, not a visual design mandate. Source-grid size and the number of keyer controls must adapt to the discovered device.

### 4.2 Dashboard source buttons

Available categories in desired order:

1. **All discovered physical inputs** (in connector order where supported)
2. **BLK**
3. **COL1** and **COL2**
4. **MP1** and **MP2**

Each selectable source MUST have a stable **ATEM input/source ID** independent of its displayed name. The UI should use the actual ATEM short or long label, with a user option for display style. Defaults: long names where space permits; number plus short name for compact buttons. Tooltips can expose long name and source category.

Do not infer input availability from a name or from whether a cable is connected. Query source availability for the particular M/E or AUX destination. Unsupported selections are hidden or disabled with an explanation. Color generators remain available even if their color settings have not been customized; empty media players may be hidden through an internal preference. Default Phase 1 behavior: show all supported source types; disable a known unusable player rather than silently removing a familiar button during the show.

- **PREVIEW row:** selecting a source queues it. Green selection means *next*; on virtual outputs it is software-only.
- **PROGRAM row:** red selection means the hardware-confirmed live source. Behavior is determined by **Program Selection Mode**, not the physical switcher's own global preference.
- The colored state should also have text (ON AIR / NEXT) so operators are not dependent on color alone.
- Button labels update if another operator renames the input in ATEM Software Control.
- If a source ID disappears or becomes unavailable, mark it unavailable and disable its selection; never silently substitute a different source.

### 4.3 Program Selection Mode (Internal Setting)

| Mode | PREVIEW click | PROGRAM click | CUT click |
|---|---|---|---|
| **Direct** | Selects next source | Immediately switches that output live | Transitions to queued preview |
| **Preview + CUT Only** | Selects next source | Indicator only; no click action | Required to change the live source |

**Default: Preview + CUT Only.** This is **unique to our Production Dashboard**, not an ATEM-wide lockout. External ATEM Software Control or physical-panel operations remain unrestricted. The setting persists across app restarts and applies to all three output panels.

### 4.4 Upstream keyer strip

The **compact keyer strip** displays discovered upstream keyers on the designated primary M/E panel (or in a persistent switcher status section if no managed output currently routes M/E Program). All existing WebATEM keyer configuration/control screens remain available:

```text
UPSTREAM KEYERS (<discovered count>)
[KEY 1 | <fill-source name> | ON AIR]
[KEY 2 | <fill-source name> | OFF]
... one control per discovered upstream keyer
```

- Enumerate available upstream keyers; do not assume there will always be exactly four on future devices.
- A keyer button is a **live on-air toggle** and routes its command through WebATEM's existing keyer-control dispatch; verify the actual bmdwire API/command before calling it.
- Show the actual current state (`ON AIR`, `OFF`, `PENDING`, `ERROR`) using the same shared ATEM feedback as existing WebATEM keyer controls.
- Show the keyer's **fill source** name (from the ATEM input catalog) beneath the key number. The key/cut source, if different, may be available in tooltip/details; don't confuse it with fill.
- Updates to keyer fill source assignments made in ATEM Software Control must change the displayed name automatically.
- Key configuration (chroma color, clip/gain, masks, pattern, etc.) remains in ATEM Software Control; read if discoverable, but do not edit in Phase 1.
- If multiple outputs carry M/E Program, the keyer strip resides on the designated primary M/E panel, reflecting shared keyer status across all linked outputs.
- If M/E ownership changes to a different output, the keyer strip follows the **new primary M/E panel**, not the old physical connector.
- Downstream keyers are discovered, but Phase 1 does not surface control buttons for them.

### 4.5 Master CUT

- One prominent **CUT ALL OUTPUTS** button.
- Command target: each output's current Preview selection.
- Deduplication: When multiple outputs carry M/E Program (mirrored outputs), Master CUT issues **exactly one** hardware M/E background CUT command for that shared engine. It never sends duplicate M/E CUT commands for linked outputs.
- Virtual outputs: set each assigned AUX's live source to its queued Preview source.
- The application must **pre-validate all three destinations** before starting. If any output is disconnected, unconfigured, invalid, or in a conflicting hardware state, do not attempt an all-output transition. Show the reason.
- Switching commands execute as closely together as practical but are **not guaranteed frame-synchronous**.
- A partially successful command must be reported accurately. Do not pretend to roll back physical video switching; resynchronize to the actual hardware state.

**Master safety slider:** A persistent on-screen slider, not a momentary ARM button that resets after every action. Recommended initial design: `PROTECTED` prompts before each master action; `INSTANT` executes on click. Store the selected mode locally. This is a UX decision that should be tested with operators before final styling. Either way, the slider stays in the chosen state until changed.

### 4.6 Dashboard live status behavior

- Connection lost: immediately disable live controls and show the last observed state as **STALE / DISCONNECTED**, not current truth.
- Command pending: show a brief pending indicator; ignore rapid repeated commands targeting the same bank until state is reconciled.
- Command rejected/time-out: display a concise error, query the device state, and correct the UI.
- Changes from ATEM Software Control or the chassis: update the affected red/green selections and key statuses automatically.
- M/E Program display represents the M/E background source plus separate keyer status; do **not** suggest that the input label alone fully describes the keyed composite.

### 4.7 Preservation and navigation rules

- Add a clearly labeled Production Dashboard navigation entry; preserve existing switching, audio, keyer, media, macros, settings, profiles, and HyperDeck navigation and routes.
- The new M/E panel may be a compact representation of WebATEM's existing M/E controls, but **must use the same hardware state and command path**, not create a new independent M/E.
- Changes from the dashboard appear on standard WebATEM controls; changes from the standard view update the dashboard.
- Existing browser behavior, responsive layout, keyboard interactions, and server launcher should not be broken by the new page. Avoid changing shared CSS or JavaScript globally without regression tests.
- No new live-thumbnail placeholders that could be mistaken for usable Preview video in Phase 1. Text source names and ON AIR/NEXT are sufficient.


## 5. Settings screen

Within the new dashboard, distinguish **Internal Settings** from changes to the physical switcher. Prefer linking to the **existing WebATEM Settings** page for all features it already supports. If a focused dashboard ATEM Settings panel is added, it must reuse the existing command/update path and keep separate staging/confirmation rules. Do not implement a second general-purpose settings system.

### 5.1 Internal Settings — `SAVE`

These dashboard-specific settings belong to our extension and **must not** send configuration updates to the ATEM.

| Setting | Type / behavior | Phase 1 default |
|---|---|---|
| ATEM IPv4/host address | **Reuse existing WebATEM connection/recent-device storage**; do not duplicate unless needed for per-dashboard preferences | Use selected WebATEM connection |
| Automatically reconnect | **Reuse existing WebATEM behavior** | Existing behavior |
| Remember device | **Reuse existing WebATEM behavior** | Existing behavior |
| Local friendly output name | One per output | Output 1, Output 2, Output 3 |
| Output display order | Ordered list | OUT 1, OUT 2, OUT 3 |
| Button label style | Short / Long / Both | Both where space allows |
| Source visibility | Per source ID/category | Supported sources shown |
| Source ordering | Sort/order preferences | Physical inputs then internal sources |
| Program Selection Mode | Direct / Preview + CUT Only | Preview + CUT Only |
| Master CUT Safety | Protected / Instant | Protected |
| Hide empty media player sources | Boolean | Off (disable unusable) |

**SAVE contract:** Validate all local fields; persist them through a suitable local mechanism consistent with WebATEM (SQLite or versioned application-local JSON after inspection); write atomically and preserve backwards compatibility; update the dashboard immediately for local-only names and presentation preferences. Display `Saved` or a specific error.

WebATEM already owns connection selection and history. The dashboard must reuse its selected connection and must not silently replace or bypass WebATEM's own remembered-device semantics.

### 5.2 ATEM Settings — `UPDATE ATEM`

These are hardware changes. Reuse the existing WebATEM settings workflow for input names and AUX routing where already supported. Add a narrowly scoped staged **UPDATE ATEM** transaction only if needed for new composite operations, especially reassignment of the managed M/E output. Nothing in this table authorizes automatic writes.

| Editable field | Source of initial value | Commit effect |
|---|---|---|
| Input short name | ATEM | Uses WebATEM's existing rename command and its verified length/character validation |
| Input long name | ATEM | Uses WebATEM's existing rename command and validation |
| M/E Program destination among OUT 1–3 | Observed OUT source routing | Updates affected AUX source assignments |
| Physical output source mapping / initial assignment | Current hardware output routes | Changes hardware routing when explicitly committed |

Read-only information in this tab may include model, video mode, all discovered inputs, USK/DSK status and configuration, media player assignments, color sources, and output source mapping.

**UPDATE ATEM contract:**

1. When opening the tab, capture a baseline snapshot of editable hardware fields.
2. User edits fields in a **staging buffer**. Do **not** alter hardware yet.
3. Show a **Changes to ATEM** diff: old value → proposed value; clearly identify any change that might affect an on-air output.
4. Before committing, re-read the latest hardware values. If an edited field has changed externally since staging, **block that field**, show the conflict, and require reload/review. Unedited fields must never be written back.
5. Ask for explicit confirmation for output-routing changes (they may affect screens immediately).
6. Apply only validated changes, recording per-field success/failure; multiple ATEM commands cannot necessarily be applied atomically.
7. Re-query authoritative ATEM state, update the UI, and show an accurate outcome, including partial success.
8. Never attempt a silent hardware rollback or restore a stale full-switcher snapshot after a failure.

**M/E reassignment nuance:** If the user reassigns M/E Program from one managed output to another, the formerly M/E-fed output needs a direct source assignment. The confirmation must show **both** affected outputs and explicit resulting routes. Do not guess what should replace M/E Program on the old output. Permit cancellation without any hardware change. This operation is not guaranteed to be frame-atomic.

**Physical output count in Phase 1:** The new dashboard UI is restricted to three panels tied to OUT 1, OUT 2, and OUT 3. Its implementation SHOULD permit later expansion without replacing existing WebATEM outputs/settings.

### 5.3 Connection and discovery information

After connection, display a discoverable **Device Information** section (read-only):

- Product/model name, reachable IP, firmware/version information **when exposed**.
- Available external inputs, input IDs, short/long names, port type, and source availability.
- Available routable physical outputs and current assignments.
- M/E blocks, current Program/Preview, transition state and next-transition selection (if exposed).
- USK and DSK count, current types, fill/key source IDs, on-air state, and key settings where available.
- Media player count, current still/clip assignment and metadata where available.
- Color generator sources and relevant values where available.
- Other discovered capabilities only for diagnostic visibility, without Phase 1 edit controls.

**Do not promise a complete clone of all ATEM software settings.** The requirement is to retrieve and display *all relevant settings exposed and supported by the existing WebATEM/bmdwire implementation*. Mark unsupported/unknown fields as such rather than fabricating defaults.

---

### 5.4 Avoid unnecessary settings duplication

Inventory current WebATEM controls and configuration before building the new Settings view. Provide a link, contextual route, or reuse of the existing controls when the feature already exists. Only custom output-friendly names, dashboard display preferences, virtual Preview behavior, safe managed-output selection, and Master CUT safety are inherently new. Where the original specification says UPDATE ATEM, the essential contract is *review before hardware write*, not a mandate to create a second input-renaming system.


## 6. Domain model and state ownership

### 6.1 Required conceptual models

```text
AtemDevice
  deviceId / model / ip / connected / capabilitySnapshot

AtemSource
  sourceId (hardware ID, stable) / physicalInputNumber? / type
  shortName / longName / availableForME / availableForAux
  currentlyUsable / displayOrder / visibility

PhysicalOutput
  outputId / connectorNumber / observedHardwareSourceId

OutputPanel
  panelId / physicalOutputId / localFriendlyName
  role = VirtualAux | HardwareME
  onAirSourceId (derived from hardware)
  queuedPreviewSourceId (hardware ME or local virtual selection)
  controlState (Ready | Pending | OutOfSync | Disconnected)

UpstreamKey
  keyId / type / fillSourceId / cutSourceId / onAir

MediaPlayer
  playerId / fillSourceId / assignedContent / contentAvailable

LocalSettings
  deviceAddress / outputNames / sourceVisibility / labelStyle
  programSelectionMode / masterSafetyMode / reconnectPreference

StagedAtemChanges
  initialHardwareBaseline / editedFields / conflictList
```

These are conceptual Python/web state models; reuse the equivalent existing WebATEM types wherever available. Names and fields are illustrative, not prescriptions for duplicate objects.

### 6.2 Single source of truth

| Data | Owner |
|---|---|
| Input names, physical source IDs | ATEM |
| Current AUX routes | ATEM |
| Real M/E Program and Preview | ATEM |
| Upstream key configuration and on-air states | ATEM |
| Local output friendly names | Application settings |
| Source button visibility and order | Application settings |
| Virtual AUX Preview selection | Dashboard state (explicitly scoped to operator/session) |
| Master safety, Program Selection Mode | Application settings |
| Unsaved hardware edits | Temporary ATEM Settings staging buffer |

**Never conflate an optimistic UI update with confirmed hardware state.** Keep commands and state updates separate.

### 6.3 Source identity and label formatting

- ATEM source IDs, not displayed names, are routing identifiers.
- Labels must be generated dynamically by joining source IDs to the latest source catalog.
- Input names may be blank, duplicated, changed elsewhere, or shortened; always show an input number/ID alongside any potentially ambiguous name.
- Suggested label fallback: `IN 3`, `COL 1`, `MP 1`, or `Source <ID>` if no name exists.
- Changing a name should never change any routing assignment.

---

### 6.4 Integration ownership additions

| Data / operation | Owner |
|---|---|
| UDP connection, reconnection, packet protocol | Existing WebATEM/bmdwire connection manager |
| Source catalog, labels, M/E state, keyer state, AUX routes | Existing WebATEM shared hardware state |
| Existing audio, media, macros, profiles, HyperDeck | Existing WebATEM modules, unchanged |
| Two AUX Preview queues | New dashboard-specific state, explicitly scoped |
| Managed OUT 1–3 panel choices and local names | New dashboard preferences (without duplicating connection history) |
| CUT ALL validation/outcomes | New dashboard coordinator calling existing command path |
| Live video frames / thumbnail ingest | Phase 2 independent subsystem, no Phase 1 dependency |


## 7. State synchronization and startup rules

### 7.1 Connection sequence

1. Launch app; load existing WebATEM session and dashboard-specific preferences.
2. If auto-reconnect is enabled and an address was saved, connect; otherwise show Connect screen/status.
3. Use existing WebATEM/bmdwire connection through selected IP; verify that the switcher is responsive.
4. Discover capabilities, input catalog, output routes, M/E state, keyer state, and media player metadata.
5. Identify which of physical OUT 1–3 currently route M/E Program. Support zero, one, or multiple M/E-routed outputs cleanly without guessing or treating multiple outputs as an error. If multiple outputs route M/E Program, designate one primary panel and label linked/mirrored outputs accordingly.
6. Initialize each virtual output's live source from the actual AUX assignment.
7. Initialize Preview: for M/E-fed outputs, reflect the authoritative hardware M/E Preview; for virtual AUX outputs, revalidate queued selection conservatively (if a valid selection exists in operator session state for this output and source is available, restore as queued; otherwise default to current live source so CUT is a no-op until an explicit choice is made).
8. Subscribe to WebATEM's existing state broadcasts, callbacks/polling, and WebSocket events for relevant source, route, M/E and keyer changes; add only missing state propagation.
9. Only enable live dashboard controls once the relevant device snapshot is consistent and current.

Never issue ATEM routing commands automatically just because the app started or reconnected.

### 7.2 External changes

- A source name changes outside the app: update button labels immediately.
- An AUX route changes externally: update that output's red ON AIR selection and re-evaluate whether it carries M/E Program or independent AUX. If it switched to M/E Program, sync its Preview to hardware M/E Preview; if it switched to AUX, restore or initialize its independent virtual Preview.
- The M/E Preview or Program changes externally: update all M/E-fed panels (primary and linked/mirrored) from hardware simultaneously.
- Upstream keyer fill source or on-air state changes externally: update key buttons and labels.
- A source is removed, disabled, or becomes unavailable: disable pending actions referencing it, without silently replacing it.

### 7.3 Disconnection and recovery

- Upon disconnect: disable all live switching, mark confirmed values **last observed**, retain local settings, and log the reason.
- Retry connection with bounded backoff; do not flood the device/network.
- On reconnect: re-discover and re-read all hardware state rather than replaying cached commands.
- Never automatically reapply old hardware output assignments or input names.
- Preserve valid virtual Preview choices only when doing so is safe, for the same hardware/connector, and visibly label them queued.
- If another controller changed routing while disconnected, display the changed state rather than trying to force the previous state back.

### 7.4 Multi-operator semantics

WebATEM supports multiple browser operators sharing one switcher session. The new dashboard must not assume only one browser is connected. Virtual Preview should default to per-operator/session state so one operator's queued Next choice does not silently replace another's. Actual AUX Program state is global hardware state and must update for everyone. Before every CUT, revalidate current AUX route, Preview target, source availability, and pending operations. Show an out-of-sync indicator if another operator changed the live destination during the operator's sequence. Document whether the session survives page refresh; never share Preview via an implicitly global Python variable.


## 8. Switching rules (normative)

### 8.1 Definitions

- **Live**: confirmed source feeding a virtual-output AUX, or the confirmed M/E background Program source for the M/E panel.
- **Next**: Preview source. Hardware-owned on the M/E panel; locally held for virtual panels.
- **CUT**: take Next to Live. On the M/E, send a native CUT with keyers unaffected by the dashboard's background transition. On virtual panels, set AUX source to Next.
- **Swap after CUT**: once successful, the formerly live source becomes Next, enabling the next CUT to toggle back. On the M/E panel, use the actual post-cut Program/Preview reported by ATEM instead of assuming its internal state.

### 8.2 Virtual AUX output: Preview

```text
SelectPreview(panel, sourceId):
  assert connected, configured, source allowed for this AUX
  set panel.queuedPreviewSourceId = sourceId     // local only
  render green preview indicator
  do not send any hardware routing command
```

### 8.3 Virtual AUX output: Program and CUT

```text
SelectProgramDirect(panel, sourceId):
  assert ProgramSelectionMode == Direct
  assert connected + source allowed
  dispatch the existing WebATEM AUX-source command for this output/source ID
  wait for device confirmation / updated route
  set live state from actual device route
  leave queued Preview unchanged unless now invalid

CutVirtual(panel):
  assert connected + configured + preview valid
  previousLive = observed AUX source ID
  target = queuedPreviewSourceId
  if target == previousLive: no-op with clear UI feedback
  command AUX.SetInputSource(target)
  wait for confirmed observed AUX source == target
  on success: queuedPreviewSourceId = previousLive
  on failure: re-read actual route; don't invent a swap
```

Do not use a generic “toggle back to last source” mechanism that bypasses the Preview row. The operator's current Preview choice is the target.

### 8.4 Real M/E output: Preview, Program, and CUT

```text
SelectPreviewME(sourceId):
  dispatch the existing WebATEM M/E Preview command
  show selection only after device acknowledgement / callback

SelectProgramDirectME(sourceId):
  only when Direct mode
  dispatch the existing WebATEM M/E Program command
  resynchronize ME Program/Preview from hardware

CutME():
  ensure expected ME is the one assigned to this panel
  verify transition/next-transition state permits background-only CUT
  dispatch the existing WebATEM M/E CUT with verified background-only next-transition selection
  read confirmed ME Program/Preview and keyer on-air status
```

**Critical hardware acceptance condition:** Blackmagic's *next-transition* selections can tie upstream keys to a transition. The dashboard's ordinary M/E CUT is intended to transition the **background only**, leaving all discovered USK on-air states unchanged. During the hardware spike, inspect and test the correct WebATEM/bmdwire command sequence for ensuring `BKGD-only` next-transition selection; perform it safely and avoid overwriting simultaneous changes made by another operator. If this cannot be done reliably, Phase 1 must warn/block rather than silently turning keys on/off. Do not simply assume that issuing a CUT can never affect keyers. See [S7](#references-and-validation-sources).

### 8.5 Upstream key toggle

```text
ToggleUSK(keyId):
  ensure connected, currently assigned to this M/E, not pending
  desired = !observedOnAir
  dispatch the existing WebATEM USK on-air command
  wait for Key.GetOnAir()/callback confirmation
  on error: re-read state, show failure
```

Use WebATEM's existing keyer read/write and source-label mapping; inspect the corresponding bmdwire fields before adding any missing method. See [S1] and [S2](#references-and-validation-sources).

### 8.6 Master CUT

```text
CutAll():
  ensure connected, no unresolved output conflict, all three previews valid
  apply persistent safety setting (PROTECTED confirmation or INSTANT)
  capture target Preview IDs and observed live IDs for all panels
  dispatch at most one ME background CUT (if one or more outputs carry M/E Program)
  plus independent virtual AUX routes for outputs routed to AUX (deduplicating mirrored M/E destinations)
  using the discovered assignments (not fixed output numbers)
  dispatch in tight sequence without unnecessary UI waits between commands
  collect independent confirmations for each output
  if all succeed: update virtual Preview swap states + ME observed state
  if partial failure: show which outputs changed and which did not;
                      refresh all output states; do not auto-rollback
```

**Timing requirement:** Favor a responsive, consistent command path but do **not** claim simultaneous frame-boundary cuts. Do not issue racing or unsequenced writes through shared connection/command state; respect existing WebATEM synchronization and command dispatch rules. Document measured switching skew in the hardware integration tests.

---

### 8.7 Command integration contract

All Phase 1 actions MUST pass through the same WebATEM command transport/validation path used by standard pages. Model each action as an intentional command with a destination, source ID or key ID, pending status, expected response, and timeout/reconciliation behavior. A web UI state change is not evidence of physical success. Use existing state payloads and subscription mechanisms rather than another UDP socket or high-frequency polling thread. Commands that span multiple physical destinations must explicitly return **per-destination** outcomes, including partial success.


## 9. WebATEM integration contract and implementation guidance

**This replaces the v0.4 proposal for a WPF/C# application using the Blackmagic COM SDK.** The product already works through WebATEM's Python stack and `bmdwire` protocol layer. The Blackmagic SDK manual can inform hardware semantics but is not the Phase 1 API contract.

### 9.1 Inspect existing code first

Before writing a feature, trace the relevant path end-to-end:

1. HTML/template and JavaScript event for the matching stock WebATEM control.
2. Existing WebSocket/HTTP entry point and command-dispatch registration.
3. Shared switcher session/pool and current state structures.
4. bmdwire/atemwire protocol call only if needed to discover a missing capability.
5. Existing browser update / feedback message after hardware confirmation.
6. Corresponding tests (including fake-protocol tests) and operator-visible error behavior.

Document the actual symbols and file paths in a short architecture note, `docs/webatem-extension-map.md`. Never infer method names from v0.4 SDK pseudocode or add a parallel integration simply because it looks easier.

### 9.2 Required extension operations (conceptual)

| Desired operation | Preferred implementation |
|---|---|
| Connect, reconnect, discover switcher | Reuse WebATEM's launcher, selected switcher and pooled session |
| Read source catalog and names | Reuse existing state snapshots, renaming and UI label mapping |
| Read and route physical AUX | Reuse existing AUX state/command; verify mapping to physical OUT 1–3 |
| Read/set M/E Preview and Program | Reuse existing M/E state/commands |
| Native CUT of M/E background | Reuse existing CUT command, with additional next-transition safety check |
| USK count, fill IDs/names, on-air toggle | Reuse existing keyer state/commands |
| Master CUT | New coordinator that validates then invokes existing per-output commands |
| Virtual AUX Preview | New software-only state, not an ATEM protocol command |
| Local friendly labels and safety preference | New settings only if no existing appropriate model/storage |
| External changes and command results | Existing WebSocket/poll notifications plus minimal missing fields |

### 9.3 Suggested *additive* repository footprint

This is illustrative; place files according to the **actual** existing tree and conventions:

```text
atem-dashboard/                  # existing WebATEM-derived working tree
  atem_control/                  # preserve existing WebATEM application
    ... existing modules ...
    ... small added dashboard view/route/template/JS modules ...
  webatem/                       # preserve server and launcher
  tests/
    ... existing tests ...
    test_production_dashboard_*.py  # focused new unit/regression tests
  docs/
    ATEM_Control_Dashboard_Blueprint.md  # this document
    Antigravity_Opening_Prompt.md
    webatem-extension-map.md     # exact integration points verified in source
    hardware-verification.md     # observed reference device behavior
  .venv/                         # local only; never commit

bmdwire/                         # separate repository/patch ownership
  atemwire/_socketqueue.py       # Windows select()-based fix
```

Do not change `bmdwire` to implement the dashboard unless a necessary public protocol capability is genuinely absent. If the underlying protocol does need a fix, make it in `bmdwire`, test there, and manage dependencies explicitly. Keep the Python environment's patch provenance visible; pip reinstalling packages may replace an uncommitted site-packages modification.

### 9.4 Developer workflow (tested launch path)

From the current working project root in VS Code / PowerShell:

```powershell
cd C:\Users\bill\Repos\atem-dashboard
.\.venv\Scripts\python.exe -m webatem
```

The GUI normally uses port `8880` unless configured otherwise in the launcher. Stop the process before editing/reinstalling dependencies or starting another copy.

For dependency/bootstrap changes, follow the checked-out README and package configuration (upstream documents `npm install`, `npm run build:css`, editable Python install and `python -m pytest tests/ -q`). Avoid wholesale reinstalling `.venv` without confirming the Windows-compatible `bmdwire` is retained. A local editable `bmdwire` install may require MSVC C++ Build Tools because its extension modules compile on Windows.

### 9.5 Testing strategy and change discipline

- Run the existing WebATEM test suite before code changes and after each milestone; record unrelated baseline failures separately.
- Add unit tests for state transitions and virtual Preview/CUT; backend fake-protocol tests for emitted AUX/M/E/key commands; front-end interaction tests or equivalent checks for view and label consistency; and regression checks for stock WebATEM pages/routes.
- Ensure all device-write tests use fakes by default. Real hardware testing must be a deliberately invoked smoke test with operator consent, visible destination, and documented expected results.
- Use small commits. Prefer a new module/route to invasive changes in existing shared templates or dispatch code. Preserve upgradeability with a list of touched upstream files.
- Maintain license/attribution and any derivative-distribution obligations for WebATEM and its LGPL protocol dependency.

---

## 10. Nonfunctional requirements

### 10.1 Live-production reliability

- No live command while disconnected, in an unresolved conflict, or with an invalid/unavailable source.
- Serialize or coordinate commands for the same output; suppress rapid double-click replays. Keep M/E and AUX operations safe under multi-operator activity.
- Use existing WebATEM connection/session lifecycle and state delivery rather than a parallel polling or UDP implementation.
- A failed command must not leave green/red UI indicators claiming confirmed hardware state. Clearly show PENDING, ERROR and STALE.
- Preserve upstream key state during background CUT. Test next-transition/tie cases on hardware; if safe behavior cannot be guaranteed, block the dashboard CUT and explain.
- Reconcile all outputs after partial Master CUT; don't attempt unrequested automatic rollback.
- No automatic output routing or hardware renaming on startup, page load, connection or reconnection.

### 10.2 Usability and preservation

- Browser UI with Windows 11 operator laptop as initial target, keyboard/mouse first, touch-friendly sizing where feasible. Preserve WebATEM's existing responsive browser experience.
- Dark operator-friendly surface; red means confirmed ON AIR and green means NEXT, with textual state labels.
- Stable button layout and source identity; no live reshuffling because a source becomes temporarily unavailable.
- Existing WebATEM navigation, templates, switching, keyers, audio, media, macros, profiles, HyperDeck and settings remain available.
- Clearly distinguish local SAVE from confirmed hardware write/UPDATE ATEM. Avoid competing settings that disagree between pages.
- Local operator must be able to run without internet, cloud accounts or subscriptions. Do not assume browser is restricted to localhost if WebATEM's existing network serving is enabled.

### 10.3 Responsiveness and diagnostics

- Click feedback should be immediate but must be visually different from confirmed ATEM state.
- Keep using WebATEM's existing WebSocket fan-out and state update rates; don't add wasteful duplicate device polling.
- Log connection state, queued vs. live selections, command destination/source IDs, pending/completed states, individual results and failures. Do not flood logs with media data or unrelated operator information.
- Measure Master CUT skew on the reference device; describe it as best effort rather than frame-synchronous.

### 10.4 Security and maintenance

- Reuse existing WebATEM host/interface and WebSocket origin controls. Do not weaken authentication/access assumptions or expose an additional unaudited control API.
- Remember WebATEM is a trusted-LAN control surface, not a permission-separated system; the new dashboard's `Preview + CUT Only` setting is a UI workflow, not an ATEM-wide lockout.
- Do not ship secrets or `.venv` inside Git. Keep source libraries in their proper repos and document reproducible environment setup.
- Track upstream WebATEM version/commit, `bmdwire` commit or release, and locally applied fixes so updates can be tested and merged safely.

---

## 11. Acceptance tests / definition of done

Tests must run through WebATEM's **existing fake-protocol/test facilities first**, then on actual hardware during a controlled rehearsal. No automatic integration tests should transmit live switcher commands without a conspicuous operator opt-in.

| ID | Test | Pass condition |
|---|---|---|
| A01 | Connect by IP | Correct device model, input count, and physical output count discovered |
| A02 | Names imported | All discovered source buttons show current ATEM short/long names |
| A03 | External rename | Renaming a source in ATEM Software Control refreshes dashboard label |
| A04 | Internal SAVE | Renaming `Output 1` changes local heading but sends no ATEM command |
| A05 | Optional dashboard-staged hardware edit | If a new dashboard staging UI exists, typing an input name sends no command until explicit UPDATE ATEM; the stock WebATEM rename workflow remains unchanged |
| A06 | Focused hardware UPDATE | When dashboard-specific staged routing edits are used, only changed, validated fields are sent; success and failures reported |
| A07 | Stale edit conflict | If the dashboard stages a hardware field, external edits block accidental overwrite; stock WebATEM settings are not duplicated |
| A08 | Virtual Preview | Preview changes locally on a discovered AUX-controlled output; physical output remains unchanged |
| A09 | Virtual CUT | AUX switches to selected Preview; prior live source becomes Preview |
| A10 | Second virtual Preview | Independent queued Preview on the other AUX-controlled output does not change hardware |
| A11 | Second virtual CUT | Independent AUX switches to selected Preview; swap and status correct |
| A12 | M/E Preview | Selecting Next updates hardware M/E Preview only |
| A13 | M/E CUT | Background changes to Preview; all discovered keyers' on-air states unchanged |
| A14 | Keyer toggles | Each key can turn on/off independently; hardware status matches UI |
| A15 | Fill source names | Changing USK fill source in ATEM updates its dashboard label |
| A16 | Direct mode | Clicking any Program source selects it live on that output |
| A17 | Preview + CUT Only | Program buttons are noninteractive; Preview + CUT works |
| A18 | Master CUT | All three routes reach queued sources; no false simultaneity claim |
| A19 | Protected/Instant slider | Choice persists across restarts; behavior matches selected mode |
| A20 | External AUX switch | Dashboard live source updates without attempting to override change |
| A21 | External M/E reassignment | Multiple outputs carrying M/E Program are recognized as linked/mirrored with synchronized M/E state; primary panel follows designation |
| A22 | Network outage | Controls disabled; stale status visible; reconnect resyncs hardware |
| A23 | Restart | Local settings retained; no automatic hardware routing commands |
| A24 | Unsupported sources | Cannot route to sources unavailable for that destination |
| A25 | Source name collision | IDs distinguish sources with same name |
| A26 | Partial MASTER failure | Actual output states reconciled; successful/failed outputs shown |
| A27 | Empty media player | Button state follows discoverable availability and configured visibility rule |
| A28 | Settings M/E move | Diff shows both impacted physical routes; applies only on UPDATE ATEM |
| A29 | M/E next transition keys tied | Dashboard background CUT doesn't accidentally change keyer on-air state |
| A30 | Clean install | Runs from the documented patched Python environment on a fresh Windows 11 test machine |

### Hardware spike that must be completed first

Before polishing the new dashboard, use existing WebATEM controls, state inspection, or a minimal diagnostic test to prove, on the initial validation ATEM (and through the existing shared connection):

1. WebATEM/bmdwire connection over Ethernet.
2. Enumeration of real external inputs, black/color/media sources, short/long names, AUX outputs, M/E, USKs, and DSK.
3. Reliable hardware updates from input name changes and external source selections.
4. Correct mapping of **physical OUT 1–3** to the discovered AUX output controls.
5. Safe background-only M/E CUT while keyers are configured/tied in various ways.
6. A working process for assigning M/E Program to any one of the three managed outputs and moving it under explicit confirmation, without assuming its initial destination.

This hardware spike is a **go/no-go gate** before enabling destructive dashboard operations on a live ATEM. Record observed behavior, code paths, dependency versions, and any limitations in `docs/hardware-verification.md`.

### Preservation-specific acceptance tests

| ID | Test | Pass condition |
|---|---|---|
| R01 | Stock WebATEM connection page | Discovery/manual IP, reconnect and multiple browsers continue to work |
| R02 | Stock M/E controls | Existing Preview, Program, CUT/AUTO and transition settings still operate |
| R03 | Stock AUX controls | Existing physical AUX routing view and commands remain usable |
| R04 | Stock upstream/downstream keyers | Existing keyer controls and settings remain intact and synchronized |
| R05 | Audio and media | Existing audio mixer/meters, media pool/uploads/still thumbnails and player UI unchanged |
| R06 | Macros, profiles and HyperDeck | Existing controls/screens remain accessible and working where available |
| R07 | Cross-view synchronization | New dashboard CUT updates standard view; standard/WebATEM/ASC changes update dashboard |
| R08 | Pooled session | Opening the new dashboard does not create an extra UDP connection for the same ATEM |
| R09 | Multi-operator virtual Preview | Two browsers can queue different AUX Preview targets without silently changing each other or routing hardware |
| R10 | Non-live test run | Tests use fake protocol by default; no real output switches without opt-in |
| R11 | Windows UDP patch | Startup does not log `socket.MSG_DONTWAIT` failures and connection succeeds with known-good patched bmdwire |
| R12 | Original tests | Existing `python -m pytest tests/ -q` suite remains green (or baseline failures documented) |

**Phase 1 is not complete if the new three-panel page works but a previously working WebATEM page breaks.**


## 12. Work plan and development order

### Milestone 0 — Baseline, inventory and safe integration design

- Make a new feature branch; record current WebATEM commit, `bmdwire` revision, working Python version, and launch steps.
- Verify `.venv` resolves to the Windows-compatible `atemwire` source; do not overwrite the tested patch during package changes.
- Launch stock WebATEM, demonstrate ATEM connection, and run existing `pytest` suite; note baseline pass/fail.
- Inspect code and create `docs/webatem-extension-map.md` with specific existing state sources, WebSocket messages, command handlers, view/template boundaries, and tests to reuse.
- Identify stable physical OUT 1–3 IDs and distinguish routable AUX vs M/E feed on the device.
- Propose the smallest additive architecture, UI placement and virtual-preview scoping. **Do not modify production command paths until this assessment is reviewed.**
- Deliver a succinct file-level implementation plan and risk/test matrix.

### Milestone 1 — Additive dashboard and live state (non-destructive)

- Add a Production Dashboard navigation entry/page without removing existing WebATEM views.
- Render three source-aware panels for selected physical outputs. Use discovered IDs, names and assignments.
- Reuse real M/E Program/Preview state in the managed M/E panel; display AUX observed ON AIR state in the other two.
- Add per-operator/session queued virtual Preview for AUX panels, but **no AUX write or Master CUT yet**.
- Render dynamic USK count and fill-source names as read-only indicators first.
- Add tests that page load and Preview selection issue **zero hardware writes**. Confirm cross-view live state updates.

### Milestone 2 — Individual switching and keyer controls

- Add virtual AUX CUT and optional Direct Program behavior via existing WebATEM AUX dispatch.
- Reuse existing M/E CUT/Preview/Program dispatch; verify background-only next-transition/keyer behavior on hardware before enabling the dashboard's CUT.
- Add independent USK on-air toggles through existing keyer dispatch and confirmed feedback.
- Validate source availability, per-panel pending/error status, safe re-click handling, external mutations and reconnect behavior.
- Add fake-protocol tests and a controlled device rehearsal checklist.

### Milestone 3 — Focused settings and Master CUT

- Add local output friendly names, presentation preferences, Program Selection Mode, and persistent Master CUT safety preference.
- Reuse or link to WebATEM's existing hardware label/routing settings; only create specialized UPDATE ATEM staging where existing UI cannot support the required safe composite change.
- Add Master CUT with prevalidation, tightly ordered three-destination dispatch, per-output acknowledgments, partial-failure reporting and post-action reconciliation.
- Exercise cross-view and two-operator race cases. Use a protected confirm-by-default Master CUT behavior.

### Milestone 4 — Regression hardening and documentation

- Run full existing and new test suites; resolve UI/command regressions, disconnection, stale state, timeouts and reentrancy.
- Confirm no duplicate switcher connection and no added cost/requirement for live video capture.
- Validate switcher operation with existing WebATEM, ATEM Software Control and new dashboard open together.
- Document source ownership, setup on Windows 11, `bmdwire` patch/dependency state, release/rollback instructions and operating limitations.
- Produce an operator rehearsal checklist. Do not label production-ready without the keyer safety tests.

### Milestone 5 — Optional packaging

- Once local Python launch is stable, test the existing WebATEM packaging pathway (PyInstaller) rather than introducing a separate installer stack.
- A patched packaged Windows EXE must include the fixed `bmdwire`; rebuilding does not happen automatically when the local source is changed.
- Verify a clean Windows environment and preserve upstream licensing/distribution requirements.

### Phase 2 — Independent live video capture and monitoring (deferred)

- Ingest physical SDI multiview through a compatible capture interface or separate encoder.
- Map/crop available multiview tiles to stable source IDs and show live Program/Preview thumbnails.
- Keep video ingest, decoder, rendering and device requirements behind a separate interface so failure/unavailability of capture **cannot disable or slow Phase 1 control**.
- Do not add the capture module, SDK dependencies or placeholder video services during Phase 1.

### AI coding handoff standard

Implement one milestone at a time. At the end of each milestone provide: exact touched files, tests run and results, working demo instructions, known limitations, and a concise proposed next step. Never silently change source/output IDs, switcher configuration, persistent settings, or existing WebATEM behavior. For uncertain hardware behavior, implement a fake-protocol test, mark **VERIFY ON DEVICE**, and stop short of making an unsafe assumption.

---

## 13. Future work (not Phase 1)

### Future operating enhancements

- Operator presets or service scenes such as Worship, Sermon, Announcements, Communion, when safe across the three managed destinations.
- Keyboard shortcuts, control-surface integrations, optional selective Master CUT groups, and permission/read-only interaction modes.
- More than three configurable managed output panels, based on actual model capabilities.
- Additional dashboard controls only when they add real production value; **existing WebATEM advanced controls remain the primary settings surface**.

### Phase 2: multiview and thumbnails

- Receive the Constellation's 16-window SDI multiview through a compatible **SDI capture device** or **SDI-to-IP encoder**.
- Crop/map source tiles into the dashboard and associate them with discovered source IDs (never identify a video tile solely by a label string).
- Show live Program/Preview thumbnails for managed outputs and optional sources, with careful handling of AUX virtual Preview selections.
- Optionally click a source tile to queue Preview, but only after explicit separate operator testing.
- Network ATEM control alone does not magically provide raw multiview video. Any required capture hardware/software is a **Phase 2 dependency only**.

### Preservation across upgrades

Keep an `UPSTREAM_NOTES.md` or similar short file listing local changes to WebATEM and bmdwire, version updates, regressions, and tests. Upstream changes may add features that supersede local implementations; prefer adopting them over indefinitely maintaining parallel code.

---

## 14. Known risks, assumptions, and decisions to validate

| Topic | Requirement / interpretation | Verification |
|---|---|---|
| M/E ownership | Physical outputs carrying M/E Program are recognized as linked/mirrored sharing hardware M/E state; one designated primary | Inspect live routing, handle zero, one, or multiple outputs cleanly |
| Hardware vs virtual Preview | Only the M/E has a true hardware Preview | Confirm in application state model |
| Background-only CUT | Do not flip USKs accidentally when next-transition keys are tied | **Critical hardware test** |
| Program direct mode | Software UI mode only, not an ATEM-wide restriction | Confirm ATEM panel remains independent |
| Master synchronization | Best-effort command burst, not frame-perfect | Measure during rehearsal |
| Empty media player | Source can exist even with no usable image loaded | Discover player availability; gray out as needed |
| Local output names | ATEM has no applicable friendly destination labels for this workflow | Store by physical connector identity |
| Editing an ATEM field | Must be staged and UPDATE ATEM committed | Check per-field conflict and partial success behavior |
| M/E reassignment | Changes at least the source routed to the new destination; old destination needs an explicit replacement | Prompt with full route diff |
| Discovery scope | Only WebATEM/bmdwire-exposed data can be read | Mark unsupported fields; no guesswork |
| WebATEM/bmdwire compatibility | Depends on local WebATEM/bmdwire versions, ATEM firmware/model | Record versions and verify actual state/command behavior |
| Phase 2 video over network | Requires external encoder, not native Ethernet multiview feed | Out of current scope |

### Questions intentionally deferred rather than silently decided

1. The **MASTER safety slider** can be shown as `Protected` (confirmation on each MASTER CUT) versus `Instant`; this is the current proposal. Test usability before locking it in.
2. When multiple physical outputs carry M/E Program, the dashboard identifies them as linked/mirrored destinations sharing hardware Program/Preview/CUT, designating one as primary control without changing hardware routing.
3. Source visibility for empty media players should favor consistency (disabled over disappearing). Verify available metadata on the target firmware.
4. When manually moving M/E Program to a different output, the user must explicitly select the old destination's replacement source. Do not infer it.

These are design refinements, not blockers to starting the WebATEM integration/audit milestone.

### New integration risks / decisions

| Topic | Phase 1 decision | Verification |
|---|---|---|
| Existing WebATEM controls | Preserve all stock views; new dashboard is additive | Regression inventory and smoke tests |
| Shared connection | Reuse existing per-switcher pooled session; no new UDP client | Inspect pool metrics/logs with two browser tabs |
| Windows `MSG_DONTWAIT` bug | Treat as separate, already-tested bmdwire patch; avoid losing it on reinstall | Confirm imported module path and connection smoke test |
| Virtual AUX Preview scope | Default per operator/browser session, not a global Python variable | Two browsers queue distinct Next sources |
| Hardware settings duplication | Prefer existing WebATEM Settings | Map current functionality before adding new pages |
| New route's CSS/JS | Scope to dashboard to avoid breaking stock UI | Browser smoke and existing test suite |
| Package/build | Reuse existing WebATEM installer/launcher pipeline | After Phase 1 control passes |
| Live media | No additional video capture in Phase 1; existing still thumbnails remain | No capture/decoder dependencies introduced |


---

## References and validation sources

- **[S1] WebATEM source, README and development guide:** https://github.com/lucas-romanenko/webatem (existing features, package/layout, tests, launch/packaging)
- **[S2] bmdwire protocol source:** https://github.com/lucas-romanenko/bmdwire (atemwire and HyperDeck; Windows UDP patch ownership)
- **[S3] WebATEM Python packaging/dependencies:** https://github.com/lucas-romanenko/webatem/blob/main/pyproject.toml
- **[S4] WebATEM development and test suite:** https://github.com/lucas-romanenko/webatem/tree/main/tests and `README.md` Development section
- **[S5] ATEM 1 M/E Constellation 4K technical specifications:** https://www.blackmagicdesign.com/products/atemconstellation/techspecs/W-APS-40
- **[S6] Blackmagic ATEM SDK manual (hardware semantics reference, not chosen implementation API):** https://documents.blackmagicdesign.com/DeveloperManuals/ATEMSDKManual.pdf
- **[S7] ATEM Software Control docs (CUT/next-transition/key tie behavior):** https://www.blackmagicdesign.com/products/atemsdi/software

## Final definition of Phase 1

**Phase 1 is complete when WebATEM continues to do everything it did before, and an operator can open an additional Production Dashboard, see the ATEM's actual source labels and state, operate three physical destinations through one real M/E and two independent virtual AUX Preview/Program/CUT workflows, safely toggle the discovered upstream keys, perform a guarded Master CUT, set local-friendly labels independently of hardware changes, recover from disconnects/external changes, and trust the ON AIR indications to reflect confirmed hardware state.**

**Phase 2 remains independent:** live capture/multiview and video thumbnails are not prerequisites for any Phase 1 control.

