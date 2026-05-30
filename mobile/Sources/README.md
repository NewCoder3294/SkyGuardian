# `mobile/Sources` — iOS app source (SwiftUI, mobile-client track)

The soldier's phone client. Renders the laptop's live world model + drone feeds and
sends **intent** (never direct Tello commands — the laptop arbitrates). Offline,
GPS-less; the map is a relative range/bearing plot anchored to the launch point.
See [`../README.md`](../README.md) for build/ship and [`../../CLAUDE.md`](../../CLAUDE.md)
for the spec + hard constraints.

**Status:** ✅ built, tested, on TestFlight. Voice path is 🟡 scaffolded (the
[Cactus](#voice--intent) framework + Gemma 3n model are not bundled; voice reports
`UNAVAILABLE` until added).

## Files by concern

### Entry / shell
- [`ReconCompanionApp.swift`](./ReconCompanionApp.swift) — `@main` scene; forces
  light mode (the tactical look is system-independent). ✅
- [`ContentView.swift`](./ContentView.swift) — root layout: `StatusBar` ·
  MAP/FEED toggle · mission-link connect panel · voice bar · `ControlBar`. Owns the
  `WorldClient` + `VoiceController`. `-demo` / `-feed` launch args (DEBUG) seed
  sample data / point at the local backend. ✅

### Contracts + networking
- [`Contracts.swift`](./Contracts.swift) — Swift mirror of **Contract A** (`Entity`,
  `Vec3`, type/status/source enums) and **Contract B** (`ServerMessage` discriminated
  union over `world_snapshot`/`mission_state`/`health`; `IntentMessage` /
  `DeviceLocation` outbound). Closed `Command` vocabulary: `follow_me`/`hold`/
  `recall`/`stop`. All `Codable`. Mirrors [`../../backend/app/contracts.py`](../../backend/app/contracts.py)
  ↔ [`../../shared/contracts.ts`](../../shared/contracts.ts). ✅
- [`WorldClient.swift`](./WorldClient.swift) — `@MainActor ObservableObject`,
  `URLSessionWebSocketTask`. Subscribes to the spine, publishes `entities`, `stage`,
  `lastError`, `health`, `connection`, and per-unit movement `trails` (soldier/drone,
  jitter-filtered, capped at 80 pts). `send(_:)` delivers intent only. Includes
  DEBUG `loadSampleData()`. ✅

### Video
Two independent paths; the FEED tab currently shows the **direct** one.
- [`TelloDirectStream.swift`](./TelloDirectStream.swift) + [`TelloVideoView.swift`](./TelloVideoView.swift)
  — **direct phone↔Tello, no laptop.** Joins the Tello AP, sends SDK
  `command`/`streamon` over UDP :8889 (+ keepalive), receives raw H.264 on UDP
  :11111, reassembles NAL units, decodes via `AVSampleBufferDisplayLayer`. Honest
  status — never fakes a frame. ✅
- [`MJPEGView.swift`](./MJPEGView.swift) — **laptop-relay** path: reads the backend's
  MJPEG (`multipart/x-mixed-replace`) feed, derives the HTTP URL from the ws server
  URL (`/video/tello`, `/video/mavic` per [`../../docs/VIDEO.md`](../../docs/VIDEO.md)).
  Built and usable; not currently wired into the FEED toggle. ✅

### Map
- [`LocalMapView.swift`](./LocalMapView.swift) — top-down `Canvas` tactical map:
  range rings (5 m), radial bearings, launch origin, movement trails, shape-coded
  entity markers (● soldier · ▲ drone · ◇ POI · ✕ hazard · • object) with label
  chips, N arrow + scale bar. Pure view. ✅
- [`MapProjection.swift`](./MapProjection.swift) — pure value type, local-frame
  metres → screen points (origin-centred, +y up); `spanMeters` square-fit. No
  MapKit/GPS. Unit-tested ([`../Tests/MapProjectionTests.swift`](../Tests/MapProjectionTests.swift)). ✅

### UI / theme
- [`ControlBar.swift`](./ControlBar.swift) — FOLLOW/HOLD/RECALL + a dominant,
  always-visible hard **STOP** (button, not voice-only — per spec). Pure view. ✅
- [`StatusBar.swift`](./StatusBar.swift) — link state · mission stage · per-channel
  health (TELLO/MAVIC/PERC) · fault line. Pure view. ✅
- [`Theme.swift`](./Theme.swift) — light tactical palette (field tan paper, olive +
  earth-brown accents, mono numerals). Explicit colours; shape over colour. ✅

### Voice + intent
- [`IntentParser.swift`](./IntentParser.swift) — maps a transcript onto the closed
  `Command` set (priority: stop → recall → hold → follow); unknown phrases rejected,
  never guessed. Pure, unit-tested ([`../Tests/IntentParserTests.swift`](../Tests/IntentParserTests.swift)). ✅
- [`VoiceController.swift`](./VoiceController.swift) — push-to-talk: `AVAudioEngine`
  capture → 16 kHz mono PCM → on-device transcribe → `IntentParser` → emit. Honest
  about availability (no model ⇒ `.error`, never a fake command). ✅
- [`CactusService.swift`](./CactusService.swift) — `CactusService` protocol + the
  honest `UnavailableCactusService` fallback + `CactusFactory` (real backend only
  when framework + Gemma 3n model present). ✅ (fallback) / 🟡 (real path)
- [`Cactus.swift`](./Cactus.swift) — thin Swift bridge over the Cactus C API
  (`init`/`complete`/`transcribe`/`destroy`), guarded by `#if canImport(cactus)`.
  Compiles in only when `cactus.xcframework` is added to the target. 🟡 — see
  [`../../docs/VOICE.md`](../../docs/VOICE.md).
- [`ModelDownloader.swift`](./ModelDownloader.swift) — `@MainActor ObservableObject`
  that fetches the int4-apple Gemma 3n weights from the Cactus HuggingFace hub on
  first run and unzips them into Documents (`ZIPFoundation`). One-time online setup;
  inference afterward is fully offline. `CactusFactory` reports `model not downloaded`
  until present. ✅ (download path) / 🟡 (only useful once the framework is bundled).

Other target resources live alongside: `Info.plist`, `Assets.xcassets`.

## Build notes
- Generated/built from [`../project.yml`](../project.yml) via `xcodegen`; tests in
  [`../Tests`](../Tests). Swift rules: no force-unwraps in app logic, async/await,
  pure views with logic in `ObservableObject`s, `Codable` wire models.
- Voice/vision are gated behind `canImport(cactus)` — the app builds and ships
  without the xcframework; add `cactus.xcframework` + a Gemma 3n model to light them up.

## Planned / not yet here
- ⬜ Wiring `device_location` (`DeviceLocation` exists; not yet sent) for "follow me" context.
- ⬜ Vision (`analyze`) surfaced in UI — the `CactusService` method exists; no caller.
- ⬜ MJPEG relay path exposed in the FEED toggle alongside the direct stream.
