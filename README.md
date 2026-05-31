# SkyGuardian

Offline-first aerial recon and situational awareness for dismounted soldiers.
A piloted **Mavic** (the dashboard's **Leader**, human-piloted) streams video to
a local brain that runs SLAM, monocular depth estimation, and a YOLO/open-vocabulary
detector; entities are projected into a metre-scale local frame and pushed to an
operator dashboard and an iOS app over WebSocket. A **Tello** (the **Follower**)
station-keeps on the soldier via an on-device **visual "me" lock** by default; a worn
**AprilTag** is used to **designate** other targets (a vehicle, a spot, another
person), not to lock the soldier. On top of perception, the brain
runs **on-device tactical reasoning** — a local vision/text LLM (the offline
equivalent of "Gemini Live") that produces a rolling threat assessment and answers
operator questions, all without leaving the laptop.

**No cloud. No internet. No GPS. Recon and situational awareness only — no
engagement, ever.** See [`CLAUDE.md`](./CLAUDE.md) for the hard constraints, and
[`docs/DEMO.md`](./docs/DEMO.md) for the live dual-end demo runbook (laptop recon
+ phone-flown follow on one Tello AP).

## Architecture

```
            [ Soldier w/ Phone ] ──AP (rc / takeoff / land)──> [ Tello ]
                  │   ▲                                    (visual-me lock by
   mission intent │   │ map + entities                     default; AprilTag
   (hold/recall)  │   │ (subscribe)                         designates other targets;
   + device loc   │   │                                     on-device follow loop on
   + follow_state ▼   │                                     phone; hovers after takeoff
                  │   │                                     until target confirmed)
[ Manned Mavic ] ──video (RTMP)──> ┌──────── LAPTOP (the brain) ──────────┐
                                   │ RTMP receiver (e.g. MediaMTX :1935)   │
                                   │   │                                   │
                                   │   ▼                                   │
                                   │ PerceptionPipeline (PERCEPTION_FPS)   │
                                   │   ├─ MonocularVO (ORB essential-mat)  │
                                   │   ├─ AprilTag metric anchor           │
                                   │   ├─ YOLO / YOLO-World (+ COCO ens.)  │
                                   │   ├─ DepthAnything-V2 depth (opt)     │
                                   │   └─ Fusion → 3D entities             │
                                   │   │                                   │
                                   │   ▼                                   │
                                   │ WorldModel ─ WS broadcast (BROADCAST_HZ) ──> Dashboard
                                   │   ▲                                   │     (Next.js, :3000, /operator)
                                   │ MissionStateMachine                   │      - Feed (polled JPEG + overlay)
                                   │   ▲                                   │      - Map (2D + 3D Three.js + OSM)
                                   │ IntelReasoner / IntelChat (Ollama)    │      - Intel summary + operator chat
                                   │ follow_state relay (phone → dash)     │      - Threat board
                                   │   (relative range/bearing radar)      │      - Follow inset (Tello radar)
                                   │ FollowController (alternate Tello     │
                                   │   controller — disabled via           │
                                   │   TELLO_DISABLE while the phone flies) │
                                   └───────────────────────────────────────┘
                                                   ▲
                                             intent (WS)
                                                   │
                                           iOS app (SwiftUI)
```

**Tello control — one armed controller at a time.** In the current build the
**phone is the primary Tello controller**: it joins the Tello AP and commands the
drone directly over UDP (`192.168.10.1:8889`) — on-device voice → flight functions
plus the on-phone follow loop (a visual "me" lock by default; an AprilTag designates
other targets). After takeoff the Tello **hovers** and the operator must **confirm
the locked target** before any follow/track motion begins (an unconfirmed lock
auto-lands on the initial takeoff; on a mid-flight re-lock it falls back to a manual
hover instead). The laptop backend also ships a `FollowController` (plus an approach
loop) as an *alternate* controller; in the dual-live demo it is taken out of
contention entirely with **`TELLO_DISABLE=1`** (the laptop never connects to or
commands the Tello, and `/health` reports `tello: disabled`), so the phone is the
sole Tello controller. A software arming interlock now exists
(`backend/app/follow/arming.py` `ArmingLock`): the laptop's follow/approach
controllers must hold the exclusive lock before driving the Tello, and arming owner
`"phone"` disarms them. It backstops, but does not replace, the single-controller
operating rule — the phone talks to the Tello over its own AP, outside the laptop's
lock (see [`CLAUDE.md`](./CLAUDE.md) → "One Tello controller armed at a time") and
[`docs/DEMO.md`](./docs/DEMO.md) for the full topology. The
phone also subscribes to the world model and sends mission `intent` /
`device_location` plus a relative `follow_state` (the Tello's range/bearing from the
soldier) over the WebSocket; the laptop owns the world model, rebroadcasts
`follow_state` to the dashboard, and streams map + state to both clients. See
[`mobile/README.md`](./mobile/README.md) for the phone-side detail.

Two contracts every subsystem meets at:
- **Contract A — Entity:** the shared world-model data shape.
  Python source of truth in `backend/app/contracts.py`; TS mirror in
  `shared/contracts.ts`; Swift mirror in `mobile/Sources/Contracts.swift`.
  `Detections.source` is `"leader"` (recon) / `"follower"` (companion).
- **Contract B — WebSocket protocol:**
  - server → clients: `world_snapshot`, `mission_state`, `health`, `detections`,
    `follow_state`, `buildings_updated`
  - clients → server: `intent`, `device_location`, `follow_state`,
    `entity_report`, `label_event`

`follow_state` carries the companion Tello's **relative** range/bearing + follow
`phase` from the soldier, plus `target_type` (`visual_me` / `tag`) + `target_label`
so the dashboard can show a follow target badge (ME / TAG) — deliberately **not** map
coordinates, because the phone's follow frame and the Mavic SLAM frame aren't
co-registered. The phone publishes it;
the laptop rebroadcasts it (injecting a `stale` phase if the phone goes quiet) so
the dashboard can draw a self-contained radar inset.

`stop` and `recall` are always-live and highest priority; the state machine
honours them from any stage.

## Repo layout

```
.
├── CLAUDE.md                      # spec + hard constraints (source of truth)
├── README.md                      # this file
├── shared/
│   └── contracts.ts               # TS mirror of Contract A + B
├── backend/                       # the local brain (FastAPI + asyncio)
│   ├── app/
│   │   ├── server.py              # WS hub + broadcast loop; JPEG/MJPEG, upload,
│   │   │                          #   buildings, intel summary + chat endpoints;
│   │   │                          #   relays phone follow_state (fail-stale TTL);
│   │   │                          #   TELLO_DISABLE=1 skips the laptop Tello stack
│   │   ├── contracts.py           # Pydantic models for Contract A + B
│   │   ├── world_model.py         # entity lifecycle / TTL
│   │   ├── state_machine.py       # mission stages + event log
│   │   ├── ws_hub.py              # WebSocket fan-out
│   │   ├── video.py               # FrameSource, StreamVideoSource, SwitchableSource, NullSource
│   │   ├── clock.py               # injectable clock (deterministic tests)
│   │   ├── designation.py         # Designator — picks top recon detection → designated_target
│   │   ├── map_area.py            # operator-requested OSM buildings re-fetch (/map/area)
│   │   ├── reasoning/
│   │   │   └── intel.py           # IntelReasoner + IntelChat over a LOCAL Ollama model
│   │   ├── perception/
│   │   │   ├── pipeline.py        # the live perception loop
│   │   │   ├── yolo.py            # YOLO / YOLO-World detector wrapper (+ optional COCO + specialty ensembles)
│   │   │   ├── depth.py           # DepthAnything-V2 monocular depth (optional)
│   │   │   ├── fusion.py          # YOLO box + SLAM pose (+ depth) → Entity
│   │   │   ├── file_processor.py  # batch perception over an uploaded clip → sidecar JSON
│   │   │   └── slam/              # vo, anchor, backend, local_map, types, euroc, orbslam3_runner
│   │   ├── capture/               # data flywheel (opt-in): recorder, cleaning, packaging,
│   │   │                          #   schema, foundry_export (live runtime never imports it)
│   │   ├── tello/
│   │   │   ├── client.py          # TelloClient — djitellopy supervisor (laptop-side controller)
│   │   │   └── video.py           # TelloVideoSource — Tello video → FrameSource (freshness-windowed)
│   │   └── follow/
│   │       ├── apriltag.py        # tag detection (bearing + distance)
│   │       ├── arming.py          # ArmingLock — one laptop controller armed at a time
│   │       ├── controller.py      # FollowController — PD follow loop, RC, entity emission
│   │       ├── approach.py        # ApproachController — backend approach-to-target loop
│   │       └── target.py          # designated-target selection for the approach loop
│   ├── tests/                     # pytest, deterministic (FakeClock); + slam/
│   ├── run.sh                     # uvicorn app.server:app on :8000
│   ├── run-indoor.sh              # indoor preset (COCO + specialty weapon model, depth off)
│   ├── run-outdoor.sh             # outdoor preset (YOLO-World defense vocab + COCO + specialty)
│   └── requirements.txt           # incl. python-multipart for upload
├── frontend/                      # operator dashboard (Next.js 14 + Tailwind, :3000)
│   └── src/
│       ├── app/                   # layout.tsx, globals.css
│       │   ├── page.tsx           # marketing LANDING page (route /), links to /operator
│       │   ├── operator/page.tsx  # the OPERATOR DASHBOARD (route /operator)
│       │   ├── data/page.tsx      # Foundry "Data" view (back-at-base, route /data)
│       │   └── api/foundry/       # server-side Foundry proxy + Ask routes (token never client-side)
│       ├── components/
│       │   ├── FollowInset.tsx    # Tello follow radar (relative range/bearing + ME/TAG badge)
│       │   ├── VideoFeed.tsx      # polled JPEG + bounding-box overlay
│       │   ├── VideoPlayer.tsx    # uploaded-clip playback + cached overlay
│       │   ├── SourceSelector.tsx # RTMP / file source switch + upload UI
│       │   ├── LocalMap.tsx       # map shell (2D/3D switch)
│       │   ├── LocalMap2D.tsx     # 2D top-down map
│       │   ├── LocalMap3D.tsx     # Three.js / R3F 3D map
│       │   ├── Buildings.tsx      # pre-cached OSM building footprints overlay
│       │   ├── OperationalArea.tsx # set/refetch the OSM buildings area
│       │   ├── EntityList.tsx     # live entity table
│       │   ├── IntelPanel.tsx     # threat board
│       │   ├── IntelSummaryCard.tsx # rolling on-device reasoning assessment
│       │   ├── IntelChat.tsx      # operator Q&A chat against the local LLM
│       │   ├── FoundryDataView.tsx # exported ontology browser + Ask box
│       │   ├── ConsolePanel.tsx   # rolling detection log
│       │   ├── Clock.tsx          # mission clock
│       │   ├── StatusBar.tsx      # link / leader / perception / world / det
│       │   └── ThreatAlert.tsx    # bottom-right warning popup
│       └── lib/                   # contracts, entities, feedUrl, followTarget, playback,
│                                  # projection, status, threats, trails, useWorldClient,
│                                  # wsConfig, foundryData, foundryServer (+ vitest tests)
├── mobile/                        # SwiftUI iOS app (XcodeGen, pairs with Cactus/Gemma)
├── scripts/                       # asc.py, run_slam_video.py, fetch_buildings.py,
│                                  #   clean_captures.py, package_dataset.py, export_to_foundry.py
├── docs/                          # DEMO + DEMO_DAY runbooks; MOBILE, SLAM, VIDEO, VOICE,
│                                  #   DATA_FLYWHEEL, FOUNDRY_SETUP notes
├── models/                        # local weights — git-ignored
└── captures/                      # recorded media for replay — git-ignored
```

## Run the stack

Up to four processes: an RTMP receiver, the backend (brain), the frontend
(dashboard), and an optional local Ollama for the reasoning layer. The backend
boots cleanly with **no** drone, no Mavic source, no weights, and no Ollama — each
producer reports a health/availability string instead of crashing.

### 1. RTMP receiver (only if feeding a live Mavic over RTMP)

Any RTMP server works; MediaMTX is convenient:

```bash
brew install mediamtx                  # one time
mediamtx                               # listens on :1935
```

The dashboard's **RTMP** button targets `rtmp://127.0.0.1:1935/live` by default
(`MAVIC_RTMP_DEFAULT`); push the Mavic feed to that path, or override with
`MAVIC_SOURCE`. You can skip RTMP entirely and feed perception a file or device
camera instead (see `MAVIC_SOURCE` below), or run with no source at all.

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # one time

./run.sh                               # uvicorn app.server:app on 0.0.0.0:8000 --reload
```

`requirements.txt` covers the live path (FastAPI, `python-multipart`, YOLO via
`ultralytics`, VO via `opencv-python-headless` + `pupil-apriltags`, `djitellopy`).
Monocular depth is optional and pulls `transformers` + `torch` on demand — install
those separately if you set a `DEPTH_MODEL`; otherwise leave it `off` and fusion
uses the ground-plane fallback.

Configure producers with env vars (or edit `run.sh`):

| Var | Default | Meaning |
|---|---|---|
| `MAVIC_SOURCE` | _(unset = no source, perception idles)_ | `url:rtmp://…`, `file:/path.mp4`, or `device:N` |
| `MAVIC_RTMP_DEFAULT` | `url:rtmp://127.0.0.1:1935/live` | source used by the dashboard **RTMP** button when `MAVIC_SOURCE` is unset |
| `YOLO_WEIGHTS` | _(unset = SLAM-only)_ | path to a YOLOv8 `.pt`; a `-world` checkpoint enables open-vocab |
| `YOLO_CLASSES` | defense vocab (21 prompts) when a `-world` checkpoint is loaded | comma-separated override for the YOLO-World vocabulary |
| `YOLO_IMGSZ` | `960` | inference resolution; bump for far-distance accuracy |
| `YOLO_CONF` | `0.20` | confidence threshold |
| `YOLO_COCO_WEIGHTS` | _(unset)_ | optional 2nd detector (standard COCO YOLOv8); its kept classes are pruned from the open-vocab set |
| `YOLO_COCO_KEEP` | person/car/truck/motorcycle/bicycle/bus/backpack | COCO labels trusted over open-vocab |
| `YOLO_SPECIALTY_WEIGHTS` | _(unset)_ | optional 3rd detector (e.g. a weapons-finetuned YOLOv8) run alongside world + COCO |
| `YOLO_SPECIALTY_KEEP` | _(unset = none)_ | which specialty labels reach the dashboard (lowercased) |
| `YOLO_SPECIALTY_CONF` | _(unset = use `YOLO_CONF`)_ | per-detector confidence floor for the specialty model (noisy threat models want ≥0.40) |
| `DEPTH_MODEL` | `depth-anything/Depth-Anything-V2-Small-hf` | HF model id, or `off` for ground-plane fallback |
| `DEPTH_SCALE` | `5.0` | inverse-depth → metres heuristic |
| `ANCHOR_TAG_SIZE_M` | `0.20` | physical side length of the metric-anchor AprilTag |
| `FOLLOW_TAG_SIZE_M` | `0.18` | follow/designation tag size (laptop `FollowController`) |
| `FOLLOW_TAG_ID` | _(unset = any tag)_ | restrict the laptop follow to a specific tag id |
| `APPROACH_STANDOFF_M` | `1.5` | standoff the laptop `ApproachController` holds from its target |
| `PERCEPTION_FPS` | `5` | perception loop rate |
| `BROADCAST_HZ` | `10` | WS broadcast cadence |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval |
| `TELLO_DISABLE` | `0` | `1` skips the laptop's Tello stack entirely (no connect, no commands; `/health` → `tello: disabled`) so the phone is the sole Tello controller in the dual-live demo |
| `INTEL_MODEL` | `gemma3:4b` | local Ollama model for reasoning + chat; `off` disables the intel layer |
| `INTEL_VISION` | `1` | image-aware reasoning by default; `0` falls back to the text-only path (~30× faster) |
| `INTEL_INTERVAL_S` | `5` | reasoning-loop interval |
| `DASHBOARD_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS allowlist for state-mutating POSTs |
| `OPERATOR_KEY` | _(unset = no auth)_ | when set, gates POSTs behind an `X-Operator-Key` header |
| `MAX_UPLOAD_MB` | `500` | per-file upload cap |
| `CAPTURE_ENABLED` | `0` | `1` records the data-flywheel capture (Mavic frames + detections + label events) |
| `CAPTURE_MISSION_ID` | `mission` | per-mission capture id (use a unique id per run) |
| `CAPTURE_CADENCE_S` / `CAPTURE_LOW_CONF` / `CAPTURE_MAX_MB` | `2.0` / `0.4` / `2000` | capture sampling cadence, low-confidence keep threshold, byte budget (MB) |

The dashboard can hot-swap the Leader source to an uploaded clip at runtime
(`SourceSelector` → `POST /video/source/upload`); the backend runs perception over
the whole clip once, caches per-timestamp detections to a sidecar JSON, and the
dashboard scrubs the raw file natively. `POST /video/source/rtmp` switches back to
the env-configured (or default) live feed. Uploads are hardened: a CORS allowlist,
an optional `OPERATOR_KEY` shared secret, a size cap, a video-extension allowlist,
and single-in-flight gating.

HTTP surface (read `server.py` for exact behaviour): `GET /health`,
`GET /video/leader.jpg` · `/video/follower.jpg` (polled single frames),
`GET /video/leader.mjpg` · `/video/follower.mjpg` (legacy multipart),
`GET /video/source` · `/video/upload/status`, `POST /video/source/rtmp` ·
`/video/source/upload`, `GET /video/file/{name}` · `/video/detections/{name}`,
`GET /map/buildings`, `POST /map/area`, `GET /intel/summary`, `POST /intel/deep-look`,
`POST /intel/chat`, and `WS /ws`.

### 3. Dashboard

```bash
cd frontend
npm install                            # one time
npm run dev                            # http://localhost:3000
```

`http://localhost:3000/` is a marketing **landing** page; the **operator dashboard**
lives at **`http://localhost:3000/operator`** (the landing page's "Operator" links
point there). The dashboard pulls video via polled single-frame JPEG
(`/video/leader.jpg`, `/video/follower.jpg`) and subscribes to the world model over
WebSocket. Set `NEXT_PUBLIC_WS_URL=ws://<laptop-ip>:8000/ws` to reach the brain from
another host on the LAN. Beyond the live map and feed it surfaces: the **Intel
summary card** (latest on-device assessment + threat level), the **operator chat**
(Q&A grounded in the current feed via `/intel/chat`), a **buildings overlay** drawn
from the pre-cached OSM footprints served at `/map/buildings`, and a **follow inset**
— a radar of the companion Tello's relative range/bearing from the soldier, fed by
the phone's `follow_state` over the WS.

### 4. On-device reasoning (optional — local Ollama)

```bash
brew install ollama && ollama serve    # local server on 127.0.0.1:11434
ollama pull gemma3:4b                  # default INTEL_MODEL
```

When Ollama is reachable, the backend runs `IntelReasoner` every `INTEL_INTERVAL_S`
over the latest detections (and, with `INTEL_VISION=1` — the default, the latest
JPEG) to produce a short tactical assessment + threat level, and `IntelChat` answers
operator questions grounded in that context. The periodic loop, the on-demand
`POST /intel/deep-look`, and `POST /intel/chat` all share **one** local model
serialized behind a single `asyncio.Lock` — no extra download, no cloud. If Ollama
is down or `INTEL_MODEL=off`, the intel endpoints report unavailable and the rest of
the stack is unaffected.

### Mobile (iOS)

Native Swift/SwiftUI, project generated with XcodeGen — **no Expo/EAS**, built and
run through Xcode. Full instructions in [`mobile/README.md`](./mobile/README.md).

```bash
cd mobile
xcodegen generate                      # project.yml → ReconCompanion.xcodeproj
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17'
```

The app subscribes to `ws://<laptop>:8000/ws`, renders an OSM basemap plus a
GPS-less range/bearing tactical map, sends `intent` / `device_location` (and
`follow_state` / `entity_report`) to the laptop, and — as the **primary Tello
controller** — joins the Tello AP to drive the drone directly (on-device voice →
flight functions + the follow loop: a visual "me" lock by default, with an AprilTag
to designate other targets) while decoding the Tello's raw H.264 in the FEED view.
Mission intents (`hold`/`recall`/`stop`) still route through the laptop.

## Perception stack — what's loaded

| Subsystem | Implementation | Notes |
|---|---|---|
| **Visual odometry** | Pure-Python ORB + OpenCV essential-matrix VO with zero-motion gate | Drop-in `ORBSLAM3Runner` (`slam/orbslam3_runner.py`) available if the C++ binary is built |
| **Metric anchor** | AprilTag (tag36h11), PnP via `pupil-apriltags` | Two observations with parallax fix scale to metres |
| **Object detection** | Ultralytics YOLO / YOLO-World (open-vocabulary) | defaults to the best bundled COCO model present (prefers `yolov8s` over `yolov8n`); a `-world` checkpoint loads the 21-prompt defense vocab; optional standard-COCO ensemble for high-precision person/vehicle/backpack, plus an optional specialty (e.g. weapons) detector |
| **Depth** | DepthAnything-V2 via HuggingFace transformers | Optional; loads `transformers`+`torch` lazily, caches locally, then offline |
| **On-device reasoning** | Ollama-hosted vision/text LLM (default `gemma3:4b`) | Rolling tactical assessment + operator chat; image-aware by default (`INTEL_VISION=1`), `INTEL_VISION=0` for the ~30× faster text-only path. Disabled if Ollama unreachable |
| **Tello follow (laptop alt.)** | djitellopy + PD station-keep on an AprilTag | Alternate controller, gated behind `ArmingLock`; in the dual-live demo it is disabled with `TELLO_DISABLE=1` so the phone flies the Tello (default visual-me lock; AprilTag designates other targets) |

Model weights are distributed out-of-band (see `models/`); Ollama weights live in
`~/.ollama/models`. No model downloads at runtime once the caches are warm.

Buildings: `scripts/fetch_buildings.py` fetches OSM building footprints for the
operational area **once, with internet**, and writes `.context/buildings.json`,
which the backend then serves read-only at `/map/buildings`. Generate it before
going offline.

## Testing

```bash
cd backend && .venv/bin/python -m pytest -q
# deterministic (FakeClock), no hardware required; includes backend + slam suites
```

```bash
cd frontend && npm test                # vitest run
```

iOS unit tests (Contracts, FollowController, IntentParser, MapProjection,
WorldClientConfig) run via `xcodebuild test` — see
[`mobile/README.md`](./mobile/README.md).

## Status notes

- On-device reasoning is image-aware by default (`INTEL_VISION=1`); `INTEL_VISION=0`
  is the text-only path (YOLO label list → assessment), ~30× faster per tick on
  Apple Silicon.
- Live voice STT is Apple's on-device `SFSpeechRecognizer` → deterministic
  `DroneIntent.match` keyword matcher → direct Tello control or mission intent. The
  Cactus/Gemma function-calling resolver (`DronePilot`) is compiled in but not wired
  into the live voice loop. See [`docs/VOICE.md`](./docs/VOICE.md).
- Monocular depth is heuristic (relative inverse depth → metres); multi-view
  triangulation against SLAM landmarks is the principled successor.
- ORB-SLAM3 C++ backend integration is drop-in via `ORBSLAM3Runner` but not the
  default.
- A software `ArmingLock` (`backend/app/follow/arming.py`) now gates the laptop's
  follow/approach controllers, and `TELLO_DISABLE=1` keeps the laptop off the Tello
  in the dual-live demo. The single-controller operating rule still stands because
  the phone commands the Tello over its own AP, outside the laptop's lock (see
  [`docs/DEMO.md`](./docs/DEMO.md)).
- The mobile follow loop hovers after takeoff and waits for the operator to confirm
  the locked target before any follow/track motion; an unconfirmed lock auto-lands
  on the initial takeoff but falls back to a manual hover on a mid-flight re-lock.

## Constraints

Offline-first · no GPS · recon and situational awareness only (no engagement)
· single plain Tello (AP mode) · no cloud calls at runtime. See `CLAUDE.md`
for the full list.
</content>
</invoke>
