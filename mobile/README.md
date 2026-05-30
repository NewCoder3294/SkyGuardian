# `mobile/` — SkyGuardian iOS app (Swift / SwiftUI)

The soldier's window into the world model and the way they talk to the system.
Native iOS — **Swift/SwiftUI, project generated with XcodeGen, no Expo/EAS**. (This
overrides the spec's React Native choice; native fits the Cactus on-device stack
and the team's Xcode workflow.)

## What it does
- **Subscribes** to the mission spine (`/ws`) and renders the live entity set on a
  map. Three map modes (`MapMode`, a top-level enum; the MAP/FEED toggle is `CenterView`):
  - **2D / 3D** — flat vs tilted **OpenStreetMap** raster basemap (`OSMMapView`,
    MapKit + an OSM tile overlay, free/no-API-key), entities placed around the
    operator's device location.
  - **TAC** — offline, GPS-less **tactical range/bearing map** (`LocalMapView`):
    range rings, bearings, movement trails, NATO-style markers, drawn relative to
    the launch point. This is the only mode that works with no location fix.
- **MAP / FEED toggle** — FEED (`TelloDirectView`) shows the **live Tello camera
  direct from the drone**: the phone joins the Tello's WiFi AP, sends the SDK
  `command`/`streamon` over UDP, and decodes the raw H.264 stream itself (no laptop
  relay) into an `AVSampleBufferDisplayLayer`.
- **On-phone autonomous follow** — FEED can also host the soldier-follow loop
  (`FollowCoordinator`): decoded frames → AprilTag detection → a station-keeping
  `rc` stick controller → the Tello, entirely on the phone while it's on the Tello
  AP. Explicit arm/takeoff, hover-on-tag-loss, auto-land if the tag stays lost. The
  coordinator runs two modes (`FollowCoordinator.Mode = .tag | .track`):
  - `.tag` — AprilTag worn by the soldier.
  - `.track` — **tag-free visual lock** (`ObjectTracker`, Vision saliency +
    `VNTrackObjectRequest`): "track that boat" centers a salient region and follows
    it frame-to-frame, synthesizing a `TagDetection` so the same station-keeping
    controller drives it. Class-agnostic, fully on-device.
- **On-phone map (no laptop)** — `Localizer` builds the map locally off the follow
  fix: the operator is anchored by GPS, the drone is placed by the tag's
  distance/bearing rotated by compass heading, and both accumulate movement trails
  in a fixed launch frame. The TAC/OSM views render the drone + operator even with
  no laptop in the loop; laptop entities (`WorldClient`) are merged in when present.
- **Voice + flight control** — push-to-talk, fully on-device. Speech-to-text runs on
  Apple's offline `SFSpeechRecognizer` (`VoiceController`), **not** Cactus — Gemma 3n's
  `cactus_transcribe` path has no STT backend and null-derefs, so STT is deliberately
  Apple's recognizer. The transcript maps to a **closed drone-function vocabulary**
  (`DroneFunction`): `VoiceController` resolves it deterministically via
  `DroneIntent.match`, while `DronePilot` is the richer path that asks the Cactus/Gemma
  model to pick exactly one function (JSON function-call) and falls back to the same
  `DroneIntent` keyword matcher. Three routing classes: *flight* functions (takeoff/
  land/up/down/left/right/forward/back/rotate_cw/rotate_ccw/emergency) execute directly
  on the Tello over UDP as SDK command strings; `track` arms (or relocks) the tag-free
  visual follow; *mission* intents (`follow_me`/`hold`/`recall`/`stop`) route to the
  laptop over the WS. An always-visible hard **STOP** (ControlBar) and **LAND** (voice
  bar) are first-class, never voice-only.
- Provides its own **device location** (`LocationProvider`) to anchor the OSM map and
  for follow-me context.

## How it talks to the brain (and to the Tello)
Two distinct paths — the spec's "phone never commands the Tello" holds for the
*mission* path; *direct* flight is the soldier's standalone mobile kit on the Tello AP.

- **Spine (laptop):** `ws://<laptop>:8000/ws` (`WorldClient`). Subscribes to the
  world model; sends `intent` only (the closed `Command` enum). Wire types mirror
  `../shared/contracts.ts` / `../backend/app/contracts.py` via `Contracts.swift`.
  The laptop stays the single source of truth — this client only renders + sends intent.
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
| `ContentView.swift` | UI shell: MAP/FEED toggle, map-mode picker, voice bar, first-launch model setup, voice→drone arbiter |
| `Contracts.swift` | Codable mirror of Contract A (entities) + B (messages/intent) |
| `WorldClient.swift` | WebSocket subscribe loop + intent send + movement trails |
| `OSMMapView.swift` | 2D/3D OpenStreetMap basemap (MapKit + OSM tile overlay), local-frame→coord projection, trace polylines |
| `LocalMapView.swift` | TAC: offline range/bearing tactical map (pure view) |
| `MapProjection.swift` | local-frame metres → screen points for TAC (tested) |
| `LocationProvider.swift` | device location + compass heading (CoreLocation) — OSM anchor, follow-me context, `Localizer` heading |
| `Localizer.swift` | phone-side map: places operator (GPS) + drone (tag distance/bearing × heading) in a launch frame with trails — no laptop needed |
| `ObjectTracker.swift` | tag-free visual lock-and-follow (Vision saliency + `VNTrackObjectRequest`); class-agnostic ("track that boat") |
| `TelloDirectStream.swift` | direct UDP H.264 receiver: NAL reassembly → VideoToolbox decode → `AVSampleBufferDisplayLayer`; optional pixel-buffer tap for follow |
| `TelloVideoView.swift` | `TelloDirectView` — FEED view hosting the display layer + the follow loop (honest status, never fakes a frame) |
| `TelloCommander.swift` | sole Tello control channel (UDP 8889): `command`/`streamon`, flight, `rc`, keepalive |
| `MJPEGView.swift` | legacy laptop MJPEG-relay decoder (not wired into FEED) |
| `AprilTagDetector.swift` | on-device AprilTag (vendored AprilRobotics C lib, tag36h11) → pose/bearing/distance |
| `FollowController.swift` | pure station-keeping: tag → `rc` stick command (tested) |
| `FollowCoordinator.swift` | the on-phone follow loop: detect (`.tag` AprilTag or `.track` `ObjectTracker`) → controller → Tello, with arm/disarm/manual/lost-land safety |
| `VoiceController.swift` | push-to-talk mic capture → Apple `SFSpeechRecognizer` on-device STT → `DroneIntent.match` → action (not Cactus) |
| `DronePilot.swift` | transcript → `DroneAction` (Cactus/Gemma function-call, `DroneIntent` keyword fallback) |
| `DroneFunction.swift` | the closed drone-function vocabulary + `DroneAction` (Tello SDK strings / mission routing) |
| `IntentParser.swift` | transcript → closed mission `Command` vocab (tested) |
| `Cactus.swift` / `CactusService.swift` | on-device model bridge (`canImport(cactus)`-guarded; honest Unavailable fallback) |
| `ModelDownloader.swift` | first-run fetch + SHA-256-verify + unzip of the Gemma 3n weights (online once, then offline) |
| `StatusBar.swift` / `ControlBar.swift` / `Theme.swift` | status strip, intent buttons + hard STOP, design tokens |

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
                      #    SPM dep: ZIPFoundation)
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17'    # 33 XCTest
# open straight to FEED (DEBUG only; also repoints WS to ws://127.0.0.1:8001/ws):
#   xcrun simctl launch booted com.nicolasdossantos.skyguardian -feed
```
Tests cover the pure/offline-safe pieces: `ContractsTests`, `FollowControllerTests`,
`IntentParserTests`, `MapProjectionTests`, `WorldClientConfigTests`. The direct Tello FEED + follow loop need
**real hardware on the Tello WiFi AP** — the simulator can't join it, and Cactus voice
needs a device + the framework/model.

Build config in `project.yml`: deployment target iOS 17, Swift 5.0, team `9KHR566436`,
bundle id `com.nicolasdossantos.skyguardian`, display name `SkyGuardian`; bump
`MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` per ship. Info-plist usage strings:
local network, location (when-in-use), microphone; `NSAllowsLocalNetworking` for plain
`ws://`; `ITSAppUsesNonExemptEncryption=false`.

TestFlight ships via the App Store Connect API (archive + export with
`ExportOptions.plist`, upload through [`../scripts/asc.py`](../scripts/asc.py)).
Full device + Tello-feed walkthrough: [`../docs/MOBILE.md`](../docs/MOBILE.md).
Voice details: [`../docs/VOICE.md`](../docs/VOICE.md).
