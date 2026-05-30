# `mobile/` — SkyGuardian iOS app (Swift / SwiftUI)

The soldier's window into the world model and the way they talk to the system.
Native iOS — **Swift/SwiftUI, project generated with XcodeGen, no Expo**. (This
overrides the spec's React Native choice; native fits the Cactus on-device stack
and the team's Xcode workflow.)

## What it does
- **Subscribes** to the spine (`/ws`) and renders the live entity set on a
  top-down **tactical range/bearing map** (no MapKit — offline + GPS-less, drawn
  relative to the launch point: range rings, bearings, north, scale, movement
  trails, NATO-style markers).
- **MAP / FEED toggle** — FEED shows the **live Tello camera** relayed by the
  laptop (MJPEG); the phone never touches the Tello directly.
- Sends **intent** only (`follow_me` / `hold` / `recall` / `stop`) with a dominant
  always-live **hard STOP**; sends `device_location` for follow-me context.
- **Voice** (on-device, Gemma 3n via Cactus): mic → transcript → closed Command
  vocabulary → intent. Scaffolded; see [`../docs/VOICE.md`](../docs/VOICE.md).

## Design
Light-mode military tactical: olive/brown/black on field-tan paper, mono type,
shape-coded markers (● soldier, ▲ drone, ◇ POI, ✕ hazard). Forced light mode.

## Layout (`Sources/`)
| File | Role |
|---|---|
| `Contracts.swift` | Codable mirror of Contract A+B |
| `WorldClient.swift` | WebSocket subscribe loop + intent send + movement trails |
| `LocalMapView.swift` | tactical range/bearing map (pure view) |
| `MJPEGView.swift` | decodes the relayed MJPEG drone feed |
| `MapProjection.swift` | local-frame metres → screen points (tested) |
| `IntentParser.swift` | transcript → closed Command vocab (tested) |
| `VoiceController.swift` | mic capture → on-device transcription → intent |
| `Cactus.swift` / `CactusService.swift` | on-device model bridge (`canImport`-guarded) |
| `StatusBar` / `ControlBar` / `ContentView` / `Theme` | UI shell |

## Interface
- `ws://<laptop>:<port>/ws`; feed at `http://<laptop>:<port>/video/tello`.
- Wire types mirror `../shared/contracts.ts`. Sends only `intent` /
  `device_location` — never commands the Tello.

## Build / test / run
```bash
xcodegen generate
xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 17'
# demo scene (no backend):    xcrun simctl launch booted com.nicolasdossantos.skyguardian -demo
# feed against local backend:  xcrun simctl launch booted com.nicolasdossantos.skyguardian -feed
```
Bundle id `com.nicolasdossantos.skyguardian`, team `9KHR566436`. TestFlight upload
via the App Store Connect lane — see [`../docs/MOBILE.md`](../docs/MOBILE.md).
