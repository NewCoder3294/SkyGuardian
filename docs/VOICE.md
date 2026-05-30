# On-device Voice + Vision (Gemma 3n via Cactus)

Voice control and multimodal vision that run **on the phone, offline at inference
time** — no cloud round-trip. Voice → transcript → drone function call → action;
vision → analyze the live Tello frame. Built on [Cactus](https://cactuscompute.com),
the same on-device stack used in the BroadcastBrain (YC Gemma) project.

## How it fits
```
                                                         ┌─► DronePilot (function-call) ─┐
mic → 16kHz PCM ─► CactusService.transcribe ─► transcript┤                               ├─► DroneAction
                                                         └─► DroneIntent (keyword fallback)
Tello frame ─────► CactusService.analyze ─────────────────────────────────────────────► vision Q&A
```

A resolved `DroneAction` is one of two routing classes (see `DroneFunction`):
- **flight** — a literal Tello SDK string (e.g. `up 50`, `cw 45`) executed directly on
  the Tello over UDP. Works standalone, no laptop in the loop.
- **mission** — a higher-level intent (`follow_me` / `hold` / `recall` / `stop`) that maps
  onto the wire `Command` vocabulary and is routed to the laptop brain, which owns the
  SLAM/AprilTag autonomy needed to execute it.

Recon/companion movement only — station-keeping and repositioning, never engagement.

## Pieces (`mobile/Sources/`)
- **`Cactus.swift`** — lean Swift bridge over the Cactus C API: `cactusInit`,
  `cactusComplete` (text + optional native PCM audio-in), `cactusTranscribe` (PCM →
  text), `cactusDestroy`. Wrapped in `#if canImport(cactus)` so the app builds
  **without** the framework. Nothing here touches the network.
- **`CactusService.swift`** — `protocol CactusService` (`transcribe` / `analyze` /
  `complete`), the real `RealCactusService` (serialized through one queue — the model
  pointer isn't thread-safe), an honest `UnavailableCactusService` (throws from every
  call, never fakes), `CactusConfig` (model path = `ModelDownloader.modelDir.path`), and
  `CactusFactory.make()` which returns the real service only when the framework **and**
  a downloaded model are both present.
- **`VoiceController.swift`** — push-to-talk. `AVAudioEngine` mic capture →
  `AVAudioConverter` resample to 16 kHz mono Int16 PCM → `service.transcribe` →
  `DronePilot.resolve` → emits a `DroneAction`. State machine: `idle → listening →
  thinking → idle`, or `.error(...)` (`MIC DENIED`, `FORMAT`, `AUDIO`, `NO MODEL`,
  `STT FAIL`, `NO INTENT`). `reloadService()` rebuilds the backend after the model
  finishes downloading.
- **`DronePilot.swift`** — the function-calling layer. Builds a system prompt from
  `DroneFunction.allCases` asking Gemma to return exactly one function as compact JSON
  (`{"function":"<name>","value":<int-or-null>}`). Prefers the model's call; falls back
  to `DroneIntent` keyword matching when the model is unavailable, unsure, or its output
  doesn't parse. Never invents a command — unmatched speech returns nil.
- **`DroneFunction.swift`** — the CLOSED function vocabulary (`DroneFunction` enum),
  the resolved `DroneAction` (renders `telloCommand` strings with magnitudes clamped to
  Tello ranges: moves 20–500 cm, rotations 1–360°; parses model JSON via
  `DroneAction.fromModelOutput`), and `DroneIntent` — the deterministic keyword matcher
  used as the offline fallback.
- **`IntentParser.swift`** — a narrower, pure mapper from transcript onto just the four
  **mission** `Command`s (`stop` / `recall` / `hold` / `follow_me`), priority-ordered so
  `stop` wins inside a longer phrase. Unit-tested (`IntentParserTests`). Unknown phrases
  return nil, never guessed.
- **`ModelDownloader.swift`** — fetches the Gemma 3n weights once on first launch and
  unzips them into Documents for Cactus to load locally (details below).

The voice pill in the UI shows the true state: **UNAVAILABLE** without the framework/
model, **GEMMA 3N** when it's live. Never fakes a command.

## Command vocabulary (`DroneFunction`)
Flight (executed on the Tello): `takeoff`, `land`, `up`, `down`, `left`, `right`,
`forward`, `back`, `rotate_cw`, `rotate_ccw`, `emergency`. Moves/rotations take a
magnitude (defaults: 50 cm, 45°). `emergency` cuts motors immediately (failsafe).

Mission (routed to the laptop): `follow_me`, `hold`, `recall`, `stop`.

`DronePilot` resolves any of these. `IntentParser` covers only the four mission intents
(the wire `Command` set).

## Model download (`ModelDownloader.swift`)
- Model: `Cactus-Compute/gemma-4-E2B-it`, the int4 Apple build of Gemma 3n (E2B: audio +
  vision + text), pulled from the Cactus hub on HuggingFace.
- One-time, online, on first launch. `URLSessionDownloadTask` streams the ~4.7 GB zip
  with progress and resume-on-drop (resume token persisted in Caches across relaunches).
- **Supply-chain hardening**: the URL is pinned to an immutable commit (not mutable
  `main`), and the finished file's SHA-256 must match a constant baked into the app
  before it is unzipped — mismatch means refuse and delete.
- Unzips into `Documents/models/gemma-4-e2b-it`, which is exactly what
  `CactusConfig.modelPath` / `cactus_init` are pointed at. State machine:
  `absent → downloading → verifying → unzipping → ready` (or `failed`). Idempotent —
  safe to re-run after a failure.

## Enabling it on-device (the open gaps)
1. **iOS framework** — add `cactus.xcframework` (iOS) to the target. Build it with
   `cactus build --apple`, or use Cactus's prebuilt iOS SDK. The on-disk
   BroadcastBrain framework is **macOS-only**. Once present, `canImport(cactus)`
   pulls in the real path automatically.
2. **Model** — `ModelDownloader.ensureModel()` fetches and verifies the weights on
   first run; inference afterward is fully local.
3. **Vision format** — the voice path (audio-in completion / transcribe) is verified
   against the real `cactus_ffi.h`. `analyze` currently passes the frame as a base64
   `image_url` data URL in the messages JSON; confirm the exact multimodal content
   shape against the Cactus iOS SDK version before relying on vision Q&A.

## Offline guarantee
The Cactus hub/HuggingFace access is only for the one-time model download (and any
setup telemetry), not runtime inference. Models load from a local file
(`cactus_init(modelPath)`) and never call out — so voice + vision satisfy offline-first.
