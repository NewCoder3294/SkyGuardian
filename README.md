# SkyGuardian

Offline-first aerial recon and situational awareness for dismounted soldiers.
A piloted **Mavic** (the dashboard's **Leader**, human-piloted) streams video to
a local brain that runs SLAM, monocular depth estimation, and an open-vocabulary
detector; entities are projected into a metre-scale local frame and pushed to an
operator dashboard and an iOS app over WebSocket. A **Tello** (the **Follower**)
station-keeps on the soldier via a worn AprilTag. On top of perception, the brain
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
                  │   ▲                                    (follows soldier via
   mission intent │   │ map + entities                     AprilTag; on-device
   (hold/recall)  │   │ (subscribe)                         follow loop on phone;
   + device loc   │   │                                     hovers after takeoff
   + follow_state ▼   │                                     until target confirmed)
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
plus the on-phone AprilTag follow loop. After takeoff the Tello **hovers** and the
operator must **confirm the locked target** before any follow/track motion begins
(an unconfirmed lock auto-lands on a timeout). The laptop backend also ships a
`FollowController` as an *alternate* controller; in the dual-live demo it is taken
out of contention entirely with **`TELLO_DISABLE=1`** (the laptop never connects to
or commands the Tello, and `/health` reports `tello: disabled`), so the phone is the
sole Tello controller. There is no code interlock yet, so single-controller arming
is still an operating rule (see [`CLAUDE.md`](./CLAUDE.md) → "One Tello controller
armed at a time") and [`docs/DEMO.md`](./docs/DEMO.md) for the full topology. The
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
    `follow_state`
  - clients → server: `intent`, `device_location`, `follow_state`

`follow_state` carries the companion Tello's **relative** range/bearing + follow
`phase` from the soldier — deliberately **not** map coordinates, because the phone's
follow frame and the Mavic SLAM frame aren't co-registered. The phone publishes it;
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
│   │   ├── reasoning/
│   │   │   └── intel.py           # IntelReasoner + IntelChat over a LOCAL Ollama model
│   │   ├── perception/
│   │   │   ├── pipeline.py        # the live perception loop
│   │   │   ├── yolo.py            # YOLO / YOLO-World detector wrapper (+ optional COCO ensemble)
│   │   │   ├── depth.py           # DepthAnything-V2 monocular depth (optional)
│   │   │   ├── fusion.py          # YOLO box + SLAM pose (+ depth) → Entity
│   │   │   ├── file_processor.py  # batch perception over an uploaded clip → sidecar JSON
│   │   │   └── slam/              # vo, anchor, backend, local_map, types, euroc, orbslam3_runner
│   │   ├── tello/
│   │   │   ├── client.py          # TelloClient — djitellopy supervisor (laptop-side controller)
│   │   │   └── video.py           # TelloVideoSource — Tello video → FrameSource
│   │   └── follow/
│   │       ├── apriltag.py        # soldier tag detection (bearing + distance)
│   │       └── controller.py      # FollowController — PD follow loop, RC, entity emission
│   ├── tests/                     # pytest, deterministic (FakeClock); + slam/
│   ├── run.sh                     # uvicorn app.server:app on :8000
│   └── requirements.txt           # incl. python-multipart for upload
├── frontend/                      # operator dashboard (Next.js 14 + Tailwind, :3000)
│   └── src/
│       ├── app/                   # layout.tsx, globals.css
│       │   ├── page.tsx           # marketing LANDING page (route /), links to /operator
│       │   └── operator/page.tsx  # the OPERATOR DASHBOARD (route /operator)
│       ├── components/
│       │   ├── FollowInset.tsx    # Tello follow radar (relative range/bearing)
│       │   ├── VideoFeed.tsx      # polled JPEG + bounding-box overlay
│       │   ├── VideoPlayer.tsx    # uploaded-clip playback + cached overlay
│       │   ├── SourceSelector.tsx # RTMP / file source switch + upload UI
│       │   ├── LocalMap.tsx       # map shell (2D/3D switch)
│       │   ├── LocalMap2D.tsx     # 2D top-down map
│       │   ├── LocalMap3D.tsx     # Three.js / R3F 3D map
│       │   ├── Buildings.tsx      # pre-cached OSM building footprints overlay
│       │   ├── EntityList.tsx     # live entity table
│       │   ├── IntelPanel.tsx     # threat board
│       │   ├── IntelSummaryCard.tsx # rolling on-device reasoning assessment
│       │   ├── IntelChat.tsx      # operator Q&A chat against the local LLM
│       │   ├── ConsolePanel.tsx   # rolling detection log
│       │   ├── Clock.tsx          # mission clock
│       │   ├── StatusBar.tsx      # link / leader / perception / world / det
│       │   └── ThreatAlert.tsx    # bottom-right warning popup
│       └── lib/                   # contracts, entities, feedUrl, playback, projection,
│                                  # status, threats, useWorldClient, wsConfig
│                                  # (+ vitest: feedUrl.test.ts, wsConfig.test.ts)
├── mobile/                        # SwiftUI iOS app (XcodeGen, pairs with Cactus/Gemma)
├── scripts/                       # asc.py, run_slam_video.py, fetch_buildings.py
├── docs/                          # DEMO runbook + MOBILE, SLAM, VIDEO, VOICE notes
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
| `DEPTH_MODEL` | `depth-anything/Depth-Anything-V2-Small-hf` | HF model id, or `off` for ground-plane fallback |
| `DEPTH_SCALE` | `5.0` | inverse-depth → metres heuristic |
| `ANCHOR_TAG_SIZE_M` | `0.20` | physical side length of the metric-anchor AprilTag |
| `FOLLOW_TAG_SIZE_M` | `0.18` | soldier-worn follow tag size |
| `FOLLOW_TAG_ID` | _(unset = any tag)_ | restrict follow to a specific tag id |
| `PERCEPTION_FPS` | `5` | perception loop rate |
| `BROADCAST_HZ` | `10` | WS broadcast cadence |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval |
| `TELLO_DISABLE` | `0` | `1` skips the laptop's Tello stack entirely (no connect, no commands; `/health` → `tello: disabled`) so the phone is the sole Tello controller in the dual-live demo |
| `INTEL_MODEL` | `gemma3:4b` | local Ollama model for reasoning + chat; `off` disables the intel layer |
| `INTEL_VISION` | `0` | `1` enables image-aware reasoning (~30× slower than text-only) |
| `INTEL_INTERVAL_S` | `5` | reasoning-loop interval |
| `DASHBOARD_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS allowlist for state-mutating POSTs |
| `OPERATOR_KEY` | _(unset = no auth)_ | when set, gates POSTs behind an `X-Operator-Key` header |
| `MAX_UPLOAD_MB` | `500` | per-file upload cap |

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
`GET /map/buildings`, `GET /intel/summary`, `POST /intel/chat`, and `WS /ws`.

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
over the latest detections (and, with `INTEL_VISION=1`, the latest JPEG) to produce
a short tactical assessment + threat level, and `IntelChat` answers operator
questions grounded in that context. Both use the **same local model** — no extra
download, no cloud. If Ollama is down or `INTEL_MODEL=off`, the intel endpoints
report unavailable and the rest of the stack is unaffected.

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
GPS-less range/bearing tactical map, sends `intent` / `device_location` to the
laptop, and — as the **primary Tello controller** — joins the Tello AP to drive
the drone directly (on-device voice → flight functions + AprilTag follow loop)
while decoding the Tello's raw H.264 in the FEED view. Mission intents
(`follow_me`/`hold`/`recall`/`stop`) still route through the laptop.

## Perception stack — what's loaded

| Subsystem | Implementation | Notes |
|---|---|---|
| **Visual odometry** | Pure-Python ORB + OpenCV essential-matrix VO with zero-motion gate | Drop-in `ORBSLAM3Runner` (`slam/orbslam3_runner.py`) available if the C++ binary is built |
| **Metric anchor** | AprilTag (tag36h11), PnP via `pupil-apriltags` | Two observations with parallax fix scale to metres |
| **Object detection** | Ultralytics YOLO / YOLO-World (open-vocabulary) | 21-prompt defense vocab by default with a `-world` checkpoint; optional standard-COCO ensemble for high-precision person/vehicle/backpack |
| **Depth** | DepthAnything-V2 via HuggingFace transformers | Optional; loads `transformers`+`torch` lazily, caches locally, then offline |
| **On-device reasoning** | Ollama-hosted vision/text LLM (default `gemma3:4b`) | Rolling tactical assessment + operator chat; text-only by default, `INTEL_VISION=1` for image-aware. Disabled if Ollama unreachable |
| **Tello follow (laptop alt.)** | djitellopy + PD station-keep on a soldier-worn AprilTag | Alternate controller; in the dual-live demo it is disabled with `TELLO_DISABLE=1` so the phone flies the Tello |

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
cd frontend && npm test                # vitest (feedUrl, wsConfig)
```

iOS unit tests (Contracts, FollowController, IntentParser, MapProjection,
WorldClientConfig) run via `xcodebuild test` — see
[`mobile/README.md`](./mobile/README.md).

## Status notes

- On-device reasoning is text-only by default (YOLO label list → assessment);
  `INTEL_VISION=1` adds the image but is ~30× slower per tick on Apple Silicon.
- Voice intent + flight (Cactus + Gemma 3n, on-device) runs on iOS — mic →
  transcript → closed drone-function / Command vocabulary → direct Tello control or
  mission intent. See [`docs/VOICE.md`](./docs/VOICE.md).
- Monocular depth is heuristic (relative inverse depth → metres); multi-view
  triangulation against SLAM landmarks is the principled successor.
- ORB-SLAM3 C++ backend integration is drop-in via `ORBSLAM3Runner` but not the
  default.
- No code interlock yet prevents the phone and the laptop `FollowController` from
  both commanding the Tello — single-controller arming is an operating rule. The
  dual-live demo enforces it by convention with `TELLO_DISABLE=1` on the laptop
  (see [`docs/DEMO.md`](./docs/DEMO.md)).
- The mobile follow loop hovers after takeoff and waits for the operator to confirm
  the locked target before any follow/track motion; an unconfirmed lock auto-lands.

## Constraints

Offline-first · no GPS · recon and situational awareness only (no engagement)
· single plain Tello (AP mode) · no cloud calls at runtime. See `CLAUDE.md`
for the full list.
</content>
</invoke>
