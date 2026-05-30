# On-device Voice → drone commands

Push-to-talk voice control that runs **entirely on the phone, offline** — no cloud
round-trip. Speech → transcript → resolved `DroneAction` → action. Recon/companion
movement only — station-keeping and repositioning, never engagement.

## The live path (what actually runs)
```
mic → AVAudioEngine ─► SFSpeechRecognizer (Apple on-device STT) ─► transcript
        ─► DroneIntent.match (deterministic keyword matcher) ─► DroneAction
```

The shipping voice path does **not** use Cactus/Gemma. `VoiceController` transcribes
with Apple's `SFSpeechRecognizer` (forced on-device via `requiresOnDeviceRecognition`
when supported) and resolves the transcript with the deterministic `DroneIntent.match`
keyword matcher. The reason is in the code comment: Gemma 3n's `cactus_transcribe`
path null-derefs (it has no STT backend), so the audio→text step was moved to Apple's
recognizer, which is offline and can't crash the C library.

The Cactus/Gemma function-calling layer (`DronePilot` + `CactusService.complete`)
still exists and is the richer flight+mission resolver, but **nothing wires it into the
live voice path** today. It is kept for the on-device-LLM route and is exercised by its
own logic, not by `VoiceController`. Vision (`CactusService.analyze`) likewise exists
but has no caller in the UI yet.

## Pieces (`mobile/Sources/`)
- **`VoiceController.swift`** — `@MainActor` push-to-talk. `AVAudioEngine` mic tap →
  `SFSpeechAudioBufferRecognitionRequest` (partial results on) → `SFSpeechRecognizer`.
  Heard speech auto-finishes after a 1.2 s silence timer (no second tap needed), or you
  re-tap to stop. The final transcript goes to `DroneIntent.match`; a hit emits a
  `DroneAction` via the `onAction` callback. State machine:
  `idle → listening → thinking → idle`, or `.error(...)`. Error strings:
  `MIC/STT DENIED`, `STT UNAVAILABLE`, `AUDIO`, `STT FAIL`, `NO SPEECH`, `NO INTENT`.
  `sourceLabel` is `ON-DEVICE STT` when authorized + available, else `VOICE`.
  `reloadService()` just re-checks mic/speech authorization (kept for API parity with
  the old Cactus-backed path). Auth requires BOTH speech and microphone permission.
- **`DroneFunction.swift`** — the CLOSED function vocabulary (`DroneFunction` enum), the
  resolved `DroneAction`, and the deterministic `DroneIntent` keyword matcher used by
  the live voice path. `DroneAction.telloCommand` renders flight strings with magnitudes
  clamped to Tello ranges (moves 20–500 cm, rotations 1–360°); `DroneAction.label` is
  the short UI status text. `DroneAction.fromModelOutput` parses model JSON for the
  (currently unwired) LLM path.
- **`DronePilot.swift`** — the on-device-LLM function-calling resolver. Builds a system
  prompt from `DroneFunction.allCases` asking Gemma to return exactly one function as
  compact JSON (`{"function":"<name>","value":<int-or-null>}`), prefers the model's
  call, and falls back to `DroneIntent.match` when the service is unavailable, unsure,
  or its output doesn't parse. Never invents a command — unmatched speech returns nil.
  Not currently called by `VoiceController`.
- **`IntentParser.swift`** — a narrower, pure mapper from transcript onto just the four
  **mission** `Command`s (`stop` / `recall` / `hold` / `followMe`), priority-ordered so
  `stop` wins inside a longer phrase. Unit-tested (`IntentParserTests`). Unknown phrases
  return nil. (This is the mission-intent mapper; the live voice path uses the broader
  `DroneIntent` matcher, which also covers flight commands and `track`.)
- **`Cactus.swift`** — lean Swift bridge over the Cactus C API: `cactusInit`,
  `cactusComplete` (text + optional native PCM audio-in), `cactusTranscribe`,
  `cactusDestroy`. Wrapped in `#if canImport(cactus)` so the app builds **without** the
  framework. Nothing here touches the network. (Used only by the Cactus-backed
  service; not on the live STT path.)
- **`CactusService.swift`** — `protocol CactusService` (`transcribe` / `analyze` /
  `complete`), the real `RealCactusService` (serialized through one queue — the model
  pointer isn't thread-safe), the honest `UnavailableCactusService` (throws from every
  call, never fakes), `CactusConfig` (model path = `ModelDownloader.modelDir.path`), and
  `CactusFactory.make()` which returns the real service only when the framework **and**
  a downloaded model are both present.
- **`ModelDownloader.swift`** — fetches the Gemma 3n weights once on first launch and
  unzips them into Documents (details below). The UI gates the voice button on
  `ModelDownloader.isPresent`, so the model download still gates voice even though the
  STT step uses Apple's recognizer — the Setup screen blocks until the model is ready.

The voice pill in the UI shows `VOICE · <sourceLabel>` and the live state
(`TAP TO SPEAK`, `→ <action label>`, error text). It never fakes a command.

## Command vocabulary (`DroneFunction` / `DroneIntent`)
Flight (`isFlight == true`; `missionCommand == nil`): `takeoff`, `land`, `up`, `down`,
`left`, `right`, `forward`, `back`, `rotate_cw`, `rotate_ccw`, `emergency`, `track`.
All except `track` render a literal Tello SDK string via `DroneAction.telloCommand`
and are sent directly to the Tello over UDP. Moves and rotations take a magnitude
(defaults: 50 cm moves, 45° rotations, from `DroneFunction.defaultMagnitude`);
`emergency` cuts motors immediately (failsafe). `track` is the one flight-class
function with no `telloCommand` (returns nil) — "track that boat" / "lock on"
engages the on-device visual tracker (`ObjectTracker`/`FollowCoordinator`) rather
than issuing a move; `ContentView` special-cases it before the generic flight path.

Mission (routed to the laptop brain over the WS, which owns the SLAM/AprilTag autonomy):
`follow_me`, `hold`, `recall`, `stop`. These map onto the wire `Command` vocabulary via
`DroneFunction.missionCommand`.

`DroneIntent.match` (the live path) resolves both classes from keywords, priority-ordered
so failsafe/mission phrases win inside longer utterances and compound phrases
("rotate left", "take off") are checked before the bare directional words they contain.
`IntentParser.parse` covers only the four mission intents.

## Model download (`ModelDownloader.swift`)
- Model: `Cactus-Compute/gemma-4-E2B-it`, the int4 Apple build of Gemma 3n (E2B: audio +
  vision + text), pulled from the Cactus hub on HuggingFace. (Used by the Cactus-backed
  LLM/vision path; the live STT path does not load it, but the UI still requires it.)
- One-time, online, on first launch. `URLSessionDownloadTask` streams the zip
  (`expectedBytes` ≈ 4.68 GB) with progress and resume-on-drop (the resume token is
  persisted in Caches across relaunches). Single-flight: a second `ensureModel()` while
  one is in progress is ignored.
- **Supply-chain hardening**: the URL is pinned to an immutable commit
  (`pinnedRevision`, not mutable `main`), and the finished file's SHA-256 must match
  `expectedSHA256` baked into the app before it is unzipped — a mismatch refuses and
  deletes the artifact. A disk preflight (needs room for a second full copy) fails
  clearly instead of crashing mid-unzip.
- Downloads into `Caches/<weightsKey>.zip`, then unzips into
  `Documents/models/gemma-4-e2b-it` (`ModelDownloader.modelDir`, which is exactly what
  `CactusConfig.modelPath` / `cactus_init` are pointed at), flattening a single wrapper
  folder if present. State machine:
  `absent → downloading(progress) → verifying → unzipping → ready` (or `failed`).
  Idempotent — safe to re-run after a failure.

## Enabling the Cactus/Gemma path on-device (open gaps)
The live voice path needs nothing beyond microphone + speech permission. To bring the
on-device-LLM resolver (`DronePilot`) and vision (`analyze`) online:
1. **iOS framework** — add `cactus.xcframework` (iOS) to the target (build with
   `cactus build --apple`, or use Cactus's prebuilt iOS SDK). Once present,
   `canImport(cactus)` pulls in `RealCactusService` automatically.
2. **Model** — `ModelDownloader.ensureModel()` fetches and verifies the weights on first
   run; inference afterward is fully local.
3. **Wire it in** — `VoiceController` would need to route the transcript through
   `DronePilot.resolve` (or call `CactusService.analyze` for vision) before either is
   actually used.
4. **Vision format** — `analyze` currently passes the frame as a base64 `image_url`
   data URL in the messages JSON; confirm the exact multimodal content shape against the
   Cactus iOS SDK version before relying on vision Q&A.

## Offline guarantee
Apple's `SFSpeechRecognizer` runs on-device (forced when supported) and `DroneIntent`
is pure local logic, so the live voice path is fully offline. The Cactus
hub/HuggingFace access is only for the one-time model download — Cactus models load from
a local file (`cactus_init(modelPath)`) and never call out — so the optional Gemma path
also satisfies offline-first.
