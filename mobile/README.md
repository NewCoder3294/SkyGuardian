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
- **MAP / FEED toggle** — FEED shows the **live Tello camera direct from the
  drone**: the phone joins the Tello's WiFi AP, sends the SDK `command`/`streamon`
  over UDP, and decodes the raw H.264 stream (UDP 11111) itself — no laptop relay.
  This is the soldier's mobile kit. (Flight commands still go only through the
  spine; FEED is a passive video receiver, not a controller.)
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
| `TelloDirectStream.swift` | direct UDP H.264 receiver: `command`/`streamon`, NAL reassembly → `AVSampleBufferDisplayLayer` |
| `TelloVideoView.swift` | FEED view hosting the direct-stream display layer (honest status, never fakes a frame) |
| `MJPEGView.swift` | legacy laptop MJPEG-relay feed decoder (not wired into FEED) |
| `MapProjection.swift` | local-frame metres → screen points (tested) |
| `IntentParser.swift` | transcript → closed Command vocab (tested) |
| `VoiceController.swift` | mic capture → on-device transcription → intent |
| `Cactus.swift` / `CactusService.swift` | on-device model bridge (`canImport`-guarded) |
| `ModelDownloader.swift` | first-run fetch + unzip of Gemma 3n weights (online once, then offline) |
| `ReconCompanionApp.swift` / `StatusBar` / `ControlBar` / `ContentView` / `Theme` | `@main` + UI shell |

## Interface
- **Spine:** `ws://<laptop>:<port>/ws` — subscribe to the world model, send
  `intent` / `device_location` only. Wire types mirror `../shared/contracts.ts`.
  Never sends flight commands to the Tello.
- **FEED:** direct to the Tello AP at `192.168.10.1` — UDP `8889` (SDK
  `command`/`streamon` + keepalive), inbound H.264 on UDP `11111`. No backend in
  this path. (Legacy laptop relay was `http://<laptop>:<port>/video/tello`.)

## Build / test / run
```bash
xcodegen generate     # project.yml → ReconCompanion.xcodeproj (embeds cactus.xcframework)
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17'    # 15 XCTest
# demo scene (no backend):  xcrun simctl launch booted com.nicolasdossantos.skyguardian -demo
# open straight to FEED:    xcrun simctl launch booted com.nicolasdossantos.skyguardian -feed
```
The direct Tello FEED needs **real hardware on the Tello WiFi AP** — the simulator
can't join it. Build config in `project.yml`: deployment target iOS 17, team
`9KHR566436`, bundle id `com.nicolasdossantos.skyguardian`, `MARKETING_VERSION`/
`CURRENT_PROJECT_VERSION` bumped per ship.

TestFlight ships via the App Store Connect API (archive + export with
`ExportOptions.plist`, upload through [`../scripts/asc.py`](../scripts/asc.py)).
Full device + Tello-feed walkthrough: [`../docs/MOBILE.md`](../docs/MOBILE.md).
