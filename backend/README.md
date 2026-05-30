# `backend/` — the laptop brain (Track 2 · Brain · Python)

The single source of truth. Owns the world model, the mission state machine, the
WebSocket fan-out, the video relay, and the only Tello connection. Both clients —
the [iOS app](../mobile/README.md) and the web dashboard — subscribe here; they
never duplicate state and never command the Tello directly.

Offline-first, no GPS, recon/situational-awareness only. See [`../CLAUDE.md`](../CLAUDE.md)
for the hard constraints.

## Setup, test, run

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest/httpx
```

Tests run against the venv interpreter and are deterministic (inject `FakeClock`,
no wall-clock or RNG in assertions):

```bash
cd backend && .venv/bin/python -m pytest -q   # 33 passing
```

Run the server (`run.sh` binds `0.0.0.0:8000` with `--reload`, so both clients
reach it):

```bash
./run.sh
```

Or invoke uvicorn directly with explicit config:

```bash
MAVIC_SOURCE=url:rtmp://localhost:1935/leader \
YOLO_WEIGHTS=$PWD/../models/yolo/yolov8l-worldv2.pt \
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

The server boots cleanly with **no** env vars set — every hardware-facing producer
(Mavic source, Tello link, perception, follow) reports its health string instead
of crashing when nothing is connected.

### Endpoints

- `ws://<host>:8000/ws` — Contract B WebSocket (world/mission/health out, intent/
  device_location in).
- `GET /health` — JSON liveness + client count + stage + tello/mavic/perception
  health.
- `GET /video/leader.jpg` · `GET /video/follower.jpg` — single-frame JPEG, polled
  by the dashboard at ~10 Hz (`204` when no frame yet). This is the primary path.
- `GET /video/leader.mjpg` · `GET /video/follower.mjpg` — legacy
  `multipart/x-mixed-replace` streams, kept for debugging.
- `GET /video/source` · `GET /video/upload/status` — current leader source state
  and upload/processing progress (dashboard `SourceSelector`).
- `POST /video/source/rtmp` · `POST /video/source/upload` — hot-swap the leader
  source between the env RTMP feed and an operator-uploaded clip without restarting.
- `GET /video/file/{name}` · `GET /video/detections/{name}` — serve an uploaded
  clip (with HTTP byte ranges) and its pre-computed per-timestamp detections JSON.

CORS is wide-open (`allow_origins=["*"]`, GET/POST) — the dashboard runs on a
separate port (3001) and this server is LAN-only.

### Env vars

All optional. Read in [`server.py`](./app/server.py).

| Var | Default | Meaning |
|---|---|---|
| `MAVIC_SOURCE` | _(unset)_ | `url:<stream>`, `file:<path>`, or `device:<index>`; unset → `NullSource` (perception idles). Wrapped in a `SwitchableSource` so the operator can hot-swap to an uploaded file at runtime. |
| `YOLO_WEIGHTS` | _(unset)_ | Local YOLO / YOLO-World weights. Without weights, perception runs SLAM-only. |
| `YOLO_CLASSES` | defense vocab when a `-world` checkpoint is loaded, else _(unset)_ | Comma-separated open-vocab prompt set for YOLO-World. |
| `YOLO_IMGSZ` | `960` | YOLO inference image size. |
| `YOLO_CONF` | `0.20` | YOLO confidence threshold. |
| `YOLO_COCO_WEIGHTS` | _(unset)_ | Optional second detector (standard COCO YOLOv8) for high-precision person/vehicle/backpack. Its classes are pruned from the YOLO-World vocab to avoid double-detection. |
| `YOLO_COCO_KEEP` | `person,car,truck,motorcycle,bicycle,bus,backpack` when COCO weights set | COCO labels trusted over open-vocab. |
| `DEPTH_MODEL` | `depth-anything/Depth-Anything-V2-Small-hf` | HF model id / local cache, or `off` to disable monocular depth. |
| `DEPTH_SCALE` | `5.0` | Calibrates inverse-depth → metres. |
| `ANCHOR_TAG_SIZE_M` | `0.20` | AprilTag physical size for the perception metric-scale anchor. |
| `PERCEPTION_FPS` | `5` | Perception loop rate (also the sample rate for offline file processing). |
| `FOLLOW_TAG_SIZE_M` | `0.18` | Soldier-badge AprilTag size for the follow controller. |
| `FOLLOW_TAG_ID` | _(unset)_ | Filter the follow controller to a specific tag id; unset → any tag. |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval. |
| `BROADCAST_HZ` | `10` | world/mission/health/detections fan-out rate. |

## The two contracts everything meets at

Defined in [`app/contracts.py`](./app/contracts.py) (Pydantic), mirrored in
[`../shared/contracts.ts`](../shared/contracts.ts) and `mobile/Sources/Contracts.swift`.

- **Contract A — Entity:** `id` · `type` (`poi`/`hazard`/`object`/`soldier`/`drone`)
  · `position` (`Vec3`, local frame, metres, no GPS) · `confidence` · `timestamp`
  · `source` (`yolo`/`slam`/`follow`/`manual`) · `ttl_s` · `status`
  (`active`/`stale`/`lost`, owned by the world model, never the producer).
- **Contract B — WebSocket protocol:** server→clients `world_snapshot` /
  `mission_state` / `health` / `detections`; clients→server `intent` (closed command
  vocab: `follow_me`/`hold`/`recall`/`stop`) / `device_location`.
  `parse_client_message` validates inbound messages; unknown/malformed intent is
  rejected, never guessed. `stop`/`recall` are always-live, highest priority,
  honored from any stage.

## `app/` package layout

| Module | Role |
|---|---|
| [`contracts.py`](./app/contracts.py) | Contract A + B, Pydantic. |
| [`world_model.py`](./app/world_model.py) | Single source of truth; entity upsert + TTL lifecycle (`active`→`stale`→`lost`). |
| [`state_machine.py`](./app/state_machine.py) | Mission arbiter + event log. Stages `idle`→`following`→`holding`; `recall`/`stopped` from anywhere. |
| [`ws_hub.py`](./app/ws_hub.py) | WebSocket client registry + broadcast fan-out (`Hub`). |
| [`video.py`](./app/video.py) | Frame-source abstraction; `make_source` selects URL/file/device or `NullSource`; `SwitchableSource` allows runtime hot-swap. |
| [`server.py`](./app/server.py) | FastAPI app: `/ws`, `/health`, leader/follower video + upload endpoints, broadcast loop, producer wiring. |
| [`clock.py`](./app/clock.py) | Injectable clock (`RealClock` / `FakeClock`) for deterministic tests. |
| [`perception/`](./app/perception/README.md) | Mavic recon: SLAM, YOLO, depth, fusion pipeline (`PerceptionPipeline`), plus `file_processor.py` for offline clip processing. |
| [`follow/`](./app/follow/README.md) | Tello soldier-follow controller (`FollowController`, AprilTag station-keep). |
| [`tello/`](./app/tello/README.md) | Tello transport: `TelloClient` (djitellopy wrapper, sole commander) + `TelloVideoSource`. |

## Producers

Wired in `server.py` and started on FastAPI `startup`. All are robust to absent
hardware.

- **`PerceptionPipeline`** reads Mavic frames from `mavic_camera` (the
  `SwitchableSource` around `MAVIC_SOURCE`), runs SLAM + YOLO (+ optional depth),
  and upserts entities. Idle when the source is `NullSource`.
- **`FollowController`** reads Tello frames, detects the soldier AprilTag, upserts
  `soldier` + `drone` entities, and sends RC to the Tello when stage=`following`.
  Idle when the Tello link is down (the supervisor thread auto-reconnects every
  `TELLO_RETRY_S`).
- **`device_location`** from the phone upserts a `soldier` entity with
  `source=manual` — the fallback marker before the follow controller is producing
  one, overwritten once it has a higher-quality reading.

## Offline clip processing

`POST /video/source/upload` parks the live source (`NullSource`), saves the clip
under `.context/uploads/`, and runs `perception/file_processor.process_video_file`
over the whole file in a worker thread (YOLO + depth ~150 ms/frame is too slow for
live HD playback on CPU). It writes a `<name>.detections.json` sidecar. The
dashboard polls `/video/upload/status` until `state=="ready"`, then plays the raw
file natively (`<video controls>`) and overlays detections from the cached JSON at
`video.currentTime`.

## Build notes

- The video relay decodes streams with OpenCV/ffmpeg, deliberately **not**
  djitellopy, so the relay stays independent of the flight transport.
- Producers (`perception`, `follow`) upsert entities; the world model alone owns
  `status` demotion. Clients subscribe and arbitrate intent through the state
  machine — never the Tello directly.
- `tests/` covers contracts, world model, state machine, video relay, and SLAM
  (`tests/slam/`).

## Docs

[`../docs/SLAM.md`](../docs/SLAM.md) · [`../docs/VIDEO.md`](../docs/VIDEO.md) ·
[`../docs/VOICE.md`](../docs/VOICE.md) · [`../docs/MOBILE.md`](../docs/MOBILE.md)
