# `app/` — the spine (laptop brain, Python)

The core package both clients read from and command through. Producers (perception,
follow, device location) write entities into one world model; consumers (iOS app, dashboard)
subscribe over a WebSocket; the state machine arbitrates client intent into Tello
stage. `stop`/`recall` are always-live and highest priority. Clients **never**
command the Tello directly.

## Owns
The single source of truth: the world model, the WebSocket protocol, the mission
state machine (arbiter), and the video relay (MJPEG + single-JPEG + upload/playback).
Bound to `0.0.0.0` so the phone and dashboard reach it on the local network.

## Flow

```
 perception/     (yolo+depth+slam) ─┐
 follow/         (apriltag)         ├─upsert──► WorldModel ──snapshot──┐
 device_location (phone)            ─┘          (TTL lifecycle)        │
                                                                    ├─► Hub.broadcast ──► clients
 clients ──intent──► server ──► MissionStateMachine.apply ──────────┘   (world_snapshot,
            (Contract B)         (arbiter → stage; follow/ reads it)     mission_state, health,
                                                                         detections)
 mavic_camera ──read_jpeg──► /video/leader.{mjpg,jpg}   tello_camera ──► /video/follower.{mjpg,jpg}
```

Every interface meets at two contracts (`contracts.py`):
- **Contract A — Entity:** the world-model data shape (mirrored in
  [`shared/contracts.ts`](../../shared/contracts.ts) ↔
  [`mobile/Sources/Contracts.swift`](../../mobile/Sources/Contracts.swift)).
- **Contract B — WebSocket messages:** `world_snapshot` / `mission_state` /
  `health` / `detections` (server→clients) and `intent` / `device_location`
  (clients→server).

## Modules

| File | Role | State |
|---|---|---|
| [`contracts.py`](./contracts.py) | Contract A (`Entity`, `Vec3`, `EntityType/Status/Source` enums) + Contract B (`WorldSnapshot`/`MissionState`/`Health`/`Detections`, `IntentMessage`/`DeviceLocation`, `Command`). Pydantic-validated at the boundary; `parse_client_message` rejects unknown intent, never guesses | ✅ |
| [`world_model.py`](./world_model.py) | Single source of truth. `upsert`/`remove`/`snapshot`; owns the `active → stale → lost` TTL lifecycle (producers never set `lost`) and GC past `ttl_s*(lost_factor+1)` | ✅ |
| [`state_machine.py`](./state_machine.py) | The arbiter. `idle/following/holding` transition table + always-live `stop`/`recall` (any stage → stopped/recall); `fail(reason)` records a named error and drops to stopped. `follow/` reads `mission.stage` to drive the Tello | ✅ |
| [`ws_hub.py`](./ws_hub.py) | WebSocket fan-out; `Connection` Protocol so it tests without a real socket; `gather`-based broadcast, drops clients that error on send | ✅ |
| [`video.py`](./video.py) | Mavic frame-source abstraction. `NullSource` (unset), `StreamVideoSource` (cv2.VideoCapture + background reader, latest-frame), `SwitchableSource` (hot-swap RTMP↔file without rewiring consumers); `make_source(spec)` parses `url:`/`file:`/`device:` | ✅ |
| [`server.py`](./server.py) | FastAPI app: `/ws`, `/health`, leader/follower video, upload+playback endpoints; broadcast loop at `BROADCAST_HZ`; constructs and starts perception, follow, Tello, and Mavic sources | ✅ |
| [`clock.py`](./clock.py) | Injectable clock (`RealClock` / `FakeClock`) so TTL + broadcast timing are deterministic under test | ✅ |

## HTTP / WS surface (server.py)

- `GET /ws` — accept, register with the hub, loop on `receive_json` → `parse_client_message`. `intent` → `mission.apply(command)`; `device_location` → upsert a `source=manual` soldier marker (fallback when follow isn't producing one). Malformed messages are dropped (`continue`).
- `GET /health` — JSON `{ok, clients, stage, tello, mavic, perception}`.
- `GET /video/leader.jpg` / `GET /video/follower.jpg` — single latest JPEG (`204` when no frame yet), `no-store`. The dashboard polls these (avoids a perpetual browser loading spinner).
- `GET /video/leader.mjpg` / `GET /video/follower.mjpg` — legacy `multipart/x-mixed-replace` MJPEG; kept for debugging.
- `GET /video/source` / `GET /video/upload/status` — current leader source (kind/label/streaming/rtmp_default) and upload-job status.
- `POST /video/source/rtmp` — restore the env `MAVIC_SOURCE` feed and `perception.reset()`.
- `POST /video/source/upload` — save an uploaded clip, park the live source to `NullSource`, and run `process_video_file` in a background task (YOLO + depth over the whole clip → sidecar JSON). Status flips `uploading → processing → ready`.
- `GET /video/file/{name}` — serve the uploaded clip (byte-range, for `<video>` scrubbing). `GET /video/detections/{name}` — the pre-computed per-timestamp detections/entities the dashboard overlays client-side.

The broadcast loop pushes `WorldSnapshot`, `MissionState`, `Health`, and `Detections`
(`source="leader"`, frame-timestamped boxes) every tick, wrapped in try/except so a
single bad tick never kills the only producer of world/mission/health.

## Subpackages

- [`perception/`](./perception/) — Mavic recon. `PerceptionPipeline` samples the Mavic source at `PERCEPTION_FPS`, runs YOLO (+ optional COCO ensemble) and monocular depth → entities + `DetectionBox`es, with SLAM for pose/anchoring. `health_str`, `latest_boxes()`, `reset()`.
- [`follow/`](./follow/) — Tello soldier-follow. `FollowController` reads Tello frames, detects the soldier AprilTag (bearing/distance), upserts soldier+drone entities, and sends RC to the Tello only when `mission.stage == FOLLOWING` (Track 1, the make-or-break).
- [`tello/`](./tello/) — `TelloClient` (djitellopy, the single owner of the Tello link; auto-reconnecting supervisor; `state`/`TelloState`) and `TelloVideoSource` (FrameSource over the Tello stream). Isolated from follow policy.

## Build notes
- Producers only ever `upsert`; the world model alone owns status. Read the latest
  via `snapshot()` (applies the TTL tick first).
- `parse_client_message` rejects unknown/malformed intent (`continue`, no guess).
- `stop`/`recall` bypass the transition table — honored from any stage.
- All hardware-facing producers are robust to "no hardware present": they report a
  health string instead of crashing, so the server always boots.
- Run from `backend/`: `uvicorn app.server:app --host 0.0.0.0 --port 8000` (or `./run.sh`).
  Env: `MAVIC_SOURCE=url:<stream>|file:<path>|device:<index>` (unset → `NullSource`,
  perception idles), `BROADCAST_HZ` (default `10`), plus YOLO/depth/follow knobs
  (`YOLO_WEIGHTS`, `YOLO_CLASSES`, `YOLO_IMGSZ`, `YOLO_CONF`, `YOLO_COCO_WEIGHTS`,
  `YOLO_COCO_KEEP`, `DEPTH_MODEL` (`off` to disable), `DEPTH_SCALE`, `PERCEPTION_FPS`,
  `ANCHOR_TAG_SIZE_M`, `FOLLOW_TAG_SIZE_M`, `FOLLOW_TAG_ID`, `TELLO_RETRY_S`).
  Tests use `FakeClock` where timing matters.

See [`../README.md`](../README.md) for run/test, [`../../CLAUDE.md`](../../CLAUDE.md)
for the hard constraints.
