# On-device Voice + Vision (Gemma 3n via Cactus)

Voice control and multimodal vision that run **on the phone, offline at inference
time** — no cloud round-trip. Voice → transcript → closed command vocabulary →
intent; vision → analyze the live Tello frame. Built on [Cactus](https://cactuscompute.com),
the same on-device stack used in the BroadcastBrain (YC Gemma) project.

## How it fits
```
mic → 16kHz PCM ─┐
                 ├─► CactusService (Gemma 3n, on-device) ─► transcript ─► IntentParser ─► intent
Tello frame ─────┘                                        └─► vision Q&A (analyze)
```

## Pieces (`mobile/Sources/`)
- **`Cactus.swift`** — lean Swift bridge over the Cactus C API (`cactus_init`,
  `cactus_complete` with native PCM audio, `cactus_transcribe`, `cactus_destroy`).
  Wrapped in `#if canImport(cactus)` so the app builds **without** the framework.
- **`CactusService.swift`** — `protocol CactusService`, the real guarded impl, an
  honest `UnavailableCactusService` (throws, never fakes), Gemma 3n config, factory.
- **`VoiceController.swift`** — AVAudioEngine mic capture → 16 kHz mono PCM →
  on-device transcription → intent.
- **`IntentParser.swift`** — transcript → closed `Command` vocab (`follow_me` /
  `hold` / `recall` / `stop`); unknown phrases rejected, never guessed. Unit-tested.

The voice pill in the UI shows the true state: **UNAVAILABLE** without the
framework/model, **GEMMA 3N** when it's live. Never fakes a command.

## Enabling it on-device (the open gaps)
1. **iOS framework** — add `cactus.xcframework` (iOS) to the target. Build it with
   `cactus build --apple`, or use Cactus's prebuilt iOS SDK. The on-disk
   BroadcastBrain framework is **macOS-only**. Once present, `canImport(cactus)`
   pulls in the real path automatically.
2. **Model** — `cactus download <gemma-3n-id>` fetches weights; the app downloads
   the model to its Documents dir on first run (auth via the Cactus key in
   `~/.cactus/config.json`, used only at download time). Inference is fully local.
3. **Vision format** — the voice API (audio-in completion / transcribe) is verified
   against the real `cactus_ffi.h`. Image-in-chat (`analyze`) currently passes the
   frame in the messages JSON; confirm the exact multimodal content shape against
   the Cactus iOS SDK version (the macOS FFI exposes `cactus_image_embed`).

## Offline guarantee
The Cactus key is for the model **hub/telemetry at setup**, not runtime inference.
Models load from a local file (`cactus_init(modelPath)`) and never call out — so
voice + vision satisfy offline-first.
