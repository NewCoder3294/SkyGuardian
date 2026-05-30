# `mobile/Sources` — iOS app source (SwiftUI, mobile-client track)

The soldier's phone client. Renders the laptop's live world model + drone feeds,
runs the on-device voice/AprilTag-follow stack, and sends **intent** to the laptop
(it never owns the mission state — the laptop arbitrates). Offline, GPS-less; the
tactical map is a relative range/bearing plot anchored to the launch point, with
optional 2D/3D OpenStreetMap basemaps anchored to the device location.
See [`../README.md`](../README.md) for build/ship and [`../../CLAUDE.md`](../../CLAUDE.md)
for the spec + hard constraints.

Two control surfaces coexist here, by design:
- **Mission intent over the WS** to the laptop (`follow_me`/`hold`/`recall`/`stop`)
  via [`WorldClient`](#contracts--networking) — the laptop owns SLAM + autonomy.
- **Direct phone↔Tello flight** over UDP via [`TelloCommander`](#direct-tello-flight-no-laptop)
  for standalone operation on the Tello AP (manual moves + the on-device follow loop).
  Per the spec the Tello is only ever driven by one controller at a time.

**Status:** voice + the direct-follow loop are wired and gated on the on-device
model. The [Cactus](#voice--intent) framework is gated behind `canImport(cactus)`:
without the xcframework, voice/vision report `UNAVAILABLE` (honest fallback, never a
fake command). The Gemma model is auto-downloaded on first launch by
[`ModelDownloader`](#voice--intent).

## Files by concern

### Entry / shell
- [`ReconCompanionApp.swift`](./ReconCompanionApp.swift) — `@main` scene; forces
  light mode (the tactical look is system-independent).
- [`ContentView.swift`](./ContentView.swift) — root layout: `StatusBar` ·
  MAP/FEED toggle · 2D/3D/TAC map-mode picker · mission-link connect panel · voice
  bar (mic + hard **LAND**) · `ControlBar`. Owns every `ObservableObject` (`WorldClient`,
  `VoiceController`, `ModelDownloader`, `LocationProvider`, `TelloDirectStream`,
  `FollowCoordinator`). Blocks the UI behind a SETUP overlay until the on-device model
  is present, then routes resolved voice actions through the single drone arbiter
  (`handle(_:)`): `follow me` → arm/resume the follow loop, `land`/`stop`/`emergency`
  → land/cut (always win), other flight → manual takeover (pause-and-hold), `hold`/
  `recall` → mission intent to the laptop. DEBUG `-feed` launch arg opens FEED against
  `ws://127.0.0.1:8001/ws`.

### Contracts + networking
- [`Contracts.swift`](./Contracts.swift) — Swift mirror of **Contract A** (`Entity`,
  `Vec3`, type/status/source enums; `ttl_s` ↔ `ttlS`) and **Contract B** (`ServerMessage`
  discriminated union over `world_snapshot`/`mission_state`/`health`; `IntentMessage` /
  `DeviceLocation` outbound). Closed `Command` vocabulary: `follow_me`/`hold`/`recall`/
  `stop`. All `Codable`. Mirrors [`../../backend/app/contracts.py`](../../backend/app/contracts.py)
  ↔ [`../../shared/contracts.ts`](../../shared/contracts.ts).
- [`WorldClient.swift`](./WorldClient.swift) — `@MainActor ObservableObject`,
  `URLSessionWebSocketTask`. Subscribes to the spine, publishes `entities`, `stage`,
  `lastError`, `health`, `connection`, and per-unit movement `trails` (soldier/drone,
  0.2 m jitter-filtered, capped at 80 pts). `send(_:)` delivers `Command` intent only.

### Direct Tello flight (no laptop)
- [`TelloCommander.swift`](./TelloCommander.swift) — singleton; the **single owner of
  the Tello control channel** (UDP → 192.168.10.1:8889). Enters SDK mode, keepalive,
  and funnels every flight command (`send`/`execute`/`rc`/`startVideo`) so the drone is
  never driven by two sockets. Publishes `link`/`lastSent`.
- [`DroneFunction.swift`](./DroneFunction.swift) — the CLOSED function vocabulary the
  on-device model may call: direct-flight cases (`takeoff`/`land`/`up`/`down`/`left`/
  `right`/`forward`/`back`/`rotate_cw`/`rotate_ccw`/`emergency`) vs mission intents
  (`follow_me`/`hold`/`recall`/`stop`, routed to the laptop). `DroneAction` resolves a
  function + optional magnitude into a clamped Tello SDK string (or a `Command`), and
  `fromModelOutput` parses the model's `{"function","value"}` JSON. `DroneIntent` is the
  deterministic keyword fallback — never invents a command.
- [`DronePilot.swift`](./DronePilot.swift) — transcript → `DroneAction`. Prefers the
  on-device model's function call (closed-vocabulary system prompt built from
  `DroneFunction`), falls back to `DroneIntent` keyword matching; unmatched speech → nil.

### Soldier-follow (on-device, direct)
- [`AprilTagDetector.swift`](./AprilTagDetector.swift) — AprilRobotics C-lib detector
  (tag36h11) on the luma plane of a 420 pixel buffer (no colour convert). Returns
  `TagDetection` with center/corners, metric distance (pose tz), bearing, elevation, and
  decision margin. `CameraIntrinsics` are estimated from the Tello FOV unless overridden.
- [`FollowController.swift`](./FollowController.swift) — pure, deterministic
  station-keeping: maps a `TagDetection` to an `RCCommand` (yaw to center, fwd/back to
  hold `targetDistance`, up/down to center vertically), with deadbands, gentle gains, and
  hard caps via `FollowConfig`. No tag / weak tag → hover.
- [`FollowCoordinator.swift`](./FollowCoordinator.swift) — `ObservableObject` that runs
  the autonomous loop: decode tap → `AprilTagDetector` (backpressured, ~12 Hz cap) →
  `FollowController` → `rc` sticks at a fixed ~15 Hz cadence. Explicit `arm`/takeoff with
  a settle delay, `pauseToManual`/`resumeFollow` (voice takeover), `disarmAndLand`,
  `emergencyCut`, and an automatic lost-tag land. Publishes `phase`/`distance`/`bearingDeg`/
  normalized tag corners.

### Video
Two independent paths; the FEED tab shows the **direct** one (which also hosts the
follow loop). The MJPEG relay path is built but not currently in the FEED toggle.
- [`TelloDirectStream.swift`](./TelloDirectStream.swift) — **direct phone↔Tello, no
  laptop.** Asks `TelloCommander` for `command`/`streamon`, receives raw H.264 on UDP
  :11111, reassembles NAL units, renders via `AVSampleBufferDisplayLayer`, and (when
  tapped) tees decoded `CVPixelBuffer`s to the follow loop via VideoToolbox. Honest
  status — never fakes a frame.
- [`TelloVideoView.swift`](./TelloVideoView.swift) — the FEED view: hosts the direct
  stream's display layer (`SampleLayerView`), overlays the live tag-lock box
  (`TagBoxShape`) + follow HUD (phase/dist/bearing) + START FOLLOW / STOP·LAND controls
  with a takeoff confirmation dialog. Keeps streaming while following even off-tab.
- [`MJPEGView.swift`](./MJPEGView.swift) — **laptop-relay** path: reads the backend's
  MJPEG (`multipart/x-mixed-replace`) feed, deriving the HTTP URL from the ws server URL
  (e.g. `/video/tello`). Built and usable; not currently wired into the FEED toggle.

### Map
- [`OSMMapView.swift`](./OSMMapView.swift) — MapKit-backed map on an **OpenStreetMap**
  raster basemap (no Apple Maps, no API key). Plots real world-model entities + comet-tail
  movement trails relative to the operator's location, flips between flat 2D and tilted 3D
  cameras. Includes the `MapDimension`, `OSMTileOverlay`, `TracePolyline`, `EntityAnnotation`
  helpers and the local-metres → geographic-coordinate conversion. Renders only what the
  world model holds.
- [`LocalMapView.swift`](./LocalMapView.swift) — the offline GPS-less **TAC** map: a
  top-down `Canvas` of the SLAM local frame — range rings (5 m) + radial bearings (no
  grid), launch origin, comet-tail trails with a drone heading chevron, shape-coded entity
  markers (● soldier · ▲ drone · ◇ POI · ✕ hazard · • object) with label chips + range/
  bearing readouts, N arrow + scale bar. Pure view.
- [`MapProjection.swift`](./MapProjection.swift) — pure value type, local-frame metres
  → screen points (origin-centred, +y up); `spanMeters` square-fit. No MapKit/GPS.
  Unit-tested ([`../Tests/MapProjectionTests.swift`](../Tests/MapProjectionTests.swift)).
- [`LocationProvider.swift`](./LocationProvider.swift) — `ObservableObject` over
  `CLLocationManager`. The operator's device location (the spec's "device location for
  follow-me context"); here it also anchors the OSM basemap and is the origin for the
  local-frame → coordinate conversion. Coarse accuracy + distance filter to avoid
  re-anchoring on every fix.

### UI / theme
- [`ControlBar.swift`](./ControlBar.swift) — FOLLOW/HOLD/RECALL + a dominant,
  always-visible hard **STOP** (button, not voice-only — per spec). Emits `Command`s
  out; pure view.
- [`StatusBar.swift`](./StatusBar.swift) — link state · mission stage · per-channel
  health (TELLO/MAVIC/PERC) · fault line. Pure view.
- [`Theme.swift`](./Theme.swift) — light tactical palette (field tan paper, olive +
  earth-brown accents, mono numerals). Explicit colours; shape over colour.

### Voice + intent
- [`VoiceController.swift`](./VoiceController.swift) — `@MainActor` push-to-talk:
  `AVAudioEngine` capture → 16 kHz mono PCM → on-device transcribe → `DronePilot.resolve`
  → emits a `DroneAction`. Honest about availability (no model ⇒ `.error`, never a fake
  command); `reloadService()` rebuilds the backend after the model downloads.
- [`IntentParser.swift`](./IntentParser.swift) — pure, unit-tested mapper of a
  transcript onto the closed `Command` set (priority: stop → recall → hold → follow);
  unknown phrases rejected. Mirrors the keyword logic; used by tests / as a `Command`-only
  reference ([`../Tests/IntentParserTests.swift`](../Tests/IntentParserTests.swift)). The
  live voice path resolves through `DronePilot`/`DroneIntent` (the richer flight+mission
  vocabulary).
- [`CactusService.swift`](./CactusService.swift) — `CactusService` protocol
  (`transcribe`/`analyze`/`complete`) + the honest `UnavailableCactusService` fallback
  (throws, never canned data) + `CactusFactory` (real backend only when the framework +
  downloaded model are present). `RealCactusService` is compiled in under
  `canImport(cactus)` and serializes inference on one queue.
- [`Cactus.swift`](./Cactus.swift) — thin Swift bridge over the Cactus C API
  (`init`/`complete` text+PCM/`transcribe`/`destroy`), guarded by `#if canImport(cactus)`.
  Compiles in only when `cactus.xcframework` is added to the target. Fully local — no
  network. See [`../../docs/VOICE.md`](../../docs/VOICE.md).
- [`ModelDownloader.swift`](./ModelDownloader.swift) — `ObservableObject` that fetches
  the int4-apple Gemma weights (`Cactus-Compute/gemma-4-E2B-it`) once on first launch,
  verifies SHA-256 against a pinned immutable commit, and unzips them into Documents
  (`ZIPFoundation`). Resumable `URLSessionDownloadTask`; one-time online setup, inference
  afterward fully offline. The SETUP overlay in `ContentView` blocks the UI until it
  reports present.

Other target resources live alongside: `Info.plist`, `Assets.xcassets`,
`SkyGuardian-Bridging-Header.h` (exposes the AprilTag C API to Swift).

## Build notes
- Generated/built from [`../project.yml`](../project.yml) via `xcodegen`; tests in
  [`../Tests`](../Tests) (`ContractsTests`, `FollowControllerTests`, `IntentParserTests`,
  `MapProjectionTests`). Swift rules: no force-unwraps in app logic, async/await, pure
  views with logic in `ObservableObject`s, `Codable` wire models.
- Voice/vision are gated behind `canImport(cactus)` — the app builds and ships without
  the xcframework; add `cactus.xcframework` to the target to light them up. The Gemma
  model itself is fetched at runtime by `ModelDownloader`.

## Planned / not yet here
- ⬜ Sending `device_location` (`DeviceLocation` + `LocationProvider` exist; the location
  anchors the map but isn't yet pushed to the laptop) for "follow me" context.
- ⬜ Vision (`analyze`) surfaced in UI — the `CactusService` method exists; no caller.
- ⬜ MJPEG relay path exposed in the FEED toggle alongside the direct stream.
