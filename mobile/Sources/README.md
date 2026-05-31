# `mobile/Sources` — iOS app source (SwiftUI, mobile-client track)

The soldier's phone client. It is the **primary Tello controller**: on-device voice +
visual/AprilTag follow, commanding the Tello directly over its AP. The default follow
target is a tag-free visual "me" lock (`ObjectTracker`); an AprilTag is used to
**designate** other targets. It also renders a live tactical map and sends mission
**intent** to the laptop. Offline, GPS-less throughout — the launch point is the map
origin and the operator's compass heading (magnetometer) places the drone relative to it.
See [`../README.md`](../README.md) for build/ship and [`../../CLAUDE.md`](../../CLAUDE.md)
for the spec + hard constraints.

Two control surfaces coexist here, by design:
- **Direct phone↔Tello flight** over UDP via [`TelloCommander`](#direct-tello-flight-no-laptop)
  — the phone is the primary controller on the Tello AP (manual voice moves + the on-device
  follow loop). Per the spec the Tello is only ever driven by one controller at a time. A
  **code interlock now exists** on the laptop (`backend/app/follow/arming.py` `ArmingLock`):
  arming owner `"phone"` disarms every laptop controller, so the laptop's `FollowController` /
  approach loop can't drive the Tello while the phone flies. It backstops — but does not
  replace — the operating rule, since the phone talks to the Tello over its own AP outside
  the laptop's lock.
- **Mission intent over the WS** to the laptop (`follow_me`/`hold`/`recall`/`stop`)
  via [`WorldClient`](#contracts--networking) — the laptop owns SLAM + the shared world model.

**Status:** the direct follow/track loop and voice are wired. Voice STT runs on Apple's
**on-device `SFSpeechRecognizer`** (fully offline) — NOT Cactus (Gemma's transcribe path is
unused). The transcript is resolved by [`DronePilot.resolve`](#voice--intent): it prefers the
Cactus/Gemma model's function-call when the framework is present, and otherwise falls back to
the deterministic [`DroneIntent`](#voice--intent) keyword matcher so voice never breaks. The
[Cactus](#voice--intent) framework is gated behind `canImport(cactus)` and powers that
model-backed function-calling / vision (`DronePilot`/`CactusService`); without the xcframework
those report `UNAVAILABLE` (honest fallback, never a fake command). The Gemma model is
auto-downloaded on first launch by [`ModelDownloader`](#voice--intent) and the SETUP overlay
blocks the UI until it's present.

## Files by concern

### Entry / shell
- [`ReconCompanionApp.swift`](./ReconCompanionApp.swift) — `@main` scene; forces
  light mode (the tactical look is system-independent).
- [`ContentView.swift`](./ContentView.swift) — root layout: `StatusBar` ·
  MAP/FEED toggle (`CenterView`) · mission-link connect panel · voice bar (mic + hard
  **LAND** + ALIGN + SCOUT) · `ControlBar` (laptop intent + `ME`/`TAG`/`RE-LOCK` target
  buttons — shown **only on the Map tab**; hidden on Feed, where the phone flies the Tello
  directly so the laptop-routed buttons would be inert). Owns every `ObservableObject`
  (`WorldClient`, `VoiceController`, `ModelDownloader`, `LocationProvider`,
  `TelloDirectStream`, `FollowCoordinator`, `Localizer`, `FrameAligner`, `AnchorCamera`,
  `ScoutController`, `TelloObjectDetector`, `BuildingsStore`). Blocks the UI behind a SETUP
  overlay until the on-device model is present, then routes resolved voice actions through the
  single drone arbiter (`handle(_:)`): `follow me`/`track` → arm (takeoff) or re-lock the
  visual-me follow via `requestLock(.visualMe)`, `track_tag` → arm/re-lock onto the AprilTag
  target via `requestLock(.tag)`, `confirm` → `confirmTarget()`, `land`/`stop`/`emergency` →
  land/cut (always win), other flight → manual takeover (`pauseToManual`, pause-and-hold),
  `hold`/`recall` → mission intent to the laptop. Both `ME`/`TAG` taps and `RE-LOCK` (enabled
  only while airborne) route through `requestLock(_:)`. Drives `Localizer` from
  `LocationProvider` + `FollowCoordinator` so the map renders with no laptop, feeds
  `AnchorCamera` sightings to `FrameAligner` to co-register with the world frame, and
  `publishFollow()` pushes the follow phase + relative range/bearing + `target_type`/
  `target_label` to the laptop (via `WorldClient.sendFollowState`, fired on every
  `follow.$phase`/`$distance` change) for the dashboard's follow inset. DEBUG `-feed`
  launch arg opens FEED against `ws://127.0.0.1:8001/ws`.

### Contracts + networking
- [`Contracts.swift`](./Contracts.swift) — Swift mirror of **Contract A** (`Entity`,
  `Vec3`, type/status/source enums; `ttl_s` ↔ `ttlS`) and **Contract B** (`ServerMessage`
  discriminated union over `world_snapshot`/`mission_state`/`health`; `IntentMessage` /
  `DeviceLocation` / `FollowStateMessage` / `EntityReportMessage` / `LabelEventMessage`
  outbound). `FollowStateMessage` (wire type `follow_state`) carries the Tello's relative
  `active`/`phase`/`distance_m`/`bearing_deg` from the soldier plus `target_type`
  (`"visual_me"`/`"tag"`/nil) and `target_label` (raw id hint; nil for visual_me) — range/
  bearing only, never map coords. `EntityReportMessage` (`entity_report`) carries phone-
  localized operator + drone entities in the shared world frame, and `LabelEventMessage`
  (`label_event`) forwards operator confirm/reject decisions. Closed `Command` vocabulary:
  `follow_me`/`hold`/`recall`/`stop`/`approach`. All `Codable`. Mirrors
  [`../../backend/app/contracts.py`](../../backend/app/contracts.py)
  ↔ [`../../shared/contracts.ts`](../../shared/contracts.ts).
- [`WorldClient.swift`](./WorldClient.swift) — `@MainActor ObservableObject`,
  `URLSessionWebSocketTask`. Subscribes to the spine, publishes `entities`, `stage`,
  `lastError`, `health`, `connection`, and per-unit movement `trails` (soldier/drone,
  0.2 m jitter-filtered, capped at 80 pts). `send(_:)` delivers `Command` intent;
  `sendFollowState(active:phase:distanceM:bearingDeg:targetType:targetLabel:)`,
  `sendEntityReport(_:)`, and `sendLabelEvent(kind:source:…)` are fire-and-forget publishers
  for the follow inset, the shared-frame entities, and the label flywheel respectively.

### Direct Tello flight (no laptop)
- [`TelloCommander.swift`](./TelloCommander.swift) — `ObservableObject` singleton; the
  **single owner of the Tello control channel** (UDP → 192.168.10.1:8889, via `Network`).
  Enters SDK mode, runs a 5 s keepalive, and funnels every command (`send`/`execute`/`rc`/
  `startVideo`) so the drone is never driven by two sockets. Publishes `link`/`lastSent`.
- [`DroneFunction.swift`](./DroneFunction.swift) — the CLOSED function vocabulary the
  on-device model may call: direct-flight cases (`takeoff`/`land`/`up`/`down`/`left`/
  `right`/`forward`/`back`/`rotate_cw`/`rotate_ccw`/`emergency`/`flip`/`track`/`track_tag`/
  `confirm`) vs mission intents (`follow_me`/`hold`/`recall`/`stop`/`approach`, routed to the
  laptop). `track` is the tag-free visual-me lock, `track_tag` designates an AprilTag target,
  and `confirm` approves the shown lock. `DroneAction` resolves a function + optional
  magnitude into a clamped Tello SDK string (move 20–500 cm, rotate 1–360°) or a `Command`,
  and `fromModelOutput` parses the model's `{"function","value"}` JSON. `DroneIntent` (also
  defined here) is the deterministic keyword fallback — phrase-boundary matched, never
  invents a command; `"follow me"` → `track`/`follow_me` (visual-me), `"track the tag"`/
  `"that tag"`/`"follow that tag"` → `track_tag`.
- [`DronePilot.swift`](./DronePilot.swift) — transcript → `DroneAction`, the resolver the
  live voice path uses (`VoiceController` calls `DronePilot.resolve`). Prefers the on-device
  model's function call (closed-vocabulary system prompt built from `DroneFunction`, via a
  `CactusService`), falls back to `DroneIntent` keyword matching; unmatched speech → nil.

### Soldier-follow + visual track (on-device, direct)
- [`AprilTagDetector.swift`](./AprilTagDetector.swift) — AprilRobotics C-lib detector
  (tag36h11) on the luma plane of a 420 pixel buffer (no colour convert). Returns
  `TagDetection` with center/corners, metric distance (pose tz; 0 = unknown), bearing,
  elevation, and decision margin. `CameraIntrinsics` are estimated from the Tello FOV
  (~72° HFOV) unless overridden.
- [`ObjectTracker.swift`](./ObjectTracker.swift) — Tag-free, class-agnostic visual
  lock-and-follow ("track that boat"). The **default follow target** (the visual "me"
  lock). Vision-based: locks onto the salient object nearest frame center
  (`VNGenerateObjectnessBasedSaliencyImageRequest`, centered-box fallback), then follows
  that image region frame-to-frame with `VNTrackObjectRequest`. Records the locked box
  height as the standoff reference. On-device, not thread-safe (call from one queue).
- [`FollowController.swift`](./FollowController.swift) — pure, deterministic
  station-keeping: maps a `TagDetection` to an `RCCommand` (yaw to center, fwd/back to
  hold `targetDistance`, up/down to center vertically), with deadbands, gentle gains, and
  hard caps via `FollowConfig`. No tag / weak tag / unknown range → hover. Also defines the
  `DroneCommandSink` protocol and the `RCCommand` stick struct.
- [`FollowCoordinator.swift`](./FollowCoordinator.swift) — `ObservableObject` that runs
  the autonomous loop in two `TargetMode`s, **`.visualMe`** (`ObjectTracker`, the DEFAULT —
  the tag-free "me" lock, synthesized into a `TagDetection` so the same controller drives
  the drone) or **`.tag`** (`AprilTagDetector`, designating another target). Decode tap →
  detect (backpressured, ~10 Hz cap) → `FollowController` → `rc` sticks at a fixed ~15 Hz
  cadence. Public API: `arm(stream:mode:)` (takeoff + settle delay, default `.visualMe`),
  `requestLock(_:)` (the single entry for every initial lock / mid-flight target switch /
  re-lock — voice "follow me"/"track the tag" or the ControlBar `ME`/`TAG`/`RE-LOCK`
  buttons), `pauseToManual`/`resumeFollow` (voice/manual takeover), `beginScript` (yield the
  channel to a scripted maneuver like scout), `disarmAndLand`, `emergencyCut`, and an
  automatic lost-lock land after a long timeout. There is no `relock()` — every re-lock goes
  through `requestLock`. **Airborne target confirmation (confirm-always):** after the takeoff
  climb settles, and on every `requestLock`, the drone HOVERS in a `.confirming` (lock
  visible) / `.searching` (no lock) pre-confirm state and sends **no** follow/track `rc`
  until the operator calls `confirmTarget()`. If they never confirm: on the **initial arm**
  (`confirmTimeoutLands = true`) it auto-lands after `confirmTimeout` (30 s); on a **mid-
  flight re-lock** (`confirmTimeoutLands = false`) it falls back to a manual hover instead.
  `.visualMe` re-locks the tracker fresh at hover (the ground-level lock may not survive the
  climb). `targetType` reports `"visual_me"`/`"tag"` while locked (nil otherwise) for the
  follow-state telemetry. `Phase` = `disarmed`/`searching`/`confirming`/`following`/`lost`/
  `manual` (lowercase `label` mirrors the backend `FollowState.phase`). Publishes
  `phase`/`distance`/`bearingDeg`/normalized box corners.
  - **Continuous rc stream:** the rc loop always streams at a fixed ~15 Hz cadence — when
    following it sends `FollowController`'s sticks, and when paused/lost/manual/pre-confirm it
    streams a steady **hover** (zero sticks) rather than going dead-air, so the Tello never
    coasts on a stale command and drifts. A scripted maneuver (`beginScript`) yields the
    channel entirely (no hover ticks) so its discrete moves run uncontested.
  - **Control-state invariant:** all control state — including `mode`
    (`.visualMe`/`.tag`), `rcTimer`, `followActive`, `manualHover`, `confirmed`, `scripted` —
    is touched **only on `rcQueue`** (the comment at the field declarations states this). The
    detect tap snapshots what it needs via the queue; teardown (`disarmAndLand`/`emergencyCut`)
    runs inside the single owning `rcQueue.async` block ordered after timer cancellation, so
    the stop/failsafe path is serialized with respect to in-flight detect/rc work. Keep new
    control state on `rcQueue`; do not add cross-thread `var`s.
  - **Arming-lock model (laptop side):** the phone is the armed Tello controller; the laptop's
    `ArmingLock` represents this as owner `"phone"`, which disarms the laptop's
    `FollowController`/approach loop so they can't contend for the link.

### Soldier-commanded scout
- [`ScoutController.swift`](./ScoutController.swift) — A bounded, soldier-COMMANDED
  explore maneuver for the companion Tello. On command the pet leaves the follow
  (`FollowCoordinator.beginScript`), explores ahead in a few short legs (each capped,
  demo-safe), rotates to scan at each, then **retraces its exact path** (every recorded move
  reversed and inverted) back to the soldier and `resumeFollow()`s. The `Scout.plan(...)` step
  builder is pure and deterministic (unit-tested in `ScoutControllerTests`, no hardware);
  `ScoutStep` carries a raw Tello SDK command + wait + a retracing flag. Soldier-directed and
  bounded in distance/rotation/time — **not** autonomous pursuit. LAND/STOP
  (`FollowCoordinator.disarmAndLand`/`emergencyCut`) preempt at any time; retrace drift is
  corrected when the follow loop re-acquires its target.

### Video
Two independent paths; the FEED tab shows the **direct** one (which also hosts the
follow/track loop). The MJPEG relay path is built but not currently in the FEED toggle.
- [`TelloDirectStream.swift`](./TelloDirectStream.swift) — **direct phone↔Tello, no
  laptop.** Asks `TelloCommander` for `command`/`streamon`, receives raw H.264 on UDP
  :11111, reassembles NAL units, renders via `AVSampleBufferDisplayLayer`, and (when
  tapped) tees decoded `CVPixelBuffer`s (420, Y=grayscale) via VideoToolbox to both
  `onPixelBuffer` (the follow loop's detection) and `onPixelBufferSecondary` (the object
  detector). Honest status — never fakes a frame.
- [`TelloVideoView.swift`](./TelloVideoView.swift) — the FEED view (`TelloDirectView`):
  hosts the direct stream's display layer (`SampleLayerView`), overlays the live lock box
  (`TagBoxShape`, olive when following / red otherwise) + `TelloObjectDetector` boxes
  (cyan, label + confidence) + follow HUD (phase/dist/bearing) + Tello telemetry HUD
  (battery/alt/temp/flight time) + FOLLOW TAG / TRACK / STOP·LAND controls (with takeoff
  confirmation dialogs) + a collapsible manual SDK control pad. When `phase == .confirming`
  the control row swaps to a `confirmBar` ("TARGET ACQUIRED — CONFIRM?" with **CONFIRM** /
  **ABORT·LAND** buttons) so the operator approves the locked target while the drone hovers;
  the phase label/colour add a `.confirming` case (◆ CONFIRM TARGET?, brown). Keeps
  streaming while following even off-tab.
- [`MJPEGView.swift`](./MJPEGView.swift) — **laptop-relay** path: `MJPEGStream` reads the
  backend's MJPEG (`multipart/x-mixed-replace`) feed, deriving the HTTP URL from the ws
  server URL (e.g. `/video/tello`). Built and usable; not currently wired into the FEED toggle.
- [`TelloObjectDetector.swift`](./TelloObjectDetector.swift) — **NEW.** On-device object
  detection over the companion Tello feed. Runs a bundled CoreML **`yolov8n`** (COCO classes,
  NMS baked in) via Vision over the decoded frames (tapped via
  `TelloDirectStream.onPixelBufferSecondary`) and publishes `DetectedObject` boxes (label +
  confidence + normalized SwiftUI top-left rect) for the feed overlay. Throttled so it never
  starves the follow loop or the video; Vision runs on a serial background queue, published
  updates hop to main. Fully on-device. COCO-class only — **not** weapon detection (see
  the Detection note in `../../CLAUDE.md`).

### Map
- [`LocalMapView.swift`](./LocalMapView.swift) — the offline GPS-less map (the only map
  view): a top-down, pan/pinch `Canvas` of the local frame — pre-cached building footprints
  as the basemap, range rings + radial bearings (no grid), launch origin, comet-tail trails
  with a drone heading chevron, shape-coded entity markers (● soldier · ▲ drone · ◇ POI ·
  ✕ hazard · • object) with label chips + range/bearing readouts, N arrow + scale bar.
  Pure view — draws whatever it is given.
- [`Buildings.swift`](./Buildings.swift) — `Building` (one OSM footprint in local metres,
  mirroring `/map/buildings`) + `BuildingsStore`, an `@MainActor ObservableObject` that loads
  the laptop's pre-cached building footprints once over the LOCAL AP (no internet, no live
  tiles) as the phone's offline basemap. Idempotent.
- [`MapProjection.swift`](./MapProjection.swift) — pure value type, local-frame metres
  → screen points (origin-centred, +y up); `spanMeters` square-fit. No MapKit/GPS.
  Unit-tested ([`../Tests/MapProjectionTests.swift`](../Tests/MapProjectionTests.swift)).
- [`Localizer.swift`](./Localizer.swift) — `@MainActor ObservableObject` that builds the map
  **with no laptop in the loop**, driven by the follow loop + phone compass — fully OFFLINE
  and GPS-FREE. The operator is the FIXED launch origin (0,0); the drone is placed relative to
  the operator from the lock's distance + bearing rotated by the compass heading
  (magnetometer, not GPS). The drone accumulates a fixed-frame movement trail (≥0.5 m to log a
  point, capped). Publishes launch-frame `entities`/`trails` (merged with `WorldClient`'s in
  `ContentView`) plus `worldEntities` — the same entities re-expressed in the shared world
  frame via `project(through:)` for the laptop report (empty until the aligner has a fix).
- [`LocationProvider.swift`](./LocationProvider.swift) — `ObservableObject` over
  `CLLocationManager`. The operator's device location + true heading. The heading drives the
  `Localizer`/`FrameAligner` drone placement; the location is published for follow-me context.
  Coarse accuracy + distance filter to avoid churn on every fix.
- [`AnchorCamera.swift`](./AnchorCamera.swift) — Phone back-camera capture that
  detects the **launch anchor AprilTag** (the same tag the Mavic anchors on) and publishes
  its latest range + bearing (`AnchorFix`). Frames feed the local `AprilTagDetector`
  (tag36h11) on a dedicated `videoQueue` (the detector is touched exclusively there);
  published updates hop to main. Fully offline / on-device; not `@MainActor`.
- [`FrameAligner.swift`](./FrameAligner.swift) — `@MainActor ObservableObject` that
  co-registers the phone's launch frame (operator at origin, north-up) with the shared
  **WORLD** frame (launch anchor tag = origin, north-up). Both frames are north-up so the
  alignment is a pure translation: observing the anchor tag at (distance, bearing) with the
  compass heading places the operator at the negative tag offset in the tag-origin world
  frame; re-observing the tag refreshes the translation (drift correction). This is what lets
  the phone publish world-frame `EntityReport`s that upsert into the laptop world model and
  render on the **shared** map (no longer just a relative inset).

### UI / theme
- [`ControlBar.swift`](./ControlBar.swift) — a `TRACK ME` / `TRACK TAG` / `RE-LOCK` target
  row (each optional callback; disabled when nil — `RE-LOCK` is wired only while airborne),
  then FOLLOW/HOLD/RECALL, then a dominant, always-visible hard **STOP** (button, not
  voice-only — per spec). Emits `Command`s + target callbacks out; pure view.
- [`StatusBar.swift`](./StatusBar.swift) — link state · mission stage · per-channel
  health (TELLO/MAVIC/PERC) · fault line. Pure view.
- [`Theme.swift`](./Theme.swift) — light tactical palette (field tan paper, olive +
  earth-brown accents, mono numerals). Explicit colours; shape over colour.

### Voice + intent
- [`VoiceController.swift`](./VoiceController.swift) — `@MainActor` push-to-talk that runs
  Apple's **on-device `SFSpeechRecognizer`** (fully offline, refuses cloud STT via
  `requiresOnDeviceRecognition`, with auto-stop on a short silence): `AVAudioEngine` capture
  → on-device transcribe → `DronePilot.resolve` → emits a `DroneAction`. STT can't crash the
  C lib (Gemma's `transcribe` path is not used here); the action resolution prefers the
  Gemma function-call and falls back to `DroneIntent`. Honest about availability (speech
  denied/unavailable ⇒ `.error`, never a fake command); `reloadService()` re-checks auth.
- [`IntentParser.swift`](./IntentParser.swift) — pure, unit-tested mapper of a
  transcript onto the closed `Command` set (priority: stop → recall → hold → follow);
  unknown phrases rejected. A `Command`-only reference used by tests
  ([`../Tests/IntentParserTests.swift`](../Tests/IntentParserTests.swift)); the live voice
  path resolves through `DronePilot`/`DroneIntent` (the richer flight+mission vocabulary).
- [`CactusService.swift`](./CactusService.swift) — `CactusService` protocol
  (`transcribe`/`analyze`/`complete`) + the honest `UnavailableCactusService` fallback
  (throws, never canned data) + `CactusFactory`/`CactusConfig` (real backend only when the
  framework + downloaded model are present). `RealCactusService` is compiled in under
  `canImport(cactus)` and serializes inference on one queue.
- [`Cactus.swift`](./Cactus.swift) — thin Swift bridge over the Cactus C API
  (`init`/`complete` text+PCM/`transcribe`/`destroy`), guarded by `#if canImport(cactus)`.
  Compiles in only when `cactus.xcframework` is added to the target. Fully local — no
  network. See [`../../docs/VOICE.md`](../../docs/VOICE.md).
- [`ModelDownloader.swift`](./ModelDownloader.swift) — `ObservableObject` that fetches
  the int4-apple Gemma weights (`Cactus-Compute/gemma-4-E2B-it`, ~4.7 GB) once on first
  launch, verifies SHA-256 against a pinned immutable commit, runs a disk preflight, and
  unzips into Documents (`ZIPFoundation`). Resumable `URLSessionDownloadTask` (single-flight);
  one-time online setup, inference afterward fully offline. The SETUP overlay in `ContentView`
  blocks the UI until it reports present.

Other target resources live alongside: `Info.plist`, `Assets.xcassets`,
`SkyGuardian-Bridging-Header.h` (exposes the AprilTag C API to Swift — still named for the
prior `SkyGuardian` module; the target/module is now `ReconCompanion`). The bundled CoreML
model (`yolov8n.mlpackage`) lives in `../Resources`.

## Build notes
- Generated/built from [`../project.yml`](../project.yml) via `xcodegen`; tests in
  [`../Tests`](../Tests) (`ContractsTests`, `DroneIntentTests`, `FollowControllerTests`,
  `FollowCoordinatorTests`, `FrameAlignerTests`, `IntentParserTests`, `MapProjectionTests`,
  `ScoutControllerTests`, `VoicePilotTests`, `WorldClientConfigTests`). Swift rules: no
  force-unwraps in app logic, async/await, pure views with logic in `ObservableObject`s,
  `Codable` wire models.
- Voice/vision model-backed paths are gated behind `canImport(cactus)` — the app builds and
  ships without the xcframework (push-to-talk STT still works via `SFSpeechRecognizer`); add
  `cactus.xcframework` to the target to light up Cactus/Gemma. The Gemma model itself is
  fetched at runtime by `ModelDownloader`.

## Planned / not yet here
- ⬜ Sending the standalone `device_location` message (`DeviceLocation` + `LocationProvider`
  exist; the heading drives the map but the raw location isn't pushed as `device_location`).
  The phone already co-registers and publishes world-frame `entity_report`s, which covers
  the operator marker — this would add the spec's explicit "follow me" location channel.
- ⬜ Vision (`analyze`) surfaced in UI — the `CactusService` method exists; no caller.
- ⬜ MJPEG relay path exposed in the FEED toggle alongside the direct stream.
