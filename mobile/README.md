# `mobile/` — SkyGuardian iOS app (Swift / SwiftUI)

The soldier's window into the world model and the way they talk to the system.
Native iOS — **Swift/SwiftUI, project generated with XcodeGen, no Expo/EAS**. (This
overrides the spec's React Native choice; native fits the Cactus on-device stack
and the team's Xcode workflow.)

## What it does
- **Subscribes** to the mission spine (`/ws`) and renders the live entity set on a
  map. The map is the offline, GPS-less **tactical range/bearing map** (`LocalMapView`):
  range rings, bearings, movement trails, NATO-style markers, plus the laptop's
  pre-cached OSM building footprints as the basemap, all drawn relative to the launch
  point. It works with no location fix. The top-level layout toggle is `CenterView`
  (`map` / `feed`).
- **MAP / FEED toggle** — FEED (`TelloDirectView`) shows the **live Tello camera
  direct from the drone**: the phone joins the Tello's WiFi AP, sends the SDK
  `command`/`streamon` over UDP, and decodes the raw H.264 stream itself (no laptop
  relay) into an `AVSampleBufferDisplayLayer`.
- **On-phone autonomous follow** — FEED can also host the soldier-follow loop
  (`FollowCoordinator`): decoded frames → target detection → a station-keeping
  `rc` stick controller → the Tello, entirely on the phone while it's on the Tello
  AP. Explicit arm/takeoff, hover-on-lock-loss, auto-land if the lock stays lost. After
  takeoff the drone enters an **airborne target-confirmation** hover (`.confirming` phase):
  it shows the lock and sends no follow/track motion until the operator hits **CONFIRM**
  (the FEED `confirmBar`), auto-landing after 30 s if they never do. A never-confirmed
  lock lands on the initial takeoff, but on a mid-flight re-lock it falls back to a manual
  hover instead; resuming from a manual takeover re-acquires the current target through the
  same confirm gate. The coordinator runs two target modes
  (`FollowCoordinator.TargetMode = .visualMe | .tag`, default `.visualMe`):
  - `.visualMe` — **tag-free visual "me" lock** (`ObjectTracker`, Vision saliency +
    `VNTrackObjectRequest`): the default target. Centers a salient region and follows
    it frame-to-frame, synthesizing a `TagDetection` so the same station-keeping
    controller drives it. Class-agnostic, fully on-device.
  - `.tag` — an **AprilTag** used to **designate another target** (a vehicle, a spot,
    another person), not worn by the soldier.

  Every initial lock, mid-flight target switch, and re-lock routes through
  `requestLock(_:)` → the `confirmTarget()` gate before any follow `rc` is sent
  (confirm-always); `pauseToManual` hands control back to the operator at any time.
- **On-phone map (no laptop)** — `Localizer` builds the map locally off the follow
  fix: the operator is the fixed launch origin, the drone is placed by the lock's
  distance/bearing rotated by compass heading, and the drone accumulates a movement
  trail in a fixed launch frame. The TAC map renders the drone + operator even with
  no laptop in the loop; laptop entities (`WorldClient`) are merged in when present.
  `FrameAligner` + `AnchorCamera` additionally co-register the phone's launch frame
  with the shared world frame off the launch anchor tag so the phone can publish
  world-frame entities (`EntityReport`) that render on the laptop's map too.
- **Voice + flight control** — push-to-talk, fully on-device. Speech-to-text runs on
  Apple's offline `SFSpeechRecognizer` (`VoiceController`), **not** Cactus — Gemma 3n's
  `cactus_transcribe` path has no STT backend and null-derefs, so STT is deliberately
  Apple's recognizer. The transcript maps to a **closed drone-function vocabulary**
  (`DroneFunction`) through `DronePilot.resolve`, which asks the Cactus/Gemma model to
  pick exactly one function (JSON function-call) when available and falls back to the
  deterministic `DroneIntent.match` keyword matcher. Routing classes: *flight* functions
  (takeoff/land/up/down/left/right/forward/back/rotate_cw/rotate_ccw/emergency/flip)
  execute directly on the Tello over UDP as SDK command strings; `track`/`follow_me`
  arm or re-lock the visual-me follow, `track_tag` designates an AprilTag target, and
  `confirm` approves the shown lock; *mission* intents (`follow_me`/`hold`/`recall`/
  `stop`/`approach`) route to the laptop over the WS. A hard **LAND** in the voice bar
  (always visible) and a hard **STOP** in the laptop `ControlBar` (shown on the Map tab;
  on Feed the phone flies the Tello directly, so STOP·LAND lives in the FEED follow
  controls) are first-class, never voice-only.
- Provides its own **device location** (`LocationProvider`) to anchor the map and
  the frame aligner, and for follow-me context.

## How it talks to the brain (and to the Tello)
Two distinct paths — the spec's "phone never commands the Tello" holds for the
*mission* path; *direct* flight is the soldier's standalone mobile kit on the Tello AP.

- **Spine (laptop):** `ws://<laptop>:8000/ws` (`WorldClient`). Subscribes to the
  world model; sends `intent` (the closed `Command` enum), `follow_state` — the Tello's
  relative range/bearing/phase plus `target_type`/`target_label` from the soldier
  (`WorldClient.sendFollowState`, fed by `ContentView.publishFollow()`), which the laptop
  rebroadcasts to the dashboard's follow inset (where it surfaces as a ME / TAG badge) —
  `entity_report` (phone-localized operator + drone in the shared world frame), and
  `label_event` (operator confirm/reject decisions for the data flywheel). Wire types
  mirror `../shared/contracts.ts` / `../backend/app/contracts.py` via `Contracts.swift`.
  The laptop stays the single source of truth — this client only renders + sends
  intent/telemetry.
- **Tello (direct):** the Tello AP at `192.168.10.1` — control over UDP `8889`
  (`TelloCommander`: the single owner of the control channel — `command`/`streamon`,
  flight commands, `rc` sticks, 5 s keepalive), inbound H.264 on UDP `11111`
  (`TelloDirectStream`). No backend in this path; one socket, so the Tello is never
  driven by two sources at once.

## Design
Forced light-mode military tactical (`Theme`): olive/brown/black on field-tan paper,
mono type, shape-coded markers (● soldier, ▲ drone, ◇ POI, ✕ hazard).

## Layout (`Sources/`)
| File | Role |
|---|---|
| `ReconCompanionApp.swift` | `@main`, forced light mode |
| `ContentView.swift` | UI shell: MAP/FEED toggle (`CenterView`), voice bar, first-launch model setup, voice→drone arbiter; laptop `ControlBar` on Map only (with `ME`/`TAG`/`RE-LOCK` target buttons); `publishFollow()` pushes follow_state to the laptop; ALIGN + SCOUT controls |
| `Contracts.swift` | Codable mirror of Contract A (entities) + B (messages/intent + `FollowStateMessage` w/ `target_type`/`target_label`, `EntityReportMessage`, `LabelEventMessage`) |
| `WorldClient.swift` | WebSocket subscribe loop + intent send + `sendFollowState`/`sendEntityReport`/`sendLabelEvent` + movement trails |
| `LocalMapView.swift` | the offline range/bearing tactical map (the only map view; pure view) |
| `MapProjection.swift` | local-frame metres → screen points for the map (tested) |
| `Buildings.swift` | `BuildingsStore` — loads the laptop's pre-cached `/map/buildings` footprints once over the local AP as the offline basemap |
| `LocationProvider.swift` | device location + compass heading (CoreLocation) — map anchor, follow-me context, `Localizer`/`FrameAligner` heading |
| `Localizer.swift` | phone-side map: places operator (launch origin) + drone (lock distance/bearing × heading) in a launch frame with trails, and projects them into the shared world frame — no laptop needed |
| `FrameAligner.swift` | co-registers the phone launch frame with the shared world frame off the launch anchor tag (pure translation, north-up) |
| `AnchorCamera.swift` | back-camera capture detecting the launch anchor AprilTag → `AnchorFix` range/bearing for `FrameAligner` |
| `ObjectTracker.swift` | tag-free visual lock-and-follow (Vision saliency + `VNTrackObjectRequest`); the default "me" target, class-agnostic ("track that boat") |
| `TelloDirectStream.swift` | direct UDP H.264 receiver: NAL reassembly → VideoToolbox decode → `AVSampleBufferDisplayLayer`; primary pixel-buffer tap for follow + secondary tap for object detection |
| `TelloVideoView.swift` | `TelloDirectView` — FEED view hosting the display layer + the follow loop + `TelloObjectDetector` boxes + the airborne CONFIRM/ABORT·LAND `confirmBar` (honest status, never fakes a frame) |
| `TelloObjectDetector.swift` | bundled CoreML `yolov8n` (COCO) over the Tello feed → `DetectedObject` boxes for the overlay; throttled, on-device |
| `TelloCommander.swift` | sole Tello control channel (UDP 8889): `command`/`streamon`, flight, `rc`, keepalive, state telemetry (UDP 8890) |
| `MJPEGView.swift` | laptop MJPEG-relay decoder (built; not wired into FEED) |
| `AprilTagDetector.swift` | on-device AprilTag (vendored AprilRobotics C lib, tag36h11) → pose/bearing/distance |
| `FollowController.swift` | pure station-keeping: `TagDetection` → `rc` stick command + `DroneCommandSink`/`RCCommand`/`FollowConfig` (tested) |
| `FollowCoordinator.swift` | the on-phone follow loop: detect (`.visualMe` `ObjectTracker` or `.tag` `AprilTagDetector`) → controller → Tello, with `arm`/`requestLock`/`pauseToManual`/`disarmAndLand`/`emergencyCut`/`beginScript` + airborne target confirmation (`.confirming` phase, `confirmTarget()`, 30 s auto-land) |
| `ScoutController.swift` | bounded, soldier-commanded explore→scan→retrace maneuver; pure deterministic `Scout.plan` step builder (tested) |
| `VoiceController.swift` | push-to-talk mic capture → Apple `SFSpeechRecognizer` on-device STT → `DronePilot.resolve` → action (Cactus/Gemma function-call, `DroneIntent` keyword fallback) |
| `DronePilot.swift` | transcript → `DroneAction` (Cactus/Gemma function-call, `DroneIntent` keyword fallback) |
| `DroneFunction.swift` | the closed drone-function vocabulary + `DroneAction` (Tello SDK strings / mission routing) + `DroneIntent` keyword matcher |
| `IntentParser.swift` | transcript → closed mission `Command` vocab (tested; a `Command`-only reference, not the live voice path) |
| `Cactus.swift` / `CactusService.swift` | on-device model bridge (`canImport(cactus)`-guarded; honest Unavailable fallback) |
| `ModelDownloader.swift` | first-run fetch + SHA-256-verify + unzip of the Gemma weights (online once, then offline) |
| `StatusBar.swift` / `ControlBar.swift` / `Theme.swift` | status strip, intent buttons + ME/TAG/RE-LOCK + hard STOP, design tokens |

## On-device model (Cactus / Gemma 3n)
Command understanding (voice → drone-function mapping in `DronePilot`) and any vision
run on-device through Cactus/Gemma. Speech-to-text itself is Apple's offline
`SFSpeechRecognizer` (`VoiceController`), not Cactus — Gemma 3n has no working STT
backend here. The Swift bridge
(`Cactus.swift`) is guarded by `#if canImport(cactus)`: **the app builds and ships
without the framework**, and `CactusFactory` returns an honest `UnavailableCactusService`
(every call throws — never canned data) so the UI shows the truth. With
`Frameworks/cactus.xcframework` present (embedded by `project.yml`) and the model on
disk, the real service lights up.

The model itself is **not** bundled. On first launch `ModelDownloader` downloads the
Cactus int4-apple build of Gemma 3n (`Cactus-Compute/gemma-4-E2B-it`, ~4.7 GB),
pinned to an immutable HuggingFace revision, verifies its SHA-256, and unzips it into
the app's Documents. This one-time fetch needs WiFi (not the Tello network); inference
afterward is fully offline. A blocking SETUP screen covers the download.

## Build / test / run
Native Xcode only — **no Expo, no EAS**.
```bash
cd mobile
xcodegen generate     # project.yml → ReconCompanion.xcodeproj
                      #   (embeds Frameworks/cactus.xcframework, compiles Vendor/apriltag,
                      #    bundles Resources/yolov8n.mlpackage, SPM dep: ZIPFoundation)
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17'
# open straight to FEED (DEBUG only; also repoints WS to ws://127.0.0.1:8001/ws):
#   xcrun simctl launch booted com.nicolasdossantos.skyguardian -feed
```
Tests (`Tests/`) cover the pure/offline-safe pieces: `ContractsTests`, `DroneIntentTests`,
`FollowControllerTests`, `FollowCoordinatorTests`, `FrameAlignerTests`, `IntentParserTests`,
`MapProjectionTests`, `ScoutControllerTests`, `VoicePilotTests`, `WorldClientConfigTests`.
The direct Tello FEED + follow loop need **real hardware on the Tello WiFi AP** — the
simulator can't join it, and Cactus voice needs a device + the framework/model.

Build config in `project.yml`: deployment target iOS 17, Swift 5.0, team `9KHR566436`,
bundle id `com.nicolasdossantos.skyguardian`, display name `SkyGuardian`; bump
`MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` per ship. Info-plist usage strings:
local network, location (when-in-use), microphone, speech recognition, camera (launch
anchor); `NSAllowsLocalNetworking` for plain `ws://`; `ITSAppUsesNonExemptEncryption=false`.
The Swift↔C bridging header is `Sources/SkyGuardian-Bridging-Header.h` (still named for
the prior `SkyGuardian` module — the target/module is now `ReconCompanion`).

TestFlight ships via the App Store Connect API (archive + export with
`ExportOptions.plist`, upload through [`../scripts/asc.py`](../scripts/asc.py)).
Full device + Tello-feed walkthrough: [`../docs/MOBILE.md`](../docs/MOBILE.md).
Voice details: [`../docs/VOICE.md`](../docs/VOICE.md).
