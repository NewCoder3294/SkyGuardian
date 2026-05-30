# `app/` — the spine (laptop brain, Python)

The core package both clients read from and command through. Producers (perception,
follow, device location) write entities into one world model; consumers (iOS app, dashboard)
subscribe over a WebSocket; the state machine arbitrates client intent into a Tello
stage. `stop`/`recall` are always-live and highest priority.

> Tello control note: the brain ships a backend `FollowController` that *can* drive
> the Tello, but in the current build the **phone is the primary Tello controller**
> (on-device follow loop + voice → `192.168.10.1:8889`). Only one controller is armed
> at a time; there is no code interlock yet, so the backend controller stays disarmed
> while the phone is flying. See [`../../CLAUDE.md`](../../CLAUDE.md) for the rule.

## Owns
The single source of truth: the world model, the WebSocket protocol, the mission
state machine (arbiter), and the video relay (MJPEG + single-JPEG + upload/playback).
Also hosts the on-device reasoning loop (offline "Gemini Live" equivalent — a local
Ollama model) and the pre-cached OSM buildings endpoint. Bound to `0.0.0.0` so the
phone and dashboard reach it on the local network; the HTTP surface is CORS-allowlisted
and optionally key-gated.

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

 reasoning/intel.py ◄─latest frame+labels─ perception   ──► /intel/summary, /intel/chat
 .context/buildings.json (read-only, pre-cached)         ──► /map/buildings
```

Every interface meets at two contracts (`contracts.py`):
- **Contract A — Entity:** the world-model data shape (mirrored in
  [`shared/contracts.ts`](../../shared/contracts.ts) ↔
  [`mobile/Sources/Contracts.swift`](../../mobile/Sources/Contracts.swift)).
- **Contract B — WebSocket messages:** `world_snapshot` / `mission_state` /
  `health` / `detections` / `follow_state` (server→clients) and `intent` /
  `device_location` / `follow_state` (clients→server — `follow_state` is both
  inbound from the phone and rebroadcast outbound).

## Modules

| File | Role | State |
|---|---|---|
| [`contracts.py`](./contracts.py) | Contract A (`Entity`, `Vec3`, `EntityType/Status/Source` enums) + Contract B (`WorldSnapshot`/`MissionState`/`Health`/`Detections`/`FollowState`, `IntentMessage`/`DeviceLocation`/`FollowState`, `Command`). `FollowState` is both a server→client broadcast and a client→server message: relative Tello range/bearing from the soldier (`distance_m` 0–200, `bearing_deg` ±360, `allow_inf_nan=False`) + a `phase` Literal (`disarmed`/`searching`/`confirming`/`following`/`lost`/`manual`/`stale`), no map coordinates. Pydantic-validated at the boundary; `parse_client_message` rejects unknown intent, never guesses | ✅ |
| [`world_model.py`](./world_model.py) | Single source of truth. `upsert`/`remove`/`snapshot`; owns the `active → stale → lost` TTL lifecycle (producers never set `lost`) and GC past `ttl_s*(lost_factor+1)` | ✅ |
| [`state_machine.py`](./state_machine.py) | The arbiter. `idle/following/holding` transition table + always-live `stop`/`recall` (any stage → stopped/recall); `fail(reason)` records a named error and drops to stopped. `follow/` reads `mission.stage` to drive the Tello | ✅ |
| [`ws_hub.py`](./ws_hub.py) | WebSocket fan-out; `Connection` Protocol so it tests without a real socket; `gather`-based broadcast, drops clients that error on send | ✅ |
| [`video.py`](./video.py) | Mavic frame-source abstraction. `NullSource` (unset), `StreamVideoSource` (cv2.VideoCapture + background reader, latest-frame), `SwitchableSource` (hot-swap RTMP↔file without rewiring consumers); `make_source(spec)` parses `url:`/`file:`/`device:` | ✅ |
| [`server.py`](./server.py) | FastAPI app: `/ws`, `/health`, leader/follower video, upload+playback, `/intel/*`, `/map/buildings`; broadcast loop at `BROADCAST_HZ` + intel loop at `INTEL_INTERVAL_S`; constructs and starts perception, follow, Tello, Mavic sources, and the intel reasoner. Stores the phone's latest `follow_state` (with a laptop receipt time) and rebroadcasts it each tick, fail-staling it to `phase="stale"` after `_FOLLOW_STALE_S` (~2 s) of silence. `TELLO_DISABLE=1` skips the Tello client/camera/follow producers at startup and makes `_tello_health()` return `"disabled"`. CORS allowlist (`DASHBOARD_ORIGINS`) + optional `OPERATOR_KEY` gate on state-mutating POSTs | ✅ |
| [`clock.py`](./clock.py) | Injectable clock (`RealClock` / `FakeClock`) so TTL + broadcast timing are deterministic under test | ✅ |

## HTTP / WS surface (server.py)

- `GET /ws` — accept, register with the hub, loop on `receive_json` → `parse_client_message`. `intent` → `mission.apply(command)`; `device_location` → upsert a `source=manual` soldier marker (`id="soldier"`, `label="operator"`, `ttl_s=4.0`) as the fallback when follow isn't producing one; `follow_state` → store the phone's latest relative Tello geometry (overwriting the advisory client `source` with `"phone"` and stamping the laptop receipt time `_follow_rx_t`) for the broadcast loop to relay. Malformed/unknown messages are dropped (`continue`).
- `GET /health` — JSON `{ok, clients, stage, tello, mavic, perception}`.
- `GET /video/leader.jpg` / `GET /video/follower.jpg` — single latest JPEG (`204` when no frame yet), `no-store`. The dashboard polls these (avoids a perpetual browser loading spinner).
- `GET /video/leader.mjpg` / `GET /video/follower.mjpg` — legacy `multipart/x-mixed-replace` MJPEG; kept for debugging.
- `GET /video/source` / `GET /video/upload/status` — current leader source (kind/label/streaming/rtmp_default/upload) and the single-slot upload-job status.
- `POST /video/source/rtmp` — restore the env `MAVIC_SOURCE` feed (or the loopback `MAVIC_RTMP_DEFAULT`, default `url:rtmp://127.0.0.1:1935/live`) and `perception.reset()`. Operator-gated.
- `POST /video/source/upload` — save an uploaded clip, park the live source to `NullSource`, and run `process_video_file` in a background task (YOLO + depth over the whole clip → sidecar JSON). Status flips `uploading → processing → ready`. Operator-gated; guarded (single in-flight upload → `409`; extension allowlist `_ALLOWED_VIDEO_EXTS` → `400`; size cap `MAX_UPLOAD_MB` → `413`; uuid-prefixed on-disk name).
- `GET /video/file/{name}` — serve the uploaded clip (byte-range, for `<video>` scrubbing). `GET /video/detections/{name}` — the pre-computed per-timestamp detections/entities the dashboard overlays client-side.
- `GET /intel/summary` — latest on-device reasoning result (`available`/`running`/`last_error`/`model` + the `IntelSummary` payload: `text`, `threat_level`, `labels_seen`, `t`, `model`, `latency_ms`).
- `POST /intel/chat` — operator Q&A over the same local Ollama model (`ChatRequest` = up to 20 `{role, content}` messages), grounded in the latest intel summary + observed labels. Returns `{reply, ok, model?}`; degrades to an `ok=false` message when intel is disabled or Ollama is offline.
- `GET /map/buildings` — serve the pre-cached OSM buildings file (`.context/buildings.json`, projected to local metres); `404` with a hint to run `scripts/fetch_buildings.py` if absent.

The broadcast loop pushes `WorldSnapshot`, `MissionState`, `Health`, `Detections`
(`source="leader"`, frame-timestamped boxes — `t = bt`, the real perception-frame
timestamp, not `now`), and — once the phone has reported — the latest `FollowState`
every tick, wrapped in try/except so a single bad tick never kills the only producer
of world/mission/health. If the phone has gone quiet for `_FOLLOW_STALE_S` (~2 s) the
relayed `FollowState` is downgraded to `phase="stale"` (and `active=False`) so the
dashboard never shows a confident-but-dead follow reading. A separate intel loop runs the local
LLM over the latest frame + labels every `INTEL_INTERVAL_S`, skipping when Ollama is
unreachable, an inference is already in flight, or no perception frame has landed yet.

## Subpackages

- [`perception/`](./perception/) — Mavic recon. `PerceptionPipeline` samples the Mavic source at `PERCEPTION_FPS`, runs YOLO (+ optional COCO ensemble) and monocular depth → entities + `DetectionBox`es, with SLAM for pose/anchoring. `health_str`, `latest_boxes()`, `reset()`.
- [`follow/`](./follow/) — Tello soldier-follow. `FollowController` reads Tello frames, detects the soldier AprilTag (bearing/distance), upserts soldier+drone entities, and sends RC to the Tello only when `mission.stage == FOLLOWING` (Track 1, the make-or-break).
- [`tello/`](./tello/) — `TelloClient` (djitellopy, the single owner of the Tello link; auto-reconnecting supervisor; `state`/`TelloState`; `send_rc`/`takeoff`/`land`) and `TelloVideoSource` (FrameSource over the Tello stream). Isolated from follow policy.
- [`reasoning/`](./reasoning/) — on-device tactical reasoning, the offline equivalent of "Gemini Live". `IntelReasoner.summarise(jpeg, labels)` runs a local Ollama model (default `gemma3:4b`) over the latest frame + YOLO labels → `IntelSummary` (assessment text + `threat_level`); `IntelChat.reply(history, context)` answers operator questions over the same `/api/chat` model; `ollama_alive()` probes liveness. Text-only by default (~2–5 s); `INTEL_VISION=1` adds the image-aware path (~30× slower). `httpx` to `127.0.0.1:11434`; no cloud.

## Build notes
- Producers only ever `upsert`; the world model alone owns status. Read the latest
  via `snapshot()` (applies the TTL tick first).
- `parse_client_message` rejects unknown/malformed intent (`continue`, no guess).
- `stop`/`recall` bypass the transition table — honored from any stage.
- All hardware-facing producers are robust to "no hardware present": they report a
  health string instead of crashing, so the server always boots.
- Run from `backend/`: `uvicorn app.server:app --host 0.0.0.0 --port 8000` (or `./run.sh`).
  Env, broadly:
  - Video: `MAVIC_SOURCE=url:<stream>|file:<path>|device:<index>` (unset → `NullSource`,
    perception idles), `MAVIC_RTMP_DEFAULT` (RTMP-button fallback, default
    `url:rtmp://127.0.0.1:1935/live`), `BROADCAST_HZ` (default `10`).
  - Perception: `YOLO_WEIGHTS`, `YOLO_CLASSES` (defaults to `_DEFAULT_VOCAB` for
    `-world` checkpoints), `YOLO_IMGSZ` (default `960`), `YOLO_CONF` (default `0.20`),
    `YOLO_COCO_WEIGHTS` + `YOLO_COCO_KEEP` (optional COCO YOLOv8 ensemble),
    `DEPTH_MODEL` (`off` to disable), `DEPTH_SCALE`, `PERCEPTION_FPS` (default `5`),
    `ANCHOR_TAG_SIZE_M`.
  - Follow / Tello: `FOLLOW_TAG_SIZE_M`, `FOLLOW_TAG_ID`, `TELLO_RETRY_S`,
    `TELLO_DISABLE` (`1` skips the laptop Tello client/camera/follow at startup →
    `tello: "disabled"`; for the demo where the phone owns the Tello).
  - Reasoning: `INTEL_MODEL` (default `gemma3:4b`, `off` disables), `INTEL_VISION`
    (default `0`), `INTEL_INTERVAL_S` (default `5`).
  - Hardening: `DASHBOARD_ORIGINS` (CORS allowlist), `OPERATOR_KEY` (optional
    `X-Operator-Key` gate on state-mutating POSTs), `MAX_UPLOAD_MB` (default `500`).
  Tests use `FakeClock` where timing matters.

See [`../README.md`](../README.md) for run/test, [`../../CLAUDE.md`](../../CLAUDE.md)
for the hard constraints.
