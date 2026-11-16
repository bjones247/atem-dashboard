# ATEM Control Dashboard
## Product and Technical Blueprint — Version 0.4

**Prepared:** November 16, 2026  
**Status:** Development specification / proposed implementation  
**Initial validation device:** Blackmagic Design ATEM 1 M/E Constellation 4K; requirements must not depend on its current source assignments or naming  
**Platform:** Windows 11  
**Scope:** Version 1 (control only; no video capture or thumbnails)

> **Purpose:** This is the single source of requirements for creating the application, whether implemented manually or through an AI coding assistant in VS Code. The goal is a reliable live-production controller, not a replacement for every feature of Blackmagic ATEM Software Control.
>
> **Implementation language:** “MUST” = required for V1, “SHOULD” = preferred for V1 if practical, “FUTURE” = explicitly out of scope. Assumptions marked **VERIFY ON DEVICE** must be proved using the exact switcher, firmware, and SDK before live-service use.

---

## 1. Vision and scope

Build a native Windows dashboard with **three independently operated outputs**. Each output has **PREVIEW**, **PROGRAM**, and **CUT** controls. For V1, two outputs use the ATEM's routable auxiliary SDI outputs to simulate a Preview/Program workflow in software. One selected output receives the switcher's real **M/E Program**, giving it genuine hardware Preview/Program and access to the keyers discovered on that M/E. The application must discover all input labels, source IDs, output routing, and keyer assignments from the connected ATEM rather than assuming a venue-specific setup.

The application should automatically read the ATEM's input names and current hardware state. Its **Settings** area differentiates locally saved preferences from settings that actually change the ATEM. The **Dashboard** always operates live when connected.

### 1.1 Explicit V1 goals

1. Connect over Ethernet by ATEM IP address and reconnect safely.
2. Discover the switcher's available inputs, internal sources, output destinations, M/E, upstream/downstream keyers, and media-player state as exposed by the SDK.
3. Show three output panels tied specifically to physical **OUT 1, OUT 2, OUT 3** for this release.
4. Support independent Preview and Program source selection for each output.
5. Support individual CUT actions and a MASTER CUT across all three outputs.
6. Give the M/E-assigned output on-air toggles for **all upstream keyers discovered on that M/E** (four on the initial validation device) and display each key's configured fill source label.
7. Read ATEM input short/long names and allow deliberate changes to those names through **UPDATE ATEM**.
8. Offer user-controlled output names and preferences saved locally through **SAVE**.
9. Keep the dashboard synchronized with changes made from ATEM Software Control or the hardware panel.
10. Operate without SDI capture hardware, a multiview stream, cloud services, or subscriptions.

### 1.2 Explicitly excluded from V1

- USB-C control (network/IP only).
- Chroma/luma/key mask configuration, media uploading, media playback editing, audio mixing, DVE control, and downstream keyer **control** (these settings may be read for discovery).
- Video monitoring or thumbnails.
- Multiple independent physical M/E engines, dissolves on virtual outputs, or guaranteed frame-accurate switching among outputs.
- Read-only/live operating mode.
- Automation presets, service scenes, scheduling, and remote multi-user control.
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

**Do not hard-code device capabilities into the core integration layer.** Hardware discovery should enumerate what the connected switcher actually provides; the V1 UI presents only the first three configured output destinations and their supported sources. See [S1](#references-and-validation-sources).

---

## 2. Device-derived source and output mapping

### 2.1 Input discovery: no venue-specific baseline

**The specification intentionally contains no physical-input assignment table.** A connected ATEM is authoritative for its actual input inventory. There must be no built-in assumptions such as a particular computer, camera, lyrics feed, or signal on any numbered connector.

On connection, discover and populate the source catalog from the device:

- Physical input/source IDs, connector numbers (if exposed), source type, short name, and long name.
- Internal sources supported by the device, such as Black, color generators, and media players.
- Availability for the relevant M/E and AUX destinations.
- Names and assignments of keyer fill/key sources by joining their hardware source IDs to the same discovered source catalog.

Any examples elsewhere in this document are **illustrations only**. They are not initial configuration values and must never be automatically written to the ATEM. Input IDs, not labels or their position in a sample list, control routing. ATEM short names may be limited to four ASCII characters; verify exact naming constraints against the installed SDK.

### 2.2 Physical outputs and software roles

For V1, the app displays **three panels associated with physical OUT 1, OUT 2, and OUT 3**, subject to the device supporting those routable outputs. Their purpose, names, and current source assignments are **not predetermined**.

| Physical connector | Default local heading | Dashboard role at connection |
|---|---|---|
| OUT 1 | Output 1 | Discovered from its current hardware routing |
| OUT 2 | Output 2 | Discovered from its current hardware routing |
| OUT 3 | Output 3 | Discovered from its current hardware routing |

- Internal Settings lets an operator assign a friendly name to each output; these names exist only in this app.
- Determine which configured physical output currently carries **M/E Program** by reading the ATEM's routing. That panel becomes the **Hardware M/E** output; remaining panels are **Virtual AUX** outputs.
- If no configured output (or multiple configured outputs) carries the relevant M/E Program source, show a configuration warning and require the operator to resolve the assignment instead of assuming a designated output.
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

### 3.2 Software layers

```text
WPF Dashboard / Settings screens
         |
View models + immutable application state
         |
Application command handler / transition coordinator
         |
IAtemController (device-independent abstraction)
         |
Blackmagic SDK adapter (C# / COM interop, callbacks)
         |
IP / Ethernet -> ATEM switcher

Separate: Local Settings Repository -> JSON file
Separate: Diagnostics / activity log
Separate: Simulated ATEM adapter for testing without hardware
```

**Recommended stack:** C# with a current supported .NET LTS release, WPF/XAML, MVVM pattern, Blackmagic ATEM SDK, and JSON configuration. Choose the exact .NET/runtime and SDK versions during project bootstrap after verifying SDK compatibility. Blackmagic supplies a Windows C# “Simple Switcher” example. See [S3](#references-and-validation-sources).

**Design rule:** UI code must not call SDK COM interfaces directly. Use an adapter that presents typed state snapshots, events, and commands. SDK callbacks must be marshaled safely to the UI thread. Serialize commands that affect a shared output or the M/E; manage COM object lifetime and reconnection explicitly.

---

## 4. Screens and navigation

Exactly two major screens in V1:

1. **Dashboard** — all live switching and keyer operations.
2. **Settings** — local application configuration and staged hardware edits, split into *Internal Settings* and *ATEM Settings*.

A persistent top status bar MUST show: application name, current ATEM connection state, device model or display name, IP address, active screen, and an unmistakable warning if disconnected or configuration is inconsistent.

### 4.1 Dashboard: desktop wireframe

Target a 1920×1080 Windows control laptop/display. Adapt gracefully to smaller windows by scrolling or stacking panels without rearranging source identity unexpectedly.

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
- Button labels update if another operator renames the input in ATEM Software Control.
- If a source ID disappears or becomes unavailable, mark it unavailable and disable its selection; never silently substitute a different source.

### 4.3 Program Selection Mode (Internal Setting)

| Mode | PREVIEW click | PROGRAM click | CUT click |
|---|---|---|---|
| **Direct** | Selects next source | Immediately switches that output live | Transitions to queued preview |
| **Preview + CUT Only** | Selects next source | Indicator only; no click action | Required to change the live source |

**Default: Preview + CUT Only.** This is **unique to our dashboard**, not an ATEM-wide lockout. External ATEM Software Control or physical-panel operations remain unrestricted. The setting persists across app restarts and applies to all three output panels.

### 4.4 Upstream keyer strip (M/E output only)

Only the output currently assigned M/E Program shows the strip:

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

**Master safety slider:** A persistent on-screen slider, not a momentary ARM button that resets after every action. Recommended initial design: `PROTECTED` prompts before each master action; `INSTANT` executes on click. Store the selected mode locally. This is a UX decision that should be tested with operators before final styling. Either way, the slider stays in the chosen state until changed.

### 4.6 Dashboard live status behavior

- Connection lost: immediately disable live controls and show the last observed state as **STALE / DISCONNECTED**, not current truth.
- Command pending: show a brief pending indicator; ignore rapid repeated commands targeting the same bank until state is reconciled.
- Command rejected/time-out: display a concise error, query the device state, and correct the UI.
- Changes from ATEM Software Control or the chassis: update the affected red/green selections and key statuses automatically.
- M/E Program display represents the M/E background source plus separate keyer status; do **not** suggest that the input label alone fully describes the keyed composite.

---

## 5. Settings screen

Use two tabs: **Internal Settings** and **ATEM Settings**. They have independent change buffers, independent validation, and independent save actions.

### 5.1 Internal Settings — `SAVE`

These settings belong to our application and **must not** send configuration updates to the ATEM.

| Setting | Type / behavior | V1 default |
|---|---|---|
| ATEM IPv4/host address | Text, validate on connect; stored locally | Empty until configured |
| Automatically reconnect | Boolean | On |
| Remember device | Boolean | On |
| Local friendly output name | One per output | Output 1, Output 2, Output 3 |
| Output display order | Ordered list | OUT 1, OUT 2, OUT 3 |
| Button label style | Short / Long / Both | Both where space allows |
| Source visibility | Per source ID/category | Supported sources shown |
| Source ordering | Sort/order preferences | Physical inputs then internal sources |
| Program Selection Mode | Direct / Preview + CUT Only | Preview + CUT Only |
| Master CUT Safety | Protected / Instant | Protected |
| Hide empty media player sources | Boolean | Off (disable unusable) |

**SAVE contract:** Validate all local fields; persist them to a versioned JSON configuration file in an appropriate Windows per-user application data folder; atomically replace the file; update the dashboard immediately for local-only names and presentation preferences. Display `Saved` or a specific error.

The `Connect` button may use an unsaved IP to test a connection, but connecting does not imply saving that address. The next startup uses the last **saved** address.

### 5.2 ATEM Settings — `UPDATE ATEM`

These settings are read from the device and must be deliberately committed back to hardware.

| Editable field | Source of initial value | Commit effect |
|---|---|---|
| Input short name | ATEM | Calls ATEM setter; max 4 ASCII characters |
| Input long name | ATEM | Calls ATEM setter; validate per SDK |
| M/E Program destination among OUT 1–3 | Observed OUT source routing | Updates affected AUX source assignments |
| Physical output source mapping / initial assignment | Current hardware output routes | Changes hardware routing when explicitly committed |

Read-only information in this tab may include model, video mode, all discovered inputs, USK/DSK status and configuration, media player assignments, color sources, and output source mapping.

**UPDATE ATEM contract:**

1. When opening the tab, capture a baseline snapshot of editable hardware fields.
2. User edits fields in a **staging buffer**. Do **not** alter hardware yet.
3. Show a **Changes to ATEM** diff: old value → proposed value; clearly identify any change that might affect an on-air output.
4. Before committing, re-read the latest hardware values. If an edited field has changed externally since staging, **block that field**, show the conflict, and require reload/review. Unedited fields must never be written back.
5. Ask for explicit confirmation for output-routing changes (they may affect screens immediately).
6. Apply only validated changes, recording per-field success/failure; the SDK cannot necessarily make multiple changes atomic.
7. Re-query authoritative ATEM state, update the UI, and show an accurate outcome, including partial success.
8. Never attempt a silent hardware rollback or restore a stale full-switcher snapshot after a failure.

**M/E reassignment nuance:** If the user reassigns M/E Program from one managed output to another, the formerly M/E-fed output needs a direct source assignment. The confirmation must show **both** affected outputs and explicit resulting routes. Do not guess what should replace M/E Program on the old output. Permit cancellation without any hardware change. This operation is not guaranteed to be frame-atomic.

**Physical output count in V1:** The UI is restricted to three panels tied to OUT 1, OUT 2, and OUT 3. Future versions may support a variable number of configurable output panels based on model capability.

### 5.3 Connection and discovery information

After connection, display a discoverable **Device Information** section (read-only):

- Product/model name, reachable IP, firmware/version information **when exposed**.
- Available external inputs, input IDs, short/long names, port type, and source availability.
- Available routable physical outputs and current assignments.
- M/E blocks, current Program/Preview, transition state and next-transition selection (if exposed).
- USK and DSK count, current types, fill/key source IDs, on-air state, and key settings where available.
- Media player count, current still/clip assignment and metadata where available.
- Color generator sources and relevant values where available.
- Other discovered capabilities only for diagnostic visibility, without V1 edit controls.

**Do not promise a complete clone of all ATEM software settings.** The requirement is to retrieve and display *all relevant settings exposed and supported by the installed SDK*. Mark unsupported/unknown fields as such rather than fabricating defaults.

---

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

The precise C# types may differ, but the distinctions are mandatory.

### 6.2 Single source of truth

| Data | Owner |
|---|---|
| Input names, physical source IDs | ATEM |
| Current AUX routes | ATEM |
| Real M/E Program and Preview | ATEM |
| Upstream key configuration and on-air states | ATEM |
| Local output friendly names | Application settings |
| Source button visibility and order | Application settings |
| Virtual AUX Preview selection | Application runtime state |
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

## 7. State synchronization and startup rules

### 7.1 Connection sequence

1. Launch app; load and validate local JSON preferences.
2. If auto-reconnect is enabled and an address was saved, connect; otherwise show Connect screen/status.
3. Establish SDK connection using supplied IP; verify that the switcher is responsive.
4. Discover capabilities, input catalog, output routes, M/E state, keyer state, and media player metadata.
5. Identify which of physical OUT 1–3 currently routes M/E Program. Detect **none** or **multiple** assignments and show a clear configuration warning instead of guessing the intended M/E owner.
6. Initialize each virtual output's live source from the actual AUX assignment.
7. Initialize virtual Preview conservatively: if a valid previous session selection exists for the **same device and output**, it may be restored as a **queued selection only**; otherwise set Preview equal to current live source so the first CUT is a no-op until the operator makes a deliberate Preview choice.
8. Register SDK callbacks for relevant source, route, M/E, and keyer changes; marshal updates to UI safely.
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
- Retry connection with bounded backoff; do not flood the device/network.
- On reconnect: re-discover and re-read all hardware state rather than replaying cached commands.
- Never automatically reapply old hardware output assignments or input names.
- Preserve valid virtual Preview choices only when doing so is safe, for the same hardware/connector, and visibly label them queued.
- If another controller changed routing while disconnected, display the changed state rather than trying to force the previous state back.

---

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
  command AUX.SetInputSource(sourceId)
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
  command ME.SetPreviewInput(sourceId)
  show selection only after device acknowledgement / callback

SelectProgramDirectME(sourceId):
  only when Direct mode
  command ME.SetProgramInput(sourceId)
  resynchronize ME Program/Preview from hardware

CutME():
  ensure expected ME is the one assigned to this panel
  verify transition/next-transition state permits background-only CUT
  execute ME.PerformCut()
  read confirmed ME Program/Preview and keyer on-air status
```

**Critical hardware acceptance condition:** Blackmagic's *next-transition* selections can tie upstream keys to a transition. The dashboard's ordinary M/E CUT is intended to transition the **background only**, leaving all four USK on-air states unchanged. During the hardware spike, determine the correct SDK sequence for ensuring `BKGD-only` next-transition selection; perform it safely and avoid overwriting simultaneous changes made by another operator. If this cannot be done reliably, V1 must warn/block rather than silently turning keys on/off. Do not simply assume that calling `PerformCut()` can never affect keyers. See [S4](#references-and-validation-sources).

### 8.5 Upstream key toggle

```text
ToggleUSK(keyId):
  ensure connected, currently assigned to this M/E, not pending
  desired = !observedOnAir
  call Key.SetOnAir(desired)
  wait for Key.GetOnAir()/callback confirmation
  on error: re-read state, show failure
```

Use the SDK's keyer `GetInputFill`, `GetInputCut`, `GetOnAir`, and `SetOnAir` interfaces where supported. See [S5](#references-and-validation-sources).

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
  if all succeed: update virtual Preview swap states + ME observed state
  if partial failure: show which outputs changed and which did not;
                      refresh all output states; do not auto-rollback
```

**Timing requirement:** Favor a responsive, consistent command path but do **not** claim simultaneous frame-boundary cuts. Do not use parallel calls to the same COM object if SDK threading rules do not permit them. Document measured switching skew in the hardware integration tests.

---

## 9. SDK integration contract and implementation guidance

Prefer Blackmagic's official **ATEM Switchers SDK**, with a C# Windows project. Do not let a specific SDK version number become a permanent requirement; use a verified version appropriate to the firmware installed on the connected switcher. As of November 2026, Blackmagic's developer download page lists SDK **11.0.1**, released November 3, 2026, but compatibility must be verified on the target machine. See [S3](#references-and-validation-sources).

### 9.1 Relevant documented SDK surface

| Need | Relevant SDK concepts / methods |
|---|---|
| Connect to IP | `IBMDSwitcherDiscovery::ConnectTo` |
| Enumerate sources | `IBMDSwitcher::CreateIterator`, input iterator, `GetInputId` |
| Read source names | `IBMDSwitcherInput::GetShortName`, `GetLongName` |
| Rename sources | `SetShortName`, `SetLongName` |
| Get/set AUX routing | `IBMDSwitcherInputAux::GetInputSource`, `SetInputSource` |
| Validate selectable source | Input availability masks for AUX and M/E |
| Get/set M/E background | `IBMDSwitcherMixEffectBlock::GetProgramInput/SetProgramInput`, `GetPreviewInput/SetPreviewInput` |
| Perform M/E CUT | `IBMDSwitcherMixEffectBlock::PerformCut` |
| Inspect/control upstream keyers | `IBMDSwitcherKey::GetInputFill`, `GetInputCut`, `GetOnAir`, `SetOnAir` |
| Subscribe to changes | SDK `AddCallback`/`RemoveCallback` on the relevant objects |

The exact COM interop signatures, callback event enum names, and M/E next-transition methods **must** be taken from the SDK files installed in the project; do not generate signatures by guesswork. See [S2], [S3], [S5], and [S6](#references-and-validation-sources).

### 9.2 Implementation interfaces (illustrative, not SDK code)

```csharp
public interface IAtemController
{
    Task ConnectAsync(string address, CancellationToken cancellationToken);
    Task DisconnectAsync();
    Task<AtemSnapshot> ReadSnapshotAsync(CancellationToken cancellationToken);

    Task RouteAuxAsync(long outputId, long sourceId, CancellationToken cancellationToken);
    Task SetMePreviewAsync(long meId, long sourceId, CancellationToken cancellationToken);
    Task SetMeProgramAsync(long meId, long sourceId, CancellationToken cancellationToken);
    Task CutMeBackgroundOnlyAsync(long meId, CancellationToken cancellationToken);
    Task SetUsKeyOnAirAsync(long keyId, bool onAir, CancellationToken cancellationToken);
    Task RenameInputAsync(long sourceId, string shortName, string longName,
                          CancellationToken cancellationToken);

    event EventHandler<AtemStateChangedEventArgs> StateChanged;
    event EventHandler<AtemConnectionChangedEventArgs> ConnectionChanged;
}
```

`CutMeBackgroundOnlyAsync` deliberately encapsulates the keyer/next-transition safety requirement; it must not simply call `PerformCut` blindly. The listed C# types are a proposed abstraction, not ready-to-compile SDK method signatures.

### 9.3 Suggested repository layout

```text
AtemDashboard/
  README.md
  docs/
    ATEM_Control_Dashboard_Blueprint.md    # copy of this specification
    sdk-compatibility.md
    test-plan.md
  src/
    AtemDashboard.App/                      # WPF views, view models
    AtemDashboard.Domain/                   # state + rules
    AtemDashboard.Application/              # commands + orchestration
    AtemDashboard.Infrastructure.AtemSdk/   # official SDK adapter
    AtemDashboard.Infrastructure.Settings/  # JSON persistence
  tests/
    AtemDashboard.Domain.Tests/
    AtemDashboard.Application.Tests/
    AtemDashboard.Fakes/                    # simulated device
    AtemDashboard.IntegrationTests/         # real ATEM, manual opt-in
```

Keep the true SDK SDK-native references and binary dependencies out of untrusted download scripts. Record the exact official SDK download and installation steps in the project README. Prefer an explicit Windows installer; test on a fresh PC with any required Blackmagic redistributables/driver packages installed.

---

## 10. Nonfunctional requirements

### 10.1 Reliability

- No direct live command should execute while disconnected, while its target is in an unresolved conflict, or when source validation fails.
- Switching operations must be serialized per controlled output; no rapid double-click queues that replay old choices.
- All callbacks that update WPF-bound state must arrive on the appropriate UI synchronization context.
- A failed command must never leave a green/red indicator falsely claiming confirmed state.
- Release COM resources and callbacks on disconnect and application shutdown.

### 10.2 Usability

- Windows 11, keyboard/mouse first; touch-friendly button sizes are encouraged.
- Dark operator-friendly interface; use clear red = on-air, green = preview, with textual labels.
- Stable location and ordering of buttons; do not reshuffle during a live event because a source became temporarily unavailable.
- Preserve the selected display mode, output titles, and panel order across restarts.
- Give explicit confirmation that local settings were saved or hardware changes were applied.
- No browser, internet, external account, or subscription should be required once installed.

### 10.3 Performance

- Source selection and click feedback should feel immediate to operators, while distinguishing **pending** from **confirmed**.
- Device callbacks should update displayed state promptly; measure latency on the actual network and switcher.
- Startup discovery should not block the UI thread.
- Keep lightweight timestamped diagnostic logs with connection changes, command targets, observed outcomes, and errors; avoid logging private network credentials (none should be needed).

### 10.4 Security and operational boundaries

- Allow connection only to an explicitly configured ATEM address in V1.
- Do not enable remote network API exposure by default.
- Do not infer or claim ATEM-level permission controls. This is a trusted production LAN application; anyone with access to the UI can issue live commands in the chosen mode.
- Treat XML/media/full switcher state backups as an ATEM Software Control responsibility in V1.

---

## 11. Acceptance tests / definition of done

Tests must run with a **fake ATEM adapter first**, then on actual hardware during a controlled rehearsal. No automatic integration tests should transmit live switcher commands without a conspicuous operator opt-in.

| ID | Test | Pass condition |
|---|---|---|
| A01 | Connect by IP | Correct device model, input count, and physical output count discovered |
| A02 | Names imported | All discovered source buttons show current ATEM short/long names |
| A03 | External rename | Renaming a source in ATEM Software Control refreshes dashboard label |
| A04 | Internal SAVE | Renaming `Output 1` changes local heading but sends no ATEM command |
| A05 | Staged hardware rename | Typing a new ATEM input name sends no command until UPDATE ATEM |
| A06 | Hardware UPDATE | Only changed, validated fields are sent; success and failures reported |
| A07 | Stale edit conflict | External edit to a staged field blocks accidental overwrite |
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
| A21 | External M/E reassignment | M/E panel designation follows confirmed hardware state or warns |
| A22 | Network outage | Controls disabled; stale status visible; reconnect resyncs hardware |
| A23 | Restart | Local settings retained; no automatic hardware routing commands |
| A24 | Unsupported sources | Cannot route to sources unavailable for that destination |
| A25 | Source name collision | IDs distinguish sources with same name |
| A26 | Partial MASTER failure | Actual output states reconciled; successful/failed outputs shown |
| A27 | Empty media player | Button state follows discoverable availability and configured visibility rule |
| A28 | Settings M/E move | Diff shows both impacted physical routes; applies only on UPDATE ATEM |
| A29 | M/E next transition keys tied | Dashboard background CUT doesn't accidentally change keyer on-air state |
| A30 | Clean install | Runs on a fresh Windows 11 test machine with documented dependencies |

### Hardware spike that must be completed first

Before polishing the visual UI, build a small console or diagnostic harness that proves, on the initial validation ATEM (and uses discovery rather than assumptions):

1. SDK connection over Ethernet.
2. Enumeration of real external inputs, black/color/media sources, short/long names, AUX outputs, M/E, USKs, and DSK.
3. Reliable hardware updates from input name changes and external source selections.
4. Correct mapping of **physical OUT 1–3** to the discovered AUX output controls.
5. Safe background-only M/E CUT while keyers are configured/tied in various ways.
6. A working process for assigning M/E Program to any one of the three managed outputs and moving it under explicit confirmation, without assuming its initial destination.

This spike is a **go/no-go gate** before full app construction. Record actual method calls, observed behavior, any compatibility limitations, and SDK version in `docs/sdk-compatibility.md`.

---

## 12. Work plan and development order

### Milestone 0 — Validate hardware integration

- Install official SDK and build a minimal SDK client.
- Enumerate and log real device capabilities and current state.
- Prove AUX routing, M/E Preview/Program, M/E background-only CUT, keyer on-air control, source labels, and callbacks.
- Do not proceed until the M/E keyer safety behavior is understood.

### Milestone 1 — Core app skeleton

- WPF window with Dashboard and Settings tabs.
- Clean application/domain/SDK architecture and a fake device adapter.
- Connection status and source catalog rendering.

### Milestone 2 — Settings and persistence

- Local Internal Settings with SAVE.
- ATEM Settings with staged edits, diff, validation, UPDATE ATEM, and hardware conflict checks.
- Dynamic output headings and input labels.

### Milestone 3 — Independent control

- Virtual Preview/Program for whichever two configured outputs are *not* assigned M/E Program.
- Native Preview/Program for M/E output.
- Direct and Preview + CUT Only modes.
- Individual CUT and keyer toggles.

### Milestone 4 — Master operations and hardening

- MASTER CUT and persistent safety behavior.
- External-state synchronization, reconnection, diagnostics, and failure handling.
- Rehearsal testing on real switcher; verify no harm to normal ATEM Software Control operation.

### Milestone 5 — Release

- Package Windows installation, document dependencies, and write operator instructions.
- Verify cold start, device restart, unplugged network, partial failures, and external-controller activity.

**AI coding handoff:** Have the coding assistant implement **one milestone at a time**. Require compilable code and passing fake-adapter tests at every milestone. Have it read this file and the installed official SDK headers/sample projects before generating the COM adapter. Require demonstration of actual hardware behavior for uncertain SDK calls; do not accept invented method names.

---

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

**V1 must not require video capture, FFmpeg, a media decoder, or an encoder.** Maintain a clean source-ID data model now so video thumbnails can later attach to the same IDs.

---

## 14. Known risks, assumptions, and decisions to validate

| Topic | Requirement / interpretation | Verification |
|---|---|---|
| M/E ownership | One physical output among OUT 1–3 carries M/E Program | Inspect live AUX routing, handle none/multiple |
| Hardware vs virtual Preview | Only the M/E has a true hardware Preview | Confirm in application state model |
| Background-only CUT | Do not flip USKs accidentally when next-transition keys are tied | **Critical hardware test** |
| Program direct mode | Software UI mode only, not an ATEM-wide restriction | Confirm ATEM panel remains independent |
| Master synchronization | Best-effort command burst, not frame-perfect | Measure during rehearsal |
| Empty media player | Source can exist even with no usable image loaded | Discover player availability; gray out as needed |
| Local output names | ATEM has no applicable friendly destination labels for this workflow | Store by physical connector identity |
| Editing an ATEM field | Must be staged and UPDATE ATEM committed | Check per-field conflict and partial success behavior |
| M/E reassignment | Changes at least the source routed to the new destination; old destination needs an explicit replacement | Prompt with full route diff |
| Discovery scope | Only SDK-exposed data can be read | Mark unsupported fields; no guesswork |
| SDK compatibility | Depends on installed SDK/firmware | Validate exact version and sample first |
| V3/V4 video over network | Requires external encoder, not native Ethernet multiview feed | Out of current scope |

### Questions intentionally deferred rather than silently decided

1. The **MASTER safety slider** can be shown as `Protected` (confirmation on each MASTER CUT) versus `Instant`; this is the current proposal. Test usability before locking it in.
2. If the switcher routes M/E Program to more than one physical output, V1 defaults to **configuration warning / blocked M/E control** until one of OUT 1–3 is chosen as the managed M/E panel. It must not guess.
3. Source visibility for empty media players should favor consistency (disabled over disappearing). Verify available metadata on the target firmware.
4. When manually moving M/E Program to a different output, the user must explicitly select the old destination's replacement source. Do not infer it.

These are design refinements, not blockers to starting the SDK validation milestone.

---

## References and validation sources

The following are source-of-truth references for hardware capabilities and SDK functionality. Review the SDK version installed for the build; older manual examples may differ from updated interfaces.

- **[S1] Blackmagic ATEM 1 M/E Constellation 4K technical specifications:** https://www.blackmagicdesign.com/products/atemconstellation/techspecs/W-APS-40
- **[S2] Blackmagic ATEM Switchers SDK Manual:** https://documents.blackmagicdesign.com/DeveloperManuals/ATEMSDKManual.pdf (consult installed manual for exact signatures)
- **[S3] Blackmagic ATEM developer downloads and Windows C# sample:** https://www.blackmagicdesign.com/developer/products/atem/sdk-and-software
- **[S4] Blackmagic ATEM Software Control documentation (Program/Preview and transitions):** https://www.blackmagicdesign.com/products/atemsdi/software ; review *next-transition / BKGD / keyer tie* section in the current ATEM operation manual.
- **[S5] SDK `IBMDSwitcherKey`:** methods documented in the SDK manual, Keyers section (fill/key, on-air, callbacks).
- **[S6] SDK `IBMDSwitcherInputAux`:** `GetInputSource` and `SetInputSource`, documented in the SDK manual, Basic Switcher Control section.

---

## Final definition of V1

**V1 is complete when an operator can open a Windows application, connect to the ATEM over IP, see the switcher's real input names, control all three physical outputs using consistent Preview/Program/CUT interfaces, independently toggle all discovered upstream keys on the M/E output, press a single MASTER CUT, stage hardware configuration edits behind UPDATE ATEM, save internal settings separately, and trust that the on-screen status reflects what the switcher actually did.**
