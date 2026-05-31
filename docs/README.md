# docs — Design & Subsystem Docs

Index of the design and per-subsystem docs for SkyGuardian. The root
[`README.md`](../README.md) (status + repo layout + run) and
[`CLAUDE.md`](../CLAUDE.md) (the mission + hard constraints) are the **source of
truth**; the files here go deep on one subsystem each.

## System at a glance

SkyGuardian is an **offline-first, no-GPS, recon-and-situational-awareness-only**
system for dismounted soldiers. Three machines, one local network, no cloud:

```
            [ Soldier w/ Phone (iOS) ] ----AP (rc/takeoff/land)----> [ Tello ]
                  |   ^                                          (visual-me lock by
   mission intent |   | map + entities                           default; AprilTag
   (hold/recall)  |   | (subscribe)                              designates targets;
   + device loc   v   |                                          on-device follow loop)
[ Manned Mavic ] --video--> [ LAPTOP (the brain) ]   (backend FollowController is an
                                |  YOLO + depth (detect)  alternate Tello controller —
                                |  SLAM (pose / metric local map)  left disarmed while
                                |  On-device reasoning (local LLM)  the phone flies,
                                |  World model                      gated by ArmingLock)
                                |  FastAPI + WebSocket server
                                v
                       [ Web dashboard ]  +  [ iOS app ]
                          (both subscribe to the same local server)
```

- **Mavic** = manned recon drone (human-piloted), shown as **"leader"** in the
  dashboard. Feeds video to the laptop. The laptop never flies it.
- **Tello** = companion drone that follows the soldier, shown as **"follower"**.
  Default target is an on-device visual "me" lock; a worn **AprilTag** is used to
  **designate** other targets (a vehicle, a spot, another person), not to lock the
  soldier. A single plain Tello in AP mode.
- **Laptop ("the brain")** = runs YOLO + depth + SLAM on the Mavic feed, runs
  on-device reasoning (a local LLM), the world model, and the local
  FastAPI/WebSocket server, and serves the dashboard's JPEG/MJPEG video. Ships a
  backend `FollowController` (plus an `ApproachController`) as an **alternate** Tello
  controller, gated behind the `ArmingLock` interlock.
- **Phone** = iOS/SwiftUI client. Reads map + entities, sends mission intent +
  device location, and — in the current architecture — is the **primary Tello
  controller**: on-device voice + follow loop (visual-me by default; AprilTag for
  designated targets), commanding the Tello directly over its AP
  (`192.168.10.1:8889`).

> **One controller at a time.** The phone and the backend `FollowController` /
> `ApproachController` can both drive the Tello; only one is armed at once. Normally
> the phone flies and the laptop controllers stay disarmed. A software `ArmingLock`
> (`backend/app/follow/arming.py`) now enforces a single armed laptop controller and
> arming owner `"phone"` disarms them — but the single-controller rule still stands
> because the phone talks to the Tello over its own AP, outside the laptop's lock.
> See [`../CLAUDE.md`](../CLAUDE.md).

## The spine (backend — `backend/app/`)

The local server is the single source of truth. `server.py` binds `0.0.0.0:8000`
(`backend/run.sh` → `uvicorn app.server:app --host 0.0.0.0 --port 8000`) and
exposes:

- `GET /ws` — one WebSocket. Broadcasts `world_snapshot` + `mission_state` +
  `health` + `detections` (`source="leader"`) at `BROADCAST_HZ` (default 10);
  accepts validated client `intent` and `device_location` messages (Contract B).
- `GET /health` — JSON liveness (clients, mission stage, tello/mavic/perception).
- `GET /video/leader.jpg` / `GET /video/follower.jpg` — single-frame JPEG, polled
  (204 when no frame is ready). The dashboard's default video path.
- `GET /video/leader.mjpg` / `GET /video/follower.mjpg` — legacy MJPEG
  (`multipart/x-mixed-replace`), kept for debugging.
- `GET /video/source`, `POST /video/source/rtmp`, `POST /video/source/upload`,
  `GET /video/upload/status`, `GET /video/file/{name}`, `GET /video/detections/{name}`
  — the leader source selector + pre-recorded clip upload/playback path.
- `GET /map/buildings` — pre-cached OSM buildings (read-only; 404 until the
  operator runs the fetch script). Source file `.context/buildings.json`,
  generated offline by `scripts/fetch_buildings.py`. `POST /map/area` lets the
  operator re-fetch the buildings layer for a new area (online).
- `GET /intel/summary`, `POST /intel/deep-look`, `POST /intel/chat` — on-device
  reasoning (below).

State-mutating endpoints (RTMP swap, upload) are hardened for a closed LAN: CORS
allowlist (`DASHBOARD_ORIGINS`, default `http://localhost:3000,http://127.0.0.1:3000`),
optional shared secret (`OPERATOR_KEY` → `X-Operator-Key` header), upload size
cap (`MAX_UPLOAD_MB`, default 500), and a video-extension allowlist.

Producers, all robust to "no hardware present" (they report a health string
instead of crashing):

- **`perception/pipeline.py`** (`PerceptionPipeline`) — reads Mavic frames
  (`MAVIC_SOURCE` env, wrapped in a `SwitchableSource` so the operator can
  hot-swap to an uploaded clip without a restart), runs SLAM + YOLO (+ optional
  monocular depth), upserts entities. Idle when no source. YOLO supports a
  YOLO-World custom vocabulary (`server.py` `_DEFAULT_VOCAB` is a defense-relevant
  prompt set; override with `YOLO_CLASSES`) and an **optional ensemble** — a
  second standard YOLOv8 (COCO) detector for high-precision person/vehicle/backpack
  (`YOLO_COCO_WEIGHTS` / `YOLO_COCO_KEEP`), with the COCO-handled labels pruned
  from the open-vocab list to avoid double-detection.
- **`follow/controller.py`** (`FollowController`) — reads Tello frames, detects an
  AprilTag, upserts `soldier` + `drone` entities, and sends RC to the Tello while
  `stage == FOLLOWING`. Bounded: hovers on no tag reading (never blind thrust) and
  caps total recall time. Idle when the Tello link is down. This is a laptop-side
  Tello controller — kept disarmed (via `ArmingLock`) while the phone is flying.
  **`follow/approach.py`** (`ApproachController`) is a second laptop controller
  (approach-to-target), sharing the same lock. **`follow/arming.py`** (`ArmingLock`)
  enforces one armed laptop controller at a time.
- **`tello/client.py`** (`TelloClient`, djitellopy-backed) + **`tello/video.py`**
  (`TelloVideoSource`, freshness-windowed — returns `None` on a stale/frozen stream
  so the follow loop treats it as "tag lost → hover") — the only backend code that
  talks to the Tello; a supervisor thread auto-reconnects.
- **`reasoning/intel.py`** — on-device reasoning, the **offline equivalent of
  "Gemini Live"**. `IntelReasoner` periodically runs a vision/text LLM over the
  latest frame + detection labels via a **local Ollama model** (default
  `gemma3:4b`); `IntelChat` answers operator Q&A on the same model grounded in the
  current feed; `IntelSummary` is the result record; `ollama_alive()` gates both.
  Fully local — no cloud. Disabled if Ollama is unreachable. Env: `INTEL_MODEL`
  (default `gemma3:4b`, `off` disables), `INTEL_VISION` (default `1` — image-aware;
  `0` is the ~30× faster text-only path), `INTEL_INTERVAL_S` (default 5).
- `world_model.py`, `state_machine.py`, `ws_hub.py`, `clock.py`, `video.py` round
  out the spine.

Contracts live in **`backend/app/contracts.py`** (Pydantic, server-side source of
truth), mirrored by **`shared/contracts.ts`** and **`mobile/Sources/Contracts.swift`**.
Entity types: `poi`, `hazard`, `object`, `soldier`, `drone` (the laptop `Designator`
emits a synthetic `designated_target` entity the dashboard reticles). Closed intent
vocabulary: `follow_me`, `hold`, `recall`, `stop`, `approach` (`stop`/`recall` are
always-live, honored from any stage). `Detections.source` is `leader`/`follower`.
A `FollowState` message carries the companion Tello's **relative** range/bearing,
follow phase from the soldier (phases: `disarmed`, `searching`, `confirming`,
`following`, `lost`, `manual`, `stale`), and `target_type`/`target_label`
(`visual_me` / `tag`) — never map coordinates, since the phone's follow frame and the
Mavic SLAM frame aren't co-registered. Clients also send `entity_report` (phone-
localized world-frame entities) and `label_event` (operator confirm/reject/correct
for the data flywheel); the server can emit `buildings_updated` when the operator
sets a new operational area.

Follow telemetry + the dual-live demo: the phone runs the follow loop and publishes
`follow_state` to the laptop, which **rebroadcasts** it to the dashboard and
downgrades it to a visible `stale` phase via a fail-stale TTL (`_FOLLOW_STALE_S`,
2 s) when the phone stream ages out. `TELLO_DISABLE=1` makes the backend skip
connecting to / commanding the Tello (so `/health` reports `"tello": "disabled"`)
— the configuration for the dual-live demo where the laptop runs Mavic recon +
dashboard while the phone flies the Tello. See [`DEMO.md`](./DEMO.md).

Perception/follow env knobs (read `server.py` for the full set): `YOLO_WEIGHTS`,
`YOLO_IMGSZ`, `YOLO_CONF`, `YOLO_CLASSES`, `YOLO_COCO_WEIGHTS`, `YOLO_COCO_KEEP`,
`YOLO_SPECIALTY_WEIGHTS` / `YOLO_SPECIALTY_KEEP` / `YOLO_SPECIALTY_CONF`,
`DEPTH_MODEL` / `DEPTH_SCALE`, `ANCHOR_TAG_SIZE_M`, `FOLLOW_TAG_SIZE_M`,
`FOLLOW_TAG_ID`, `APPROACH_STANDOFF_M`, `PERCEPTION_FPS`, `TELLO_RETRY_S`,
`BROADCAST_HZ`, `TELLO_DISABLE` (`1` skips the laptop Tello controller — the
dual-live demo mode), and the `CAPTURE_*` data-flywheel knobs (see
[`DATA_FLYWHEEL.md`](./DATA_FLYWHEEL.md)). The `backend/run-indoor.sh` /
`backend/run-outdoor.sh` presets wire these into ready-made detector stacks.

Tests: `cd backend && .venv/bin/python -m pytest -q` (deterministic, FakeClock;
covers contracts, state machine, video, world model, upload guards, arming,
approach, designation, capture/flywheel, follow state, intel deep-look, Foundry
export/isolation, plus `tests/slam/`).

## Web dashboard (`frontend/`)

Next.js 14 + Tailwind. Runs on its own port (3000) and pulls leader/follower
video as JPEG/MJPEG from the brain; everything else arrives over the `/ws` stream
(`src/lib/useWorldClient.ts`).

- `src/app/`: `page.tsx` is the public-facing **marketing landing page** at `/`;
  the **operator dashboard** (Feed/Map/Intel tabs) lives at `operator/page.tsx`,
  route `/operator`. A back-at-base Foundry **Data** view lives at `data/page.tsx`
  (route `/data`), backed by server-side `api/foundry/` routes (the token never
  reaches the client).
- `src/components/`: `Buildings`, `Clock`, `ConsolePanel`, `EntityList`,
  `FollowInset`, `FoundryDataView`, `IntelChat`, `IntelPanel`, `IntelSummaryCard`,
  `LocalMap`, `LocalMap2D`, `LocalMap3D`, `OperationalArea`, `SourceSelector`,
  `StatusBar`, `ThreatAlert`, `VideoFeed`, `VideoPlayer`. `FollowInset` renders the
  rebroadcast `follow_state` as a small radar (soldier at centre, Tello
  range/bearing + phase) with a ME/TAG follow-target badge — deliberately **not**
  co-registered with the SLAM map.
- `src/lib/`: `contracts`, `entities`, `feedUrl`, `followTarget`, `playback`,
  `projection`, `status`, `threats`, `trails`, `useWorldClient`, `wsConfig`,
  `foundryData`, `foundryServer` (+ vitest tests for `feedUrl`, `wsConfig`,
  `followTarget`, `trails`, `useWorldClient`, `foundryServer`, and component tests
  `IntelPanel`, `OperationalArea`).

## Mobile app (`mobile/`)

iOS / SwiftUI, with Cactus/Gemma on-device. `Sources/` includes
`ReconCompanionApp`, `ContentView`, `WorldClient`, `LocalMapView`, `MapProjection`,
`AprilTagDetector`, `ObjectTracker`, `AnchorCamera`, `FrameAligner`,
`FollowController`, `FollowCoordinator`, `ScoutController`, `Cactus`,
`CactusService`, `VoiceController`, `IntentParser`, `DroneFunction`, `DronePilot`,
`TelloCommander`, `TelloDirectStream`, `TelloVideoView`, `TelloObjectDetector`,
`MJPEGView`, `Buildings`, `ModelDownloader`, `LocationProvider`, `Localizer`,
`StatusBar`, `ControlBar`, `Theme`, `Contracts` (the Xcode bridging header is still
named `SkyGuardian-Bridging-Header.h`, though the module is `ReconCompanion`).
`Tests/`: `ContractsTests`, `FollowControllerTests`, `IntentParserTests`,
`MapProjectionTests`, `WorldClientConfigTests`. See
[`MOBILE.md`](./MOBILE.md) and [`../mobile/README.md`](../mobile/README.md).

## Subsystem docs

| Doc | Covers | State |
|---|---|---|
| [`SLAM.md`](./SLAM.md) | GPS-less monocular mapping — Mavic feed → metric local map via VO + AprilTag scale anchor; swappable `MonocularVO` / `ORBSLAM3Runner` backends; honest limitations | ✅ built, tested |
| [`VIDEO.md`](./VIDEO.md) | Laptop video relay — leader/follower JPEG and MJPEG endpoints; env-selected Mavic sources (`url:` / `file:` / `device:` / unset) plus the clip-upload/playback path | ✅ built, tested |
| [`VOICE.md`](./VOICE.md) | On-device voice — mic → Apple `SFSpeechRecognizer` (live STT) → closed `DroneIntent` keyword vocab. Cactus/Gemma (`DronePilot` + vision) is compiled in but not wired into the live voice loop; `cactus.xcframework` embedded, needs the model download | 🟡 Cactus framework embedded; live STT on Apple recognizer |
| [`MOBILE.md`](./MOBILE.md) | iOS app build / TestFlight / device test — XcodeGen + ASC API ship lane, and the single-network Tello-feed walkthrough | ✅ built, tested |

## Specs

- [`superpowers/specs/2026-05-29-recon-companion-design.md`](./superpowers/specs/2026-05-29-recon-companion-design.md)
  — approved design: the recon + soldier-companion pivot, clean-reimplement reuse
  strategy, six-subsystem decomposition around the spine, contracts, and sequencing.

## See also

- [`../backend/app/README.md`](../backend/app/README.md) — backend internals.
- [`../mobile/README.md`](../mobile/README.md) — iOS app source/layout.
- [`../shared/README.md`](../shared/README.md) — the shared message contract.
- Hard constraints (offline-first · no GPS · recon only, no engagement · single
  plain Tello in AP mode · one Tello controller armed at a time) live in
  [`../CLAUDE.md`](../CLAUDE.md).
