# SkyGuardian

Offline-first aerial recon and situational awareness for dismounted soldiers.
A piloted **Leader** drone (DJI Mavic) streams video to a local brain that runs
SLAM, monocular depth estimation, and an open-vocabulary detector; entities are
projected into a metre-scale local frame and pushed to an operator dashboard
and a tactical mobile app over WebSocket. A **Follower** drone (Tello) is
paired with the mobile app for soldier station-keeping via AprilTag.

**No cloud. No internet. No GPS. Recon and situational awareness only — no
engagement, ever.** See [`CLAUDE.md`](./CLAUDE.md) for the hard constraints.

## Architecture

```
                 ┌── DJI Fly app (RTMP push) ──┐
                 │                               │
[ Mavic camera ──> rtmp://laptop:1935/leader ]   │
                                                 ▼
                  ┌──────── LAPTOP (the brain) ─────────┐
                  │ MediaMTX (:1935 RTMP receiver)      │
                  │   │                                  │
                  │   ▼                                  │
                  │ PerceptionPipeline (~3-5 Hz)         │
                  │   ├─ MonocularVO (ORB SLAM core)     │
                  │   ├─ AprilTag metric anchor          │
                  │   ├─ YOLO-World v2 detector          │
                  │   ├─ DepthAnything-V2 depth          │
                  │   └─ Fusion → 3D entities            │
                  │   │                                  │
                  │   ▼                                  │
                  │ WorldModel ── WS broadcast (10 Hz) ──┼──> Dashboard (Next.js)
                  │   ▲                                  │     - Feed (+ overlay + console)
                  │ MissionStateMachine                  │     - Map (3D Three.js)
                  │   ▲                                  │     - Intel (threat board)
                  │ FollowController ─ djitellopy ── Tello (AP)
                  └──────────────────────────────────────┘
                                  ▲
                            intent (WS)
                                  │
                          Mobile app (SwiftUI)
```

Two contracts every subsystem meets at:
- **Contract A — Entity:** the shared world-model data shape.
  Python source of truth in `backend/app/contracts.py`; TS mirror in
  `shared/contracts.ts`.
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
│   │   ├── server.py              # WS hub, broadcast loop, MJPEG + single-JPEG endpoints
│   │   ├── contracts.py           # Pydantic models for Contract A + B
│   │   ├── world_model.py         # entity lifecycle / TTL
│   │   ├── state_machine.py       # mission stages + event log
│   │   ├── ws_hub.py              # WebSocket fan-out
│   │   ├── video.py               # FrameSource + StreamVideoSource (cv2)
│   │   ├── clock.py               # injectable clock (deterministic tests)
│   │   ├── perception/
│   │   │   ├── pipeline.py        # the live loop
│   │   │   ├── yolo.py            # YOLO / YOLO-World detector wrapper
│   │   │   ├── depth.py           # DepthAnything-V2 monocular depth
│   │   │   ├── fusion.py          # YOLO box + SLAM pose (+ depth) → Entity
│   │   │   └── slam/              # MonocularVO + AprilTag anchor + LocalMap
│   │   ├── tello/
│   │   │   ├── client.py          # djitellopy supervisor (single Tello owner)
│   │   │   └── video.py           # Tello video → FrameSource
│   │   └── follow/
│   │       ├── apriltag.py        # soldier tag detection (bearing + distance)
│   │       └── controller.py      # PD follow loop, RC commands, entity emission
│   ├── tests/                     # 29 pytest cases, deterministic
│   └── requirements.txt
├── frontend/                      # operator dashboard (Next.js 14 + Tailwind)
│   └── src/
│       ├── app/                   # page + globals + favicon
│       ├── components/
│       │   ├── VideoFeed.tsx      # polled JPEG + bounding-box overlay
│       │   ├── LocalMap3D.tsx     # Three.js / R3F 3D map
│       │   ├── IntelPanel.tsx     # threat board
│       │   ├── ConsolePanel.tsx   # rolling detection log
│       │   ├── StatusBar.tsx      # link / leader / perception / world / det
│       │   └── ThreatAlert.tsx    # bottom-right warning popup
│       └── lib/                   # WS client, status tiers, threat list
├── mobile/                        # SwiftUI tactical companion (iOS)
├── models/                        # local weights — git-ignored
├── captures/                      # recorded media for replay — git-ignored
├── scripts/                       # bring-up + dev helpers
└── docs/                          # design specs (SLAM, hardware notes)
```

## Run the stack

Three processes: MediaMTX (RTMP receiver), backend (brain), frontend (dashboard).

### 1. RTMP receiver
```bash
brew install mediamtx                                # one time
mediamtx .context/mediamtx.yml                       # listens on :1935 path 'leader'
```

### 2. Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                      # one time

MAVIC_SOURCE=url:rtmp://localhost:1935/leader \
YOLO_WEIGHTS=$PWD/../models/yolo/yolov8l-worldv2.pt \
DEPTH_MODEL=depth-anything/Depth-Anything-V2-Small-hf \
ANCHOR_TAG_SIZE_M=0.20 \
PERCEPTION_FPS=3 \
uvicorn app.server:app --host 0.0.0.0 --port 8001
```

Environment knobs:

| Var | Default | Meaning |
|---|---|---|
| `MAVIC_SOURCE` | _(unset = no source)_ | `url:rtmp://…`, `file:/path.mp4`, or `device:0` |
| `YOLO_WEIGHTS` | _(unset = SLAM-only)_ | path to a YOLOv8 `.pt`. `-world` weights enable open-vocab |
| `YOLO_CLASSES` | defense vocab (21 classes) | comma-separated override for YOLO-World vocabulary |
| `YOLO_IMGSZ` | `960` | inference resolution; bump for far-distance accuracy |
| `YOLO_CONF` | `0.20` | confidence threshold |
| `DEPTH_MODEL` | DepthAnything-V2-Small | HF model id, or `off` to use ground-plane fallback |
| `DEPTH_SCALE` | `5.0` | inverse-depth → metres heuristic |
| `ANCHOR_TAG_SIZE_M` | `0.20` | physical side length of the AprilTag |
| `PERCEPTION_FPS` | `5` | perception loop rate |
| `BROADCAST_HZ` | `10` | WS broadcast cadence |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval |

### 3. Dashboard
```bash
cd frontend
npm install                                          # one time
npm run dev                                          # http://localhost:3001
```

Set `NEXT_PUBLIC_WS_URL=ws://<laptop-ip>:8001/ws` if hitting the dashboard from
a phone on the LAN.

## Perception stack — what's loaded

| Subsystem | Implementation | Notes |
|---|---|---|
| **Visual odometry** | Pure-Python ORB + OpenCV essential-matrix VO with zero-motion gate | Drop-in `ORBSLAM3Runner` available if the C++ binary is built |
| **Metric anchor** | AprilTag (tag36h11), PnP via `pupil-apriltags` | Two observations with parallax fix scale to metres |
| **Object detection** | Ultralytics YOLO-World v2 (open-vocabulary) | 21-class defense vocab by default; CLIP text encoder |
| **Depth** | DepthAnything-V2 via HuggingFace transformers | Cached locally; inference fully offline after first load |
| **Tello follow** | djitellopy + PD station-keep on a soldier-worn AprilTag | Idle when no Tello on the network |

All model weights are distributed out-of-band (see `models/yolo/README.md`).
No model downloads at runtime once the cache is warm.

## Testing

```bash
cd backend && source .venv/bin/activate
pytest                  # 29 tests, deterministic (FakeClock), no hardware required
```

## What's deliberately not built yet

- Voice intent (Cactus + Gemma on mobile)
- Multi-view object triangulation (the principled successor to monocular depth)
- ORB-SLAM3 C++ backend integration (drop-in via `ORB_SLAM3_ROOT` env)
- Shared-map sync between Tello/mobile and the dashboard (the Follower feed
  endpoint exists but is unwired)

## Constraints

Offline-first · no GPS · recon and situational awareness only (no engagement)
· single plain Tello (AP mode) · no cloud calls at runtime. See `CLAUDE.md`
for the full list.
