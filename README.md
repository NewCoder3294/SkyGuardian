# SkyGuardian

Offline-first aerial recon and situational awareness for dismounted soldiers.
A piloted **Mavic** (the dashboard's **Leader**, human-piloted) streams video to
a local brain that runs SLAM, monocular depth estimation, and an open-vocabulary
detector; entities are projected into a metre-scale local frame and pushed to an
operator dashboard and an iOS app over WebSocket. A **Tello** (the **Follower**)
station-keeps on the soldier via a worn AprilTag, commanded only by the laptop.

**No cloud. No internet. No GPS. Recon and situational awareness only — no
engagement, ever.** See [`CLAUDE.md`](./CLAUDE.md) for the hard constraints.

## Architecture

```
                 ┌── DJI Fly app (RTMP push) ──┐
                 │                               │
[ Mavic camera ──> rtmp://laptop:1935/leader ]   │
                                                 ▼
                  ┌──────── LAPTOP (the brain) ─────────┐
                  │ RTMP receiver (e.g. MediaMTX :1935) │
                  │   │                                  │
                  │   ▼                                  │
                  │ PerceptionPipeline (PERCEPTION_FPS)  │
                  │   ├─ MonocularVO (ORB essential-mat) │
                  │   ├─ AprilTag metric anchor          │
                  │   ├─ YOLO / YOLO-World detector      │
                  │   ├─ DepthAnything-V2 depth (opt)    │
                  │   └─ Fusion → 3D entities            │
                  │   │                                  │
                  │   ▼                                  │
                  │ WorldModel ── WS broadcast (10 Hz) ──┼──> Dashboard (Next.js, :3001)
                  │   ▲                                  │     - Feed (polled JPEG + overlay + console)
                  │ MissionStateMachine                  │     - Map (2D + 3D Three.js)
                  │   ▲                                  │     - Intel (threat board)
                  │ FollowController ─ djitellopy ── Tello (AP)
                  └──────────────────────────────────────┘
                                  ▲
                            intent (WS)
                                  │
                          iOS app (SwiftUI)
```

The laptop owns the Tello link and is the only thing that flies it. The phone
subscribes to the world model and sends intent only — it never commands the
Tello through the brain. (The iOS app's FEED view does join the Tello AP to
receive its raw H.264 video directly, but it is a passive receiver — no flight
commands. See [`mobile/README.md`](./mobile/README.md).)

Two contracts every subsystem meets at:
- **Contract A — Entity:** the shared world-model data shape.
  Python source of truth in `backend/app/contracts.py`; TS mirror in
  `shared/contracts.ts`; Swift mirror in `mobile/Sources/Contracts.swift`.
- **Contract B — WebSocket protocol:**
  - server → clients: `world_snapshot`, `mission_state`, `health`, `detections`
  - clients → server: `intent`, `device_location`

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
│   │   ├── server.py              # WS hub, broadcast loop, MJPEG + JPEG + upload endpoints
│   │   ├── contracts.py           # Pydantic models for Contract A + B
│   │   ├── world_model.py         # entity lifecycle / TTL
│   │   ├── state_machine.py       # mission stages + event log
│   │   ├── ws_hub.py              # WebSocket fan-out
│   │   ├── video.py               # FrameSource, StreamVideoSource, SwitchableSource, NullSource
│   │   ├── clock.py               # injectable clock (deterministic tests)
│   │   ├── perception/
│   │   │   ├── pipeline.py        # the live perception loop
│   │   │   ├── yolo.py            # YOLO / YOLO-World detector wrapper
│   │   │   ├── depth.py           # DepthAnything-V2 monocular depth (optional)
│   │   │   ├── fusion.py          # YOLO box + SLAM pose (+ depth) → Entity
│   │   │   ├── file_processor.py  # batch perception over an uploaded clip → sidecar JSON
│   │   │   └── slam/              # vo, anchor, backend, local_map, types, euroc, orbslam3_runner
│   │   ├── tello/
│   │   │   ├── client.py          # TelloClient — djitellopy supervisor (sole Tello owner)
│   │   │   └── video.py           # TelloVideoSource — Tello video → FrameSource
│   │   └── follow/
│   │       ├── apriltag.py        # soldier tag detection (bearing + distance)
│   │       └── controller.py      # FollowController — PD follow loop, RC, entity emission
│   ├── tests/                     # 33 pytest cases, deterministic (FakeClock)
│   ├── run.sh                     # uvicorn app.server:app on :8000
│   └── requirements.txt
├── frontend/                      # operator dashboard (Next.js 14 + Tailwind, :3001)
│   └── src/
│       ├── app/                   # layout.tsx, page.tsx, globals.css
│       ├── components/
│       │   ├── VideoFeed.tsx      # polled JPEG + bounding-box overlay
│       │   ├── VideoPlayer.tsx    # uploaded-clip playback + cached overlay
│       │   ├── SourceSelector.tsx # RTMP / file source switch + upload UI
│       │   ├── LocalMap.tsx       # 2D top-down map
│       │   ├── LocalMap3D.tsx     # Three.js / R3F 3D map
│       │   ├── EntityList.tsx     # live entity table
│       │   ├── IntelPanel.tsx     # threat board
│       │   ├── ConsolePanel.tsx   # rolling detection log
│       │   ├── Clock.tsx          # mission clock
│       │   ├── StatusBar.tsx      # link / leader / perception / world / det
│       │   └── ThreatAlert.tsx    # bottom-right warning popup
│       └── lib/                   # contracts, entities, feedUrl, playback,
│                                  # projection, status, threats, useWorldClient
├── mobile/                        # SwiftUI iOS app (XcodeGen, pairs with Cactus/Gemma)
├── scripts/                       # asc.py (App Store Connect), run_slam_video.py
├── docs/                          # MOBILE, SLAM, VIDEO, VOICE design notes
├── models/                        # local weights — git-ignored
└── captures/                      # recorded media for replay — git-ignored
```

## Run the stack

Three processes: an RTMP receiver, the backend (brain), the frontend (dashboard).
The backend boots cleanly with **no** drone, no Mavic source, and no weights —
each producer reports a health string instead of crashing.

### 1. RTMP receiver (only if feeding a live Mavic over RTMP)

Any RTMP server works; MediaMTX is convenient:

```bash
brew install mediamtx                  # one time
mediamtx                               # listens on :1935; push to /leader
```

You can skip this entirely and feed perception a file or device camera instead
(see `MAVIC_SOURCE` below), or run with no source at all.

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # one time

./run.sh                               # uvicorn app.server:app on 0.0.0.0:8000 --reload
```

`requirements.txt` covers the live path (FastAPI, YOLO via `ultralytics`, VO via
`opencv-python-headless` + `pupil-apriltags`, `djitellopy`). Monocular depth is
optional and pulls `transformers` + `torch` on demand — install those separately
if you set a `DEPTH_MODEL`; otherwise leave it `off` and fusion uses the
ground-plane fallback.

Configure producers with env vars (or edit `run.sh`):

| Var | Default | Meaning |
|---|---|---|
| `MAVIC_SOURCE` | _(unset = no source, perception idles)_ | `url:rtmp://…`, `file:/path.mp4`, or `device:N` |
| `YOLO_WEIGHTS` | _(unset = SLAM-only)_ | path to a YOLOv8 `.pt`; a `-world` checkpoint enables open-vocab |
| `YOLO_CLASSES` | defense vocab (21 prompts) when a `-world` checkpoint is loaded | comma-separated override for the YOLO-World vocabulary |
| `YOLO_IMGSZ` | `960` | inference resolution; bump for far-distance accuracy |
| `YOLO_CONF` | `0.20` | confidence threshold |
| `YOLO_COCO_WEIGHTS` | _(unset)_ | optional 2nd detector (COCO YOLOv8); its classes are pruned from the open-vocab set |
| `YOLO_COCO_KEEP` | person/car/truck/motorcycle/bicycle/bus/backpack | COCO labels trusted over open-vocab |
| `DEPTH_MODEL` | `depth-anything/Depth-Anything-V2-Small-hf` | HF model id, or `off` for ground-plane fallback |
| `DEPTH_SCALE` | `5.0` | inverse-depth → metres heuristic |
| `ANCHOR_TAG_SIZE_M` | `0.20` | physical side length of the metric-anchor AprilTag |
| `FOLLOW_TAG_SIZE_M` | `0.18` | soldier-worn follow tag size |
| `FOLLOW_TAG_ID` | _(unset = any tag)_ | restrict follow to a specific tag id |
| `PERCEPTION_FPS` | `5` | perception loop rate |
| `BROADCAST_HZ` | `10` | WS broadcast cadence |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval |

The dashboard can also hot-swap the Leader source to an uploaded clip at runtime
(`SourceSelector` → `POST /video/source/upload`); the backend runs perception
over the whole clip once, caches per-timestamp detections to a sidecar JSON, and
the dashboard scrubs the raw file natively. `POST /video/source/rtmp` switches
back to the env-configured live feed.

### 3. Dashboard

```bash
cd frontend
npm install                            # one time
npm run dev                            # http://localhost:3001
```

The dashboard pulls video via polled single-frame JPEG (`/video/leader.jpg`,
`/video/follower.jpg`) and subscribes to the world model over WebSocket. Set
`NEXT_PUBLIC_WS_URL=ws://<laptop-ip>:8000/ws` to reach the brain from another
host on the LAN.

### Mobile (iOS)

Native Swift/SwiftUI, project generated with XcodeGen — **no Expo/EAS**, built
and run through Xcode. Full instructions in [`mobile/README.md`](./mobile/README.md).

```bash
cd mobile
xcodegen generate                      # project.yml → ReconCompanion.xcodeproj
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17'
```

The app subscribes to `ws://<laptop>:8000/ws`, renders a GPS-less range/bearing
tactical map, sends `intent` / `device_location` only, and (FEED mode) decodes
the Tello's raw H.264 directly off the drone AP — never relaying flight commands.

## Perception stack — what's loaded

| Subsystem | Implementation | Notes |
|---|---|---|
| **Visual odometry** | Pure-Python ORB + OpenCV essential-matrix VO with zero-motion gate | Drop-in `ORBSLAM3Runner` (`slam/orbslam3_runner.py`) available if the C++ binary is built |
| **Metric anchor** | AprilTag (tag36h11), PnP via `pupil-apriltags` | Two observations with parallax fix scale to metres |
| **Object detection** | Ultralytics YOLO / YOLO-World (open-vocabulary) | 21-prompt defense vocab by default with a `-world` checkpoint; optional COCO ensemble |
| **Depth** | DepthAnything-V2 via HuggingFace transformers | Optional; loads `transformers`+`torch` lazily, caches locally, then offline |
| **Tello follow** | djitellopy + PD station-keep on a soldier-worn AprilTag | Idle when no Tello on the network |

Model weights are distributed out-of-band (see `models/`). No model downloads at
runtime once the cache is warm.

## Testing

```bash
cd backend && .venv/bin/python -m pytest -q
# 33 tests, deterministic (FakeClock), no hardware required
```

iOS unit tests (Contracts, FollowController, IntentParser, MapProjection) run
via `xcodebuild test` — see [`mobile/README.md`](./mobile/README.md).

## Status notes

- Voice intent (Cactus + Gemma 3n, on-device) is **scaffolded** on iOS — mic →
  transcript → closed Command vocabulary → intent. See
  [`docs/VOICE.md`](./docs/VOICE.md).
- Monocular depth is heuristic (relative inverse depth → metres); multi-view
  triangulation against SLAM landmarks is the principled successor.
- ORB-SLAM3 C++ backend integration is drop-in via `ORBSLAM3Runner` but not the
  default.

## Constraints

Offline-first · no GPS · recon and situational awareness only (no engagement)
· single plain Tello (AP mode) · no cloud calls at runtime. See `CLAUDE.md`
for the full list.
