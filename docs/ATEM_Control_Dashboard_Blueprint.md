# ATEM Control Dashboard
## WebATEM Extension Blueprint — Version 0.5

**Prepared:** November 16, 2026  
**Status:** Development specification / proposed WebATEM extension  
**Initial validation device:** Blackmagic Design ATEM 1 M/E Constellation 4K; requirements must not depend on its current source assignments or naming  
**Platform:** Windows 11 hosting WebATEM; browser-based control page  
**Scope:** Version 1 (control only; no video capture or thumbnails)

> **Purpose:** This is the single source of functional requirements for extending the existing open-source WebATEM application in our `atem-dashboard` fork. Reuse WebATEM’s discovery, network protocol library, hardware commands, live state distribution, existing controls, tests, styling, and launcher. Build only the additional multi-output operator workflow and required local preferences. The goal is not to replace WebATEM or to rebuild Blackmagic ATEM Software Control.
>
> **Implementation language:** “MUST” = required for V1, “SHOULD” = preferred for V1 if practical, “FUTURE” = explicitly out of scope. **INHERIT** = an existing WebATEM capability that must be reused and validated, not rewritten. **BUILD** = a new feature unique to this extension. **VERIFY IN REPO** and **VERIFY ON DEVICE** identify open questions that must be checked against the current fork and the actual switcher, respectively.

---

## 1. Vision and scope

Extend WebATEM with a new browser-based dashboard showing **three independently operated outputs**. Each output has **PREVIEW**, **PROGRAM**, and **CUT** controls. For V1, two outputs use the ATEM's routable auxiliary SDI outputs to simulate a Preview/Program workflow in software. One selected output receives the switcher's real **M/E Program**, giving it genuine hardware Preview/Program and access to the keyers discovered on that M/E. The application must discover all input labels, source IDs, output routing, and keyer assignments from the connected ATEM rather than assuming a venue-specific setup.

WebATEM already reads ATEM input names and hardware state and publishes state to browser clients. Our extension consumes those existing capabilities. Its dedicated **Settings** area differentiates dashboard-local preferences from staged hardware edits; its **Dashboard** sends live commands through WebATEM’s existing command path. Existing WebATEM control pages and advanced settings remain available.

### 1.1 Explicit V1 goals

1. **INHERIT:** Connect over Ethernet through WebATEM’s discovery/manual-IP and reconnection facilities.
2. **INHERIT:** Consume WebATEM’s discovered inputs, internal sources, output destinations, M/E, upstream/downstream keyers, and media-player state as available in its current state model.
3. **BUILD:** Show three output panels tied specifically to physical **OUT 1, OUT 2, OUT 3** for this release.
4. **BUILD:** Support independent Preview and Program source selection for each output.
5. **BUILD:** Support individual CUT actions and a MASTER CUT across all three outputs.
6. **BUILD UI, REUSE CONTROL:** Give the M/E-assigned output on-air toggles for **all upstream keyers discovered on that M/E** (four on the initial validation device) and display each key's configured fill source label.
7. **INHERIT data/commands, BUILD staged workflow:** Read existing ATEM input short/long names and allow deliberate changes to those names through **UPDATE ATEM** on our new settings page.
8. **BUILD:** Offer user-controlled output names and preferences saved via the WebATEM server through **SAVE**.
9. **INHERIT state transport, BUILD new view updates:** Keep the dashboard synchronized with changes made in WebATEM, ATEM Software Control, or the hardware panel.
10. Operate without SDI capture hardware, a multiview stream, cloud services, or subscriptions.

### 1.2 Explicitly excluded from V1

- USB-C control (network/IP only).
- Chroma/luma/key mask configuration, media uploading, media playback editing, audio mixing, DVE control, and downstream keyer **control** (these settings may be read for discovery).
- Video monitoring or thumbnails.
- Multiple independent physical M/E engines, dissolves on virtual outputs, or guaranteed frame-accurate switching among outputs.
- Read-only/live operating mode.
- Automation presets, service scenes, and scheduling. WebATEM already supports browser-based multi-operator access; this extension must preserve that ability, not recreate a second transport.
- Management of more than three physical output panels.

### 1.3 Reference hardware capabilities (not configuration defaults)

The following describes the **initial validation model**, not the assumed configuration of a connected switcher. The application must discover actual capabilities and never preload input names, signal purposes, or output roles from this table.

| Capability | ATEM 1 M/E Constellation 4K reference |
|---|---|
| External inputs | 10 SDI |
| Assignable SDI outputs | 6 (V1 uses OUT 1–3) |
| Hardware M/E blocks | 1 |
| Upstream keyers | 4 |
| Downstream keyers | 1 (discovery only in V1) |
| Color generators | 2 |
| Media players | 2 (verify usable source availability per device) |
| Multiview | One 16-window-capable output; future work |
| Control | Ethernet |

**Do not hard-code device capabilities into the UI or duplicate WebATEM’s discovery layer.** Consume its current device report, augment its state model only if a field needed by this dashboard is genuinely absent, and verify that any extension remains model-aware. See [W1] and [H1](#references-and-validation-sources).

---

## 2. Device-derived source and output mapping

### 2.1 Input discovery: no venue-specific baseline

**The specification intentionally contains no physical-input assignment table.** A connected ATEM is authoritative for its actual input inventory. There must be no built-in assumptions such as a particular computer, camera, lyrics feed, or signal on any numbered connector.

On connection, populate the source catalog from WebATEM’s existing per-switcher state and capability discovery:

- Physical input/source IDs, connector numbers (if exposed), source type, short name, and long name.
- Internal sources supported by the device, such as Black, color generators, and media players.
- Availability for the relevant M/E and AUX destinations.
- Names and assignments of keyer fill/key sources by joining their hardware source IDs to the same discovered source catalog.

Any examples elsewhere in this document are **illustrations only**. They are not initial configuration values and must never be automatically written to the ATEM. Input IDs, not labels or their position in a sample list, control routing. ATEM short names may be limited to four ASCII characters; verify naming constraints in WebATEM’s input-edit validation and against the device.

### 2.2 Physical outputs and software roles

For V1, the app displays **three panels associated with physical OUT 1, OUT 2, and OUT 3**, subject to the device supporting those routable outputs. Their purpose, names, and current source assignments are **not predetermined**.

| Physical connector | Default local heading | Dashboard role at connection |
|---|---|---|
| OUT 1 | Output 1 | Discovered from its current hardware routing |
| OUT 2 | Output 2 | Discovered from its current hardware routing |
| OUT 3 | Output 3 | Discovered from its current hardware routing |

- Internal Settings lets an operator assign a friendly name to each output; these names exist only in this app.
- Determine which configured physical output currently carries **M/E Program** by reading the ATEM's routing. That panel becomes the **Hardware M/E** output; remaining panels are **Virtual AUX** outputs.
- If no configured output carries M/E Program, show a configuration warning. If multiple outputs carry the same M/E Program source, require the operator to select exactly one **managed M/E dashboard panel**; do not force the hardware to change merely to make this choice.
- The selected M/E destination may be reassigned through **ATEM Settings → UPDATE ATEM**; this changes a physical output's source, not the location or quantity of M/E engines.

### 2.3 Header naming rule

Each heading MUST be generated dynamically from the **saved local friendly name**, **physical output number**, and **confirmed hardware M/E assignment**:

```text
OUTPUT: <Friendly Name> (OUT 1)
OUTPUT: <Friendly Name> (OUT 2, M/E)
OUTPUT: <Friendly Name> (OUT 3)
```

The example above shows the possible formatting when OUT 2 happens to carry M/E Program; it is **not a default M/E assignment**. A different output may carry M/E Program, so the suffix must move accordingly. On a clean install, local friendly names start as `Output 1`, `Output 2`, and `Output 3` until the user names them.

---

## 3. Functional architecture

### 3.1 Logical signal plan

```text
             CONNECTED ATEM: DISCOVERED SOURCE CATALOG
                              |
                 +------------+------------+
                 |                         |
       Routable AUX destinations       M/E ENGINE
       (direct source routing)        Program + Preview
                 |                         |
       Virtual Preview lives         Upstream keyers
          in application                  |
                 |                         |
             Physical OUTs <--- configurable assignment of M/E Program
```

- **Exactly one** of the three managed output panels is designated as the M/E panel in V1 after successful hardware assignment validation; which connector receives M/E Program is discovered and may be changed intentionally.
- Other managed outputs are independent direct AUX routings; their Preview selections exist only in this application.
- An M/E background CUT must **not intentionally alter any upstream keyer's on-air state**. Verify the effect of ATEM *next-transition selection / tie* settings and implement background-only CUT behavior (see §8.4).
- MASTER CUT operates all three physical outputs, but cannot promise frame synchronization across AUX and M/E commands.

### 3.2 Software layers — WebATEM-first design

```text
Browser: New three-output dashboard (Django templates + Alpine.js)
                  |
          Existing WebATEM WebSockets / HTTP
                  |
    New output workflow coordinator (Python / Django)
       |             |                |
  virtual Preview   MASTER CUT    dashboard settings
       |             |                |
    EXISTING WebATEM command dispatch + shared device state
                  |
        EXISTING atemwire / bmdwire protocol layer
                  |
             Ethernet -> ATEM

Existing webatem/ launcher, Windows packaging, styling, discovery,
connection pooling, other control pages, and test infrastructure stay in place.
```

**Use the existing repository stack:** Python 3.10+, Django/Channels, Alpine.js, Tailwind 3, DaisyUI 4, WebSockets, and the installed `bmdwire`/`atemwire` protocol implementation. These are documented in WebATEM's README and design brief. Do **not** create a second C#/WPF app, direct Blackmagic SDK adapter, Electron wrapper, React frontend, ATEM session manager, or separate polling engine unless a documented gap and an explicit architecture decision require it.

**New code should be narrowly scoped:** a dashboard view/template and supporting client state; a server-side orchestration service for virtual Preview and coordinated CUT; and new dashboard preferences plus staged ATEM-setting edits. Reuse existing command dispatch, source IDs/names, event messages, device inventory, reconnection, and validation patterns. Determine the actual code entry points by reading the checked-out repository; paths mentioned in this document are guidance, not proof of a particular function/class.

**Multi-operator rule:** WebATEM supports multiple browser clients on a pooled switcher connection. For a given ATEM device and controlled physical output, virtual Preview must have **one shared authoritative server-side value** (and broadcast to connected dashboards), not an independent browser-tab choice that would make MASTER CUT unpredictable. Define conflict handling when two operators queue different sources. A new browser must see the current shared queue, and server restart behavior must remain conservative (no surprise hardware commands).

**Extension over replacement:** Keep upstream WebATEM settings and full-control surfaces usable. Add the new page through the existing Django routing/templates or supported extension hooks, choosing the smallest maintainable modification that preserves upstream updateability. The README describes `atem_control.hooks.Hooks` and a `control_extra` template block; **VERIFY IN REPO** whether they support a separate top-level dashboard page or only embedding panels.

## 4. Screens and navigation

Our extension introduces two operator-facing surfaces inside WebATEM:

1. **Three-Output Dashboard** — custom live switching and USK on-air controls. This is the primary workflow we build.
2. **Dashboard Settings** — tabs for **Internal Settings** and **ATEM Settings**, with distinct SAVE and UPDATE ATEM behavior. This may reuse existing WebATEM settings components; do not recreate all existing ATEM setting forms.

Existing WebATEM full control, advanced ATEM settings, media pool, audio, macros, and other pages MUST remain accessible and functional. The new dashboard should include an easy link back to the original controls.

Reuse the existing launcher, device selection/connect page, connection-state display, and browser navigation where possible; do not introduce a second network/IP onboarding flow. Show the active ATEM, current connection status, and output-assignment warnings on the new dashboard. WebATEM's normal browser access is a supported part of the product; Windows hosting is the initial deployment target.

**UI design:** Follow the current WebATEM control surface's established red Program / green Preview / amber keyer semantics, dark palette, raised illuminated buttons, and font choices. Its branding brief identifies `atem_control/static/brand/brand.css` as the shared styling source and says it loads after compiled Tailwind; extend it sparingly rather than introducing a competing design system. Do not add new logo/branding deliverables to this project's scope.

### 4.1 Dashboard: browser-first wireframe

Optimize first for a 1920×1080 Windows control laptop/display. Maintain usability in a browser at smaller viewport sizes (scroll or stack panels without shuffling input identity). No separate desktop UI toolkit is required.

```text
+--------------------------------------------------------------------------+
| ATEM CONTROL DASHBOARD | <Device model> @ <ATEM IP> | CONNECTED | Settings |
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

Do not infer input availability from a name or from whether a cable is connected. Query source availability for the particular M/E or AUX destination. Unsupported selections are hidden or disabled with an explanation. Color generators remain available even if their color settings have not been customized; empty media players may be hidden through an internal preference. Default V1 behavior: show all supported source types; disable a known unusable player rather than silently removing a familiar button during the show.

- **PREVIEW row:** selecting a source queues it. Green selection means *next*; on virtual outputs it is software-only.
- **PROGRAM row:** red selection means the hardware-confirmed live source. Behavior is determined by **Program Selection Mode**, not the physical switcher's own global preference.
- The colored state should also have text (ON AIR / NEXT) so operators are not dependent on color alone.
- Button labels update if another operator renames the input from WebATEM, ATEM Software Control, or another hardware controller.
- If a source ID disappears or becomes unavailable, mark it unavailable and disable its selection; never silently substitute a different source.

### 4.3 Program Selection Mode (Internal Setting)

| Mode | PREVIEW click | PROGRAM click | CUT click |
|---|---|---|---|
| **Direct** | Selects next source | Immediately switches that output live | Transitions to queued preview |
| **Preview + CUT Only** | Selects next source | Indicator only; no click action | Required to change the live source |

**Default: Preview + CUT Only.** This is **unique to our dashboard**, not an ATEM-wide lockout. External ATEM Software Control or physical-panel operations remain unrestricted. The setting persists across app restarts and applies to all three output panels.

### 4.4 Upstream keyer strip (M/E output only)

Only the output currently assigned M/E Program shows the strip; use WebATEM’s existing keyer state and on-air action rather than a new protocol implementation:

```text
UPSTREAM KEYERS (<discovered count>)
[KEY 1 | <fill-source name> | ON AIR]
[KEY 2 | <fill-source name> | OFF]
... one control per discovered upstream keyer
```

- Enumerate available upstream keyers; do not assume there will always be exactly four on future devices.
- A keyer button is a **live on-air toggle** and immediately issues the corresponding ATEM `SetOnAir` state change.
- Show the actual current state (`ON AIR`, `OFF`, `PENDING`, `ERROR`) from ATEM feedback.
- Show the keyer's **fill source** name (from the ATEM input catalog) beneath the key number. The key/cut source, if different, may be available in tooltip/details; don't confuse it with fill.
- Updates to keyer fill source assignments made in ATEM Software Control must change the displayed name automatically.
- Key configuration (chroma color, clip/gain, masks, pattern, etc.) remains in ATEM Software Control; read if discoverable, but do not edit in V1.
- If M/E ownership changes to a different output, the keyer strip follows the **new M/E panel**, not the old physical connector.
- Downstream keyers are discovered, but V1 does not surface control buttons for them.

### 4.5 Master CUT

- One prominent **CUT ALL OUTPUTS** button.
- Command target: each output's current Preview selection.
- M/E output: use a hardware M/E background CUT.
- Virtual outputs: set each assigned AUX's live source to its queued Preview source.
- The application must **pre-validate all three destinations** before starting. If any output is disconnected, unconfigured, invalid, or in a conflicting hardware state, do not attempt an all-output transition. Show the reason.
- Switching commands execute as closely together as practical but are **not guaranteed frame-synchronous**.
- A partially successful command must be reported accurately. Do not pretend to roll back physical video switching; resynchronize to the actual hardware state.

**Master safety slider:** A persistent on-screen slider, not a momentary ARM button that resets after every action. Recommended initial design: `PROTECTED` prompts before each master action; `INSTANT` executes on click. Store the selected mode in dashboard-specific server settings. This is a UX decision that should be tested with operators before final styling. Either way, the slider stays in the chosen state until changed.

### 4.6 Dashboard live status behavior

- Connection lost: immediately disable live controls and show the last observed state as **STALE / DISCONNECTED**, not current truth.
- Command pending: show a brief pending indicator; ignore rapid repeated commands targeting the same bank until state is reconciled.
- Command rejected/time-out: display a concise error, query the device state, and correct the UI.
- Changes from ATEM Software Control or the chassis: update the affected red/green selections and key statuses automatically.
- M/E Program display represents the M/E background source plus separate keyer status; do **not** suggest that the input label alone fully describes the keyed composite.

---

## 5. Dashboard Settings: new UX around existing controls

These two tabs are specific to **our dashboard**. Do not replace or constrain WebATEM's existing advanced ATEM settings page; its live-edit behavior remains an available expert workflow. The staged `UPDATE ATEM` rule applies only to edits made within our new ATEM Settings tab.

The two tabs have independent unsaved-change indicators, validation, and save actions. They should reuse WebATEM's existing device and form components as appropriate, without introducing duplicate hardware state stores.

### 5.1 Internal Settings — `SAVE`

These settings belong to our application and **must not** send configuration updates to the ATEM.

| Setting | Type / behavior | V1 default |
|---|---|---|
| Preferred ATEM device | Existing WebATEM discovered/recent device identity or manual IP | No device assumed |
| Connection/discovery behavior | Inherit existing WebATEM launcher / device chooser behavior | WebATEM defaults |
| Local friendly output name | One per output | Output 1, Output 2, Output 3 |
| Output display order | Ordered list | OUT 1, OUT 2, OUT 3 |
| Button label style | Short / Long / Both | Both where space allows |
| Source visibility | Per source ID/category | Supported sources shown |
| Source ordering | Sort/order preferences | Physical inputs then internal sources |
| Program Selection Mode | Direct / Preview + CUT Only | Preview + CUT Only |
| Master CUT Safety | Protected / Instant | Protected |
| Hide empty media player sources | Boolean | Off (disable unusable) |

**SAVE contract:** Validate all dashboard-local fields; persist them with an appropriate **server-side** WebATEM persistence mechanism (prefer extending existing SQLite/Django storage where warranted; avoid introducing another independent configuration system). Identify settings by device identity and physical output ID so the page behaves consistently for multiple browser operators. Apply local labels/visibility changes to the dashboard and broadcast shared changes when appropriate. Display `Saved` or a specific error.

Device discovery, manual IP connection, remembered connections, and launcher network interface/port already belong to WebATEM; reuse those UI paths rather than cloning them in Dashboard Settings.

### 5.2 ATEM Settings — `UPDATE ATEM`

These settings are read from the device and must be deliberately committed back to hardware.

| Editable field | Source of initial value | Commit effect |
|---|---|---|
| Input short name | ATEM | Calls ATEM setter; max 4 ASCII characters |
| Input long name | ATEM | Reuses existing WebATEM rename command; validate per current implementation and ATEM constraints |
| M/E Program destination among OUT 1–3 | Observed OUT source routing | Updates affected AUX source assignments |
| Physical output source mapping / initial assignment | Current hardware output routes | Changes hardware routing when explicitly committed |

Read-only information in this tab may include model, video mode, all discovered inputs, USK/DSK status and configuration, media player assignments, color sources, and output source mapping. Prefer an overview/link into existing WebATEM detailed settings instead of copying dozens of configuration controls.

**UPDATE ATEM contract (new staged workflow for this page only):**

1. When opening the tab, capture a baseline snapshot of editable hardware fields.
2. User edits fields in a **staging buffer**. Do **not** alter hardware yet.
3. Show a **Changes to ATEM** diff: old value → proposed value; clearly identify any change that might affect an on-air output.
4. Before committing, re-read the latest hardware values. If an edited field has changed externally since staging, **block that field**, show the conflict, and require reload/review. Unedited fields must never be written back.
5. Ask for explicit confirmation for output-routing changes (they may affect screens immediately).
6. Apply only validated changes through existing WebATEM commands, recording per-field success/failure; independent hardware commands are not guaranteed atomic.
7. Re-query authoritative ATEM state, update the UI, and show an accurate outcome, including partial success.
8. Never attempt a silent hardware rollback or restore a stale full-switcher snapshot after a failure.

**M/E reassignment nuance:** If the user reassigns M/E Program from one managed output to another, the formerly M/E-fed output needs a direct source assignment. The confirmation must show **both** affected outputs and explicit resulting routes. Do not guess what should replace M/E Program on the old output. Permit cancellation without any hardware change. This operation is not guaranteed to be frame-atomic.

**Physical output count in V1:** The UI is restricted to three panels tied to OUT 1, OUT 2, and OUT 3. Future versions may support a variable number of configurable output panels based on model capability.

### 5.3 Connection and discovery information

After connection, use WebATEM’s state model to display a concise **Device Information** summary (read-only); deeper detail may link to WebATEM’s existing settings:

- Product/model name, reachable IP, firmware/version information **when exposed**.
- Available external inputs, input IDs, short/long names, port type, and source availability.
- Available routable physical outputs and current assignments.
- M/E blocks, current Program/Preview, transition state and next-transition selection (if exposed).
- USK and DSK count, current types, fill/key source IDs, on-air state, and key settings where available.
- Media player count, current still/clip assignment and metadata where available.
- Color generator sources and relevant values where available.
- Other discovered capabilities only for diagnostic visibility, without V1 edit controls.

**Do not reimplement or promise a clone of all ATEM settings.** The requirement is to consume *the relevant data available in WebATEM’s current protocol/state implementation*. For missing fields, first inspect the underlying `atemwire` state and existing command dispatcher; extend minimally if needed. Mark unsupported/unknown fields as such.

---

## 6. Domain model and state ownership

### 6.1 Required conceptual models

```text
AtemDevice
  deviceId / model / ip / connected / capabilitySnapshot  # from WebATEM state

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
  queuedPreviewSourceId (hardware M/E or shared server-side virtual selection)
  controlState (Ready | Pending | OutOfSync | Disconnected)

UpstreamKey
  keyId / type / fillSourceId / cutSourceId / onAir

MediaPlayer
  playerId / fillSourceId / assignedContent / contentAvailable

DashboardSettings
  deviceIdentity / outputNames / sourceVisibility / labelStyle
  programSelectionMode / masterSafetyMode / reconnectPreference

StagedAtemChanges
  initialHardwareBaseline / editedFields / conflictList
```

These are conceptual domain entities, not prescriptions for Python class names. Reuse/adapt existing WebATEM models and state messages rather than duplicating them.

### 6.2 Single source of truth

| Data | Owner |
|---|---|
| Input names, physical source IDs | ATEM |
| Current AUX routes | ATEM |
| Real M/E Program and Preview | ATEM |
| Upstream key configuration and on-air states | ATEM |
| Local output friendly names | Dashboard settings stored on WebATEM server |
| Source button visibility and order | Dashboard settings stored on WebATEM server |
| Virtual AUX Preview selection | Shared server-side dashboard session state, keyed by ATEM and output |
| Master safety, Program Selection Mode | Dashboard settings stored on WebATEM server |
| Unsaved hardware edits | Temporary ATEM Settings staging buffer |

**Never conflate an optimistic UI update with confirmed hardware state.** Keep commands and state updates separate.

### 6.3 Source identity and label formatting

- ATEM source IDs, not displayed names, are routing identifiers.
- Labels must be generated dynamically by joining source IDs to the latest source catalog.
- Input names may be blank, duplicated, changed elsewhere, or shortened; always show an input number/ID alongside any potentially ambiguous name.
- Suggested label fallback: `IN 3`, `COL 1`, `MP 1`, or `Source <ID>` if no name exists.
- Changing a name should never change any routing assignment.

---

## 7. State synchronization and startup rules

### 7.1 Connection sequence

1. Start the existing WebATEM application using its normal Windows launcher/server; load validated dashboard-specific preferences.
2. Select a device via WebATEM’s discovered/recent switcher list or its manual IP control.
3. Reuse WebATEM’s pooled network session and current connection status; do not establish a second ATEM client from the dashboard.
4. Consume WebATEM’s discovered capabilities, source catalog, routes, M/E state, keyers, and media players.
5. Identify which of physical OUT 1–3 routes M/E Program. If zero or multiple matching outputs exist, require the operator to explicitly choose which output panel is managed as M/E; do not silently infer a single owner or automatically rewrite hardware. Multiple physical outputs may legitimately receive the same M/E feed.
6. Initialize each virtual output's live source from the actual AUX assignment.
7. Initialize the **shared server-side virtual Preview** conservatively for each device/output. If a valid saved queue exists, it may be restored as a queued source only. Otherwise set it equal to current live source so the first CUT is a no-op until someone explicitly queues Preview. Notify every connected dashboard of this same selection.
8. Subscribe the dashboard to existing WebATEM WebSocket state changes; extend its message/state model only for genuinely missing fields and for the new shared virtual-Preview queue.
9. Only enable live dashboard controls once the relevant device snapshot is consistent and current.

Never issue ATEM routing commands automatically just because the app started or reconnected.

### 7.2 External changes

- A source name changes outside the app: update button labels immediately.
- An AUX route changes externally: update that output's red ON AIR selection. Preserve the queued virtual Preview if still valid; revalidate on next CUT.
- The M/E Preview or Program changes externally: update the genuine M/E panel from hardware.
- Upstream keyer fill source or on-air state changes externally: update key buttons and labels.
- The M/E Program feed moves to a different configured physical output externally: move the M/E role and keyer strip after confirming the new routing. If routing is ambiguous, block control and display `M/E assignment needs review`.
- A source is removed, disabled, or becomes unavailable: disable pending actions referencing it, without silently replacing it.

### 7.3 Disconnection and recovery

- Upon disconnect: disable all live switching, mark confirmed values **last observed**, retain local settings, and log the reason.
- Let WebATEM’s existing connection/session pool handle retry/backoff; the extension must respond to the shared connection state and not create independent retries.
- On reconnect: re-discover and re-read all hardware state rather than replaying cached commands.
- Never automatically reapply old hardware output assignments or input names.
- Preserve valid virtual Preview choices only when doing so is safe, for the same hardware/connector, and visibly label them queued.
- If another controller changed routing while disconnected, display the changed state rather than trying to force the previous state back.

---

## 8. Switching rules (normative)

### 8.1 Definitions

- **Live**: confirmed source feeding a virtual-output AUX, or the confirmed M/E background Program source for the M/E panel.
- **Next**: Preview source. Hardware-owned on the M/E panel; server-held and shared across browser clients for virtual panels.
- **CUT**: take Next to Live. On the M/E, send a native CUT with keyers unaffected by the dashboard's background transition. On virtual panels, set AUX source to Next.
- **Swap after CUT**: once successful, the formerly live source becomes Next, enabling the next CUT to toggle back. On the M/E panel, use the actual post-cut Program/Preview reported by ATEM instead of assuming its internal state.

### 8.2 Virtual AUX output: Preview

```text
SelectPreview(panel, sourceId):
  assert connected, configured, source allowed for this AUX
  atomically set shared_server_queue[deviceId, outputId] = sourceId
  broadcast updated queued Preview to all dashboard clients
  render green preview indicator
  do not send any hardware routing command
```

### 8.3 Virtual AUX output: Program and CUT

```text
SelectProgramDirect(panel, sourceId):
  assert ProgramSelectionMode == Direct
  assert connected + source allowed
  dispatch existing WebATEM AUX routing command with sourceId
  wait for device confirmation / updated route
  set live state from actual device route
  leave shared queued Preview unchanged unless now invalid

CutVirtual(panel):
  assert connected + configured + preview valid
  previousLive = observed AUX source ID
  target = queuedPreviewSourceId
  if target == previousLive: no-op with clear UI feedback
  dispatch existing WebATEM AUX routing command with target
  wait for confirmed observed AUX source == target
  on success: atomically set shared queuedPreviewSourceId = previousLive and broadcast
  on failure: re-read actual route; don't invent a swap
```

Do not use a generic “toggle back to last source” mechanism that bypasses the Preview row. The operator's current Preview choice is the target.

### 8.4 Real M/E output: Preview, Program, and CUT

```text
SelectPreviewME(sourceId):
  dispatch existing WebATEM M/E Preview selection command
  show selection only after authoritative WebATEM state update

SelectProgramDirectME(sourceId):
  only when Direct mode
  dispatch existing WebATEM M/E Program selection command
  resynchronize ME Program/Preview from hardware

CutME():
  ensure expected ME is the one assigned to this panel
  verify transition/next-transition state permits background-only CUT
  dispatch existing WebATEM M/E CUT command with verified background-only semantics
  read confirmed ME Program/Preview and keyer on-air status
```

**Critical hardware acceptance condition:** Blackmagic's *next-transition* selections can tie upstream keys to a transition. The dashboard's ordinary M/E CUT is intended to transition the **background only**, leaving all four USK on-air states unchanged. During the hardware spike, inspect WebATEM’s existing transition/next-transition logic, then determine the correct safe command sequence for ensuring `BKGD-only` next-transition selection; perform it safely and avoid overwriting simultaneous changes made by another operator. If this cannot be done reliably, V1 must warn/block rather than silently turning keys on/off. Do not simply assume that calling `PerformCut()` can never affect keyers. See [H2](#references-and-validation-sources).

### 8.5 Upstream key toggle

```text
ToggleUSK(keyId):
  ensure connected, currently assigned to this M/E, not pending
  desired = !observedOnAir
  dispatch existing WebATEM keyer on-air action with desired
  wait for authoritative WebATEM key on-air state feedback
  on error: re-read state, show failure
```

Consume existing WebATEM keyer state for fill/key names and on-air status. Reuse its existing keyer on-air command; verify on real hardware. Do not create a separate raw UDP command path.

### 8.6 Master CUT

```text
CutAll():
  ensure connected, no unresolved output conflict, all three previews valid
  apply persistent safety setting (PROTECTED confirmation or INSTANT)
  capture target Preview IDs and observed live IDs for all panels
  dispatch two virtual AUX routes + one ME background CUT
  using the discovered M/E assignment (not fixed output numbers)
  dispatch in tight sequence without unnecessary UI waits between commands
  collect independent confirmations for each output
  if all succeed: update shared virtual Preview swap states + ME observed state
  if partial failure: show which outputs changed and which did not;
                      refresh all output states; do not auto-rollback
```

**Timing requirement:** Favor a responsive, consistent command path but do **not** claim simultaneous frame-boundary cuts. Coordinate the three actions in one **server-side** command transaction/sequence that locks relevant output queues, snapshots intended targets once, and records individual hardware acknowledgments. Prevent competing browser tabs or concurrent operators from interleaving changes to one controlled output while MASTER CUT runs. Do not claim frame synchronization. Document measured switching skew in hardware tests.

---

## 9. WebATEM integration contract and implementation guidance

**Implementation baseline:** Fork `https://github.com/lucas-romanenko/webatem` in the local `atem-dashboard` repository and use its current Python/Django + Alpine.js UI, WebSocket state updates, shared ATEM connection, and `bmdwire`/`atemwire` commands. Work with the exact version checked out, not remembered method names from unrelated ATEM libraries. The README documents these structural components: `atem_control/` (Django app, command dispatcher, UI, discovery), `webatem/` (project and launcher), existing tests, and WebATEM's extension hooks.

### 9.1 Existing responsibilities: inspect and reuse

| Requirement | Existing WebATEM feature to inspect | New work |
|---|---|---|
| Discover devices / connect by IP | Network discovery, recent devices, connection pool | None unless a device-model compatibility gap is found |
| Discover source IDs and names | Per-switcher state and input label UI | Adapt discovered source catalog to our button grid |
| Rename inputs | Existing input-name settings/command | Stage edits in our ATEM Settings until UPDATE ATEM |
| Read/route AUX outputs | Existing AUX commands/state | Map two output panels and supply virtual Preview/CUT logic |
| M/E Program, Preview, CUT | Existing M/E buttons/commands | Map to the selected M/E panel; enforce safe background-only CUT |
| Keyer on-air state and fill source | Existing USK state/config and on-air actions | Four/discovered toggle buttons and dynamic fill labels in one panel |
| Color/media sources | Existing state, media player metadata | Source button ordering, visibility and availability |
| Reconnection and state fan-out | WebSocket consumer + pooled session | Subscribe and reconcile new shared virtual Preview state |
| Windows launch / install | Existing WebATEM tray app / PyInstaller | Reuse and rebrand only if later necessary |
| UI styles | Existing `brand.css`, fonts, Tailwind/DaisyUI | Add only dashboard styles consistent with current design |
| Tests / CI | Existing Python pytest suite, fake protocol layers | Add tests for extension logic and nonregression |

These are **documented WebATEM capabilities**, not proof that every field is already exposed in a convenient Python class or WebSocket payload. **VERIFY IN REPO** the current function/file for each before implementing.

### 9.2 Required new components (conceptual)

```text
ThreeOutputDashboardView:
  consumes existing source catalog + live hardware state
  renders three bank panels and shared operator preferences
  sends application commands, never direct UDP

OutputWorkflowService (Python):
  get/set shared virtual Preview per device and physical output
  CutVirtual(output)  -> existing AUX action
  CutMEBackgroundOnly() -> existing transition action with key safety
  CutAll() -> validates/coordinates 2 AUX + 1 M/E, reports partial failures
  emits updates to all connected dashboard clients

DashboardSettingsStore:
  saved friendly names, program-selection mode, master safety,
  source label/visibility/order, panel assignments

StagedAtemSettings:
  temporary editable diff from hardware snapshot
  UPDATE ATEM writes only confirmed changed fields via existing actions
```

Do not create an entirely separate ATEM device model. Extend or adapt the one used by WebATEM. Do not introduce a second REST API solely to have an API: use the existing WebSocket/HTTP command dispatch pattern unless a small endpoint is justified by staged-settings semantics.

### 9.3 Repository placement and customization strategy

```text
atem-dashboard/                              # your fork of WebATEM
  atem_control/                             # EXISTING Django app
    ...                                     # Existing state, commands, templates, assets
    [new dashboard view/template/service]   # Concrete names chosen after code review
  webatem/                                  # EXISTING server + Windows launcher
  tests/                                    # EXISTING pytest regression suite
    [new dashboard tests]
  docs/
    ATEM_Control_Dashboard_Blueprint.md    # this file
    webatem-capability-audit.md            # file/function/field mapping
    hardware-validation.md                 # verified model/firmware behavior
```

The bracketed paths are placeholders for new files, **not existing directory names**. Identify actual reusable consumer/dispatch/template entry points in the fork. Preserve WebATEM's `Hooks` and template override patterns where practical. If cleanly implemented as an additive Django app inside the same project, that is acceptable so long as it reuses the same pooled switcher session, command dispatcher, and WebSocket state.

### 9.4 Development, packaging, and testing

Reuse the existing project toolchain. Its README documents:

```powershell
npm install
npm run build:css
pip install -e ".[test]"
python -m webatem
python -m pytest tests/ -q
```

Use a Python virtual environment on Windows. Do not build a new installer or updater in V1; preserve the existing release/launcher path until a concrete limitation requires changes. Record the base WebATEM commit and `bmdwire` dependency version in `docs/webatem-capability-audit.md`, so upstream changes can be evaluated deliberately.

**Security boundary:** WebATEM can expose its control page on a LAN and has no built-in login. Retain its same-origin WebSocket protections, deploy on a trusted production network, and do not add an unauthenticated separate network control endpoint.

## 10. Nonfunctional requirements

### 10.1 Reliability

- No direct live command should execute while disconnected, while its target is in an unresolved conflict, or when source validation fails.
- Switching operations must be serialized per controlled output; no rapid double-click queues that replay old choices.
- Every output panel must consume WebATEM’s shared live-state stream; server-side queue changes must be broadcast to all operator clients.
- A failed command must never leave a green/red indicator falsely claiming confirmed state.
- Reuse WebATEM’s existing session and WebSocket cleanup paths; do not leak per-tab observers or independent ATEM sessions.

### 10.2 Usability

- Windows 11 hosts WebATEM; dashboard runs in a local or LAN browser. Keyboard/mouse first; touch-friendly button sizes are encouraged.
- Dark operator-friendly interface; use clear red = on-air, green = preview, with textual labels.
- Stable location and ordering of buttons; do not reshuffle during a live event because a source became temporarily unavailable.
- Preserve the selected display mode, output titles, and panel order across restarts.
- Give explicit confirmation that local settings were saved or hardware changes were applied.
- A browser is the primary UI, **not a separate install dependency**. No cloud account, internet connectivity, or subscription is required once the local WebATEM server is installed.

### 10.3 Performance

- Source selection and click feedback should feel immediate to operators, while distinguishing **pending** from **confirmed**.
- Device callbacks should update displayed state promptly; measure latency on the actual network and switcher.
- Startup discovery must not block the browser UI or WebATEM’s event loop.
- Keep lightweight timestamped diagnostic logs with connection changes, command targets, observed outcomes, and errors; avoid logging private network credentials (none should be needed).

### 10.4 Security and operational boundaries

- Reuse WebATEM’s existing discovery, remembered-device list, and manual-IP controls. Restrict UI access through the trusted production network, not a new duplicate discovery policy.
- WebATEM already serves pages to devices on its configured network interface. Do not add new externally exposed endpoints; honor the launcher’s interface binding and WebSocket origin protections.
- Do not infer or claim ATEM-level permission controls. WebATEM has no built-in login; anyone with access to the control UI on the trusted production LAN can issue live commands in the chosen mode.
- Treat XML/media/full switcher state backups as an ATEM Software Control responsibility in V1.

---

## 11. Acceptance tests / definition of done

Tests must run with WebATEM’s **existing fake protocol/test fixtures first**, then on actual hardware during a controlled rehearsal. No automatic integration tests should transmit live switcher commands without a conspicuous operator opt-in.

| ID | Test | Pass condition |
|---|---|---|
| A01 | Existing WebATEM connection | Selecting discovered/manual-IP device gives accurate model, inputs, and output count without a second ATEM session |
| A02 | Names imported | All discovered source buttons show current ATEM short/long names |
| A03 | External rename | Renaming a source in ATEM Software Control refreshes dashboard label |
| A04 | Internal SAVE | Renaming `Output 1` changes local heading but sends no ATEM command |
| A05 | Staged hardware rename | Typing a new ATEM input name sends no command until UPDATE ATEM |
| A06 | Hardware UPDATE | Only changed, validated fields are sent; success and failures reported |
| A07 | Stale edit conflict | External edit to a staged field blocks accidental overwrite |
| A08 | Virtual Preview | Shared server queue changes for an AUX-controlled output; physical output remains unchanged |
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
| A21 | External M/E reassignment | M/E panel designation follows confirmed hardware state or warns |
| A22 | Network outage | Controls disabled; stale status visible; reconnect resyncs hardware |
| A23 | Restart | Dashboard settings retained server-side; no automatic hardware routing commands |
| A24 | Unsupported sources | Cannot route to sources unavailable for that destination |
| A25 | Source name collision | IDs distinguish sources with same name |
| A26 | Partial MASTER failure | Actual output states reconciled; successful/failed outputs shown |
| A27 | Empty media player | Button state follows discoverable availability and configured visibility rule |
| A28 | Settings M/E move | Diff shows both impacted physical routes; applies only on UPDATE ATEM |
| A29 | M/E next transition keys tied | Dashboard background CUT doesn't accidentally change keyer on-air state |
| A30 | Clean install | Existing WebATEM Windows launcher with new dashboard works on fresh Windows 11 test PC |
| A31 | Multi-operator shared preview | Two browser clients show the same virtual Preview after either one changes it |
| A32 | Concurrent cuts | Simultaneous commands from browser clients are serialized or rejected clearly; no stale replay |
| A33 | Existing WebATEM regression | Original control page, settings, audio, media pool and other relevant functions remain operational |
| A34 | Staged settings isolation | UPDATE ATEM staging applies only in new dashboard settings; original WebATEM settings behavior remains intact |
| A35 | Protocol reuse | No second UDP ATEM session/connection stack introduced by our extension |

### Reuse and hardware spike that must be completed first

Before designing more UI, Claude must inspect the actual fork and create a **capability audit** showing the files/functions/message payloads already responsible for:

1. Network discovery, manual IP, connections/reconnections, and current device selection.
2. Input IDs, names, type and source availability; AUX output identity and routes.
3. Real M/E Program/Preview, CUT, next-transition BKGD/key selection.
4. USK count, fill/key source, on-air state and on-air commands.
5. Media player, color generator, internal-source availability.
6. WebSocket event delivery; multi-operator behavior; extension hooks/template structure.
7. Saved settings, browser/launcher options, packaging and existing test fixtures.

Then run the existing test suite before modifications. On the actual target ATEM in an off-air rehearsal, validate model compatibility, the physical OUT 1–3 mapping, hardware source changes, keyer state, and **background-only M/E CUT**. Do not proceed to live-service deployment until this last test is safe and repeatable.

Write the audit to `docs/webatem-capability-audit.md`, recording base commit, library versions, implementation paths, verified behavior, gaps, and which features need no additional code. This is the V1 **go/no-go** gate. Not every assertion in the WebATEM design brief is independently confirmed by that brief; it is primarily a branding/design assignment.

## 12. Work plan and development order — additive WebATEM extension

### Milestone 0 — Baseline and capability audit

- Clone/fork WebATEM; establish Windows Python virtual environment and CSS build.
- Run `python -m pytest tests/ -q` on untouched base and launch existing control page.
- Identify existing dispatch/state/template paths for every inherited feature.
- Document base commit, existing compatibility issues, and real-device tests needed.
- Validate initial target switcher off-air and understand M/E next-transition/USK behavior.

### Milestone 1 — New dashboard shell with inherited state

- Add dedicated Three-Output Dashboard page in the existing browser app.
- Use discovered input/source names, current AUX routing, and real M/E state.
- Follow WebATEM’s dark theme and current operator button components.
- Do not write protocol code or change existing live commands.

### Milestone 2 — Virtual Preview / independent CUT

- Add shared server-side queued Preview for two controlled AUX destinations.
- Implement independent Preview + CUT state machine with authoritative AUX feedback.
- Add Direct / Preview + CUT Only preference and tests.
- Verify multiple browser operators see one consistent queued selection.

### Milestone 3 — M/E and keyer integration

- Bind the selected M/E output to existing M/E Program/Preview/CUT commands.
- Safely perform background-only CUT without accidentally transitioning keys.
- Add discovered upstream-key on-air toggles with live fill labels.
- Validate on device; leave existing advanced keyer settings intact.

### Milestone 4 — Dashboard settings and MASTER CUT

- Add Internal Settings → SAVE, using server-side persistence.
- Add staged ATEM Settings → UPDATE ATEM via existing rename/routing actions.
- Add dynamic output headings, assignment warnings, MASTER CUT, and persistent safety choice.
- Serialize/validate commands across operators and report partial transitions.

### Milestone 5 — Regression, rehearsal and release

- Extend existing pytest/fake device fixtures; ensure current WebATEM features still work.
- Test disconnect/reconnect, external changes, simultaneous operators and recovery.
- Reuse WebATEM Windows launcher/build; document changes, licensing, and upstream sync.
- Approve only after supervised rehearsal with actual ATEM hardware.

**AI coding handoff:** Have the coding assistant read the full current WebATEM repository, this blueprint and the design brief. Begin with Milestone 0 and **do not implement substitute plumbing already available upstream**. Require each milestone to identify reused functions, new functions, tests, and remaining hardware-dependent assumptions.

## 13. Future versions (not V1)

### V2 — Workflow improvements

- Service/scene presets such as Worship, Sermon, Announcements, Communion.
- Alternate transition types for the real M/E only (AUTO, MIX, etc.).
- Optional DSK on-air toggles and media-player controls.
- Read-only / Live operator mode (requested as future rather than V1).
- Configurable keyboard shortcuts and volunteer profiles.
- More than three output panels, with actual device capability discovery.
- Optional advanced master safety and selective CUT-all groups.

### V3 / V4 — Video and multiview

- Receive the Constellation's physical 16-window SDI multiview through a compatible **SDI capture device** or **SDI-to-IP encoder**.
- Crop and map its source tiles into the dashboard.
- Show Program and Preview thumbnails for each Output, plus remaining inputs.
- Potentially allow clicking a thumbnail to queue Preview.
- No assumption that the ATEM provides native multiview video via its Ethernet control connection; it does not advertise that capability on this model.
- Design the video ingest interface to accommodate local capture or a third-party encoded network stream.

**V1 must not require new video capture, FFmpeg, a media decoder, or an encoder.** WebATEM’s existing **media-pool still thumbnails are not live multiview video**; do not conflate the two. Maintain a clean source-ID data model now so live thumbnails can attach to the same IDs later.

---

## 14. Known risks, assumptions, and decisions to validate

| Topic | Requirement / interpretation | Verification |
|---|---|---|
| M/E ownership | One dashboard panel acts as the managed M/E output; multiple physical connectors may carry the same M/E Program | Inspect live routes, handle none/multiple by explicit selection |
| Hardware vs virtual Preview | Only the M/E has a true hardware Preview | Confirm in application state model |
| Background-only CUT | Do not flip USKs accidentally when next-transition keys are tied | **Critical hardware test** |
| Program direct mode | Software UI mode only, not an ATEM-wide restriction | Confirm ATEM panel remains independent |
| Master synchronization | Best-effort command burst, not frame-perfect | Measure during rehearsal |
| Empty media player | Source can exist even with no usable image loaded | Discover player availability; gray out as needed |
| Local output names | ATEM has no applicable friendly destination labels for this workflow | Store server-side by device and physical connector identity |
| Editing an ATEM field | Must be staged and UPDATE ATEM committed | Check per-field conflict and partial success behavior |
| M/E reassignment | Changes at least the source routed to the new destination; old destination needs an explicit replacement | Prompt with full route diff |
| Discovery scope | Only data exposed by WebATEM / its protocol layer is presently usable | Audit current state payload; extend only missing fields |
| Protocol and device compatibility | Upstream author mainly validates 1 M/E Constellation HD | Validate 1 M/E Constellation 4K + firmware and pinned bmdwire version |
| V3/V4 video over network | Requires external encoder, not native Ethernet multiview feed | Out of current scope |

### Questions intentionally deferred rather than silently decided

1. The **MASTER safety slider** can be shown as `Protected` (confirmation on each MASTER CUT) versus `Instant`; this is the current proposal. Test usability before locking it in.
2. If the switcher routes M/E Program to more than one physical output, V1 requires the operator to choose which of OUT 1–3 is the **dashboard’s managed M/E panel**; identical feeds on other connectors are valid, but dashboard ownership must be unambiguous. It must not guess.
3. Source visibility for empty media players should favor consistency (disabled over disappearing). Verify available metadata on the target firmware.
4. When manually moving M/E Program to a different output, the user must explicitly select the old destination's replacement source. Do not infer it.

These are design refinements, not blockers to starting the WebATEM capability audit and hardware-validation milestone.

---

## References and validation sources

- **[W1] WebATEM repository and current README:** https://github.com/lucas-romanenko/webatem — features, architecture, device reports, development, testing, packaging, hosting hooks, licensing, and security.
- **[W2] Source document:** `DESIGN_BRIEF.md` supplied alongside this specification — design/branding brief, including established dark control-surface palette, style tokens, frontend asset paths, and launcher expectations. It is not a substitute for inspecting the current source code or its tests.
- **[W3] WebATEM architecture in README:** Django/Channels + Alpine.js + WebSocket + `atemwire`/`bmdwire`, with connection pooling and state fan-out; the full implementation must be verified in the local fork.
- **[H1] Blackmagic ATEM 1 M/E Constellation 4K technical specifications:** https://www.blackmagicdesign.com/products/atemconstellation/techspecs/W-APS-40
- **[H2] ATEM operation manual / next-transition behavior:** Current manual for the selected firmware and device; used to verify BKGD-only CUT requirements during hardware testing.

**Source hierarchy:** Actual checked-out source code and tests > current upstream README/docs > design brief > extrapolated API assumptions. Verify uncertain hardware behavior against an off-air device before release.

## Final definition of V1

**V1 is complete when an operator launches the existing WebATEM application on Windows, opens the new three-output browser dashboard, selects a connected ATEM using WebATEM’s device discovery, sees its real input names, controls three physical outputs with Preview/Program/CUT, independently toggles discovered upstream keys on the managed M/E output, executes MASTER CUT with reliable partial-failure reporting, stages dashboard hardware edits behind UPDATE ATEM, saves dashboard-local settings separately, and sees state consistent across browser operators and with the hardware — without duplicating WebATEM’s already-working protocol, launcher, and full-control functionality.**
