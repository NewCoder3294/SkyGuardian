# `app/` — the spine (laptop brain, Python)

The core package both clients read from and command through. Producers (perception,
follow, device location) write entities into one world model; consumers (iOS app, dashboard)
subscribe over a WebSocket; the state machine arbitrates client intent into a Tello
stage. `stop`/`recall` are always-live and highest priority.

> Tello control note: the brain ships a backend `FollowController` (and an approach loop)
> that *can* drive the Tello, but in the current build the **phone is the primary Tello
> controller** (on-device follow loop + voice → `192.168.10.1:8889`). Only one controller is
> armed at a time, now enforced by a **code interlock** (`follow/arming.py` `ArmingLock`):
> a laptop controller must hold the exclusive lock before driving the Tello, and arming owner
> `"phone"` disarms every laptop controller. It backstops — but does not replace — the
> operating rule, since the phone talks to the Tello over its own AP outside the lock. The
> backend flight path is hardened: RECALL is bounded (hover on no reading + `_RECALL_MAX_S`
> cap → STOPPED), arming routes on the resulting mission stage (not the raw command, so a
> rejected transition can't strand the lock) and STOPPED disarms, and `TelloVideoSource` is
> freshness-windowed. Those paths are only exercised with the laptop armed (`TELLO_DISABLE=0`).
> See [`../../CLAUDE.md`](../../CLAUDE.md) for the rule.

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
| [`state_machine.py`](./state_machine.py) | The arbiter. `idle/following/holding/approach` transition table + always-live `stop`/`recall` (any stage → stopped/recall); `fail(reason)` records a named error and drops to stopped. `follow/` reads `mission.stage` to drive the Tello | ✅ |
| [`ws_hub.py`](./ws_hub.py) | WebSocket fan-out; `Connection` Protocol so it tests without a real socket; `gather`-based broadcast, drops clients that error on send | ✅ |
| [`video.py`](./video.py) | Mavic frame-source abstraction. `NullSource` (unset), `StreamVideoSource` (cv2.VideoCapture + background reader, latest-frame, **freshness-windowed**: `_FRESH_WINDOW_S = 3.0` so `read_jpeg()` returns `None` once the decode goes stale), `SwitchableSource` (hot-swap RTMP↔file without rewiring consumers); `make_source(spec)` parses `url:`/`file:`/`device:` | ✅ |
| [`server.py`](./server.py) | FastAPI app: `/ws`, `/health`, leader/follower video, upload+playback, `/intel/*`, `/map/buildings`; broadcast loop at `BROADCAST_HZ` + intel loop at `INTEL_INTERVAL_S`; constructs and starts perception, follow, Tello, Mavic sources, and the intel reasoner. Stores the phone's latest `follow_state` (with a laptop receipt time) and rebroadcasts it each tick, fail-staling it to `phase="stale"` after `_FOLLOW_STALE_S` (~2 s) of silence. `TELLO_DISABLE=1` skips the Tello client/camera/follow producers at startup and makes `_tello_health()` return `"disabled"`. CORS allowlist (`DASHBOARD_ORIGINS`) + optional `OPERATOR_KEY` gate on state-mutating POSTs | ✅ |
| [`clock.py`](./clock.py) | Injectable clock (`RealClock` / `FakeClock`) so TTL + broadcast timing are deterministic under test | ✅ |
| [`designation.py`](./designation.py) | `Designator.select(entities)` picks the top-priority recon detection — entities with `source == YOLO`, `status == ACTIVE` (the ACTIVE filter prevents promoting a STALE/LOST detection), and a high-value label, ranked by confidence desc, ties broken by proximity to launch then id for determinism. `_apply_designation` takes the broadcast tick's single `world.snapshot()` (no double `tick()`) and publishes the pick as a synthetic `designated_target` entity the dashboard reticles. Read-only awareness — commands nothing | ✅ |

## HTTP / WS surface (server.py)

- `GET /ws` — accept, register with the hub, loop on `receive_json` → `parse_client_message`. `intent` → `mission.apply(command)`; `device_location` → upsert a `source=manual` soldier marker (`id="soldier"`, `label="operator"`, `ttl_s=4.0`) as the fallback when follow isn't producing one; `follow_state` → store the phone's latest relative Tello geometry (overwriting the advisory client `source` with `"phone"` and stamping the laptop receipt time `_follow_rx_t`) for the broadcast loop to relay; `entity_report` → upsert the phone's world-frame entities (operator + drone, co-registered against the launch anchor tag) directly into the world model; `label_event` → record an operator confirm/reject/correct decision for the data flywheel. `intent` routing additionally transfers the `ArmingLock` via `_route_arming_for_command(new_stage, arming)` — gated on the **resulting** mission stage, not the raw command, so a rejected transition can't desync the lock. Malformed/unknown messages are dropped (`continue`).
  - **EntityReport id/TTL policy (offline single-trusted-peer threat model).** `EntityReport` validates finiteness and caps the list at 8; the legitimate phone path uses `drone` (and shares the operator marker via the intended `soldier` id). `_apply_entity_report` is hardened so a malformed payload can't corrupt server-owned state: **reserved ids** (`designated_target`, `tello`) are **rejected** (the phone can't clobber follow/server-owned markers), the `timestamp` is **restamped** to the laptop receipt time (`clock.now()`, so a stuck/future client clock can't keep an entity ACTIVE — same discipline as `FollowState`), and `ttl_s` is **clamped** to a small server max (`_MAX_REPORTED_TTL_S`, so a reported marker can't be pinned ACTIVE indefinitely). The world model is otherwise last-writer-wins keyed on `id`.
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
- `POST /map/area` — operator request (`MapAreaRequest`) to re-fetch the OSM buildings layer for a new area; broadcasts a `buildings_updated` signal on success. Operator-gated.
- `POST /intel/deep-look` — on-demand single vision pass through a dedicated always-vision reasoner (`_deep_look_reasoner`), serialized behind the shared Ollama lock.

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

- [`perception/`](./perception/) — Mavic recon. `PerceptionPipeline` samples the Mavic source at `PERCEPTION_FPS`, runs YOLO (+ optional COCO + specialty ensemble) and monocular depth → entities + `DetectionBox`es, with SLAM for pose/anchoring. World-space entity dedup (~2 m grid bucketing) and per-detector confidence thresholds. `health_str`, `latest_boxes()`, `reset()`.
- [`follow/`](./follow/) — Tello laptop-side flight path. `FollowController` reads Tello frames, detects the soldier AprilTag (bearing/distance), upserts soldier+`tello` entities, and sends RC to the Tello only while it holds the `ArmingLock` and `mission.stage` is `FOLLOWING`/`RECALL` (Track 1, the make-or-break). `ApproachController` is the alternate, target-box-driven controller (`mission.stage == APPROACH`). RECALL is bounded (`_RECALL_MAX_S`). Both fail closed without the lock.
- [`tello/`](./tello/) — `TelloClient` (djitellopy, the single owner of the Tello link; auto-reconnecting supervisor; `state`/`TelloState`; `send_rc`/`takeoff`/`land`) and `TelloVideoSource` (FrameSource over the Tello stream). Isolated from follow policy. **Freshness discipline:** like `StreamVideoSource`, `TelloVideoSource.read_jpeg()` now enforces a freshness window (`_FRESH_WINDOW_S` + `_latest_t` recorded on each decode) and returns `None` once the decode goes stale — so a video-only freeze (stream stalls while the 1 Hz heartbeat still answers, keeping `is_connected` true) makes the armed laptop follow loop treat it as "tag lost -> hover" instead of station-keeping on a frozen frame. (Only exercised when the laptop is the armed controller, `TELLO_DISABLE=0`.)
- [`reasoning/`](./reasoning/) — on-device tactical reasoning, the offline equivalent of "Gemini Live". `IntelReasoner.summarise(jpeg, labels)` runs a local Ollama model (default `gemma3:4b`) over the latest frame + YOLO labels → `IntelSummary` (assessment text + `threat_level`); `IntelChat.reply(history, context)` answers operator questions over the same `/api/chat` model; `/intel/deep-look` runs a separate vision-on reasoner; `ollama_alive()` probes liveness. **`INTEL_VISION` now defaults to `1`** (image-aware; `0` is the ~30× faster text-only path). **All three callers — the periodic loop, deep-look, and chat — share one local Ollama** (`127.0.0.1:11434`) and are serialized behind one process-wide `asyncio.Lock` (`_get_ollama_lock()`, acquired around every `summarise()`/chat call) so only one inference runs at a time (the periodic loop additionally exposes a `running` flag for the `/intel/summary` UI). The intel loop still samples `boxes` (6 s perception staleness) and the JPEG (3 s monotonic window) as two independent latest-samples, so the frame and labels can come from different perception ticks — confined to the advisory `_intel_summary` string; a single coherent JPEG+boxes snapshot is the tracked hardening. `httpx`; no cloud.

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
    `ANCHOR_TAG_SIZE_M`. The upload/playback path runs a separate, heavier detector
    stack via `UPLOAD_YOLO_*` overrides (`UPLOAD_YOLO_WEIGHTS`/`_CLASSES`/`_IMGSZ`/
    `_CONF`, `_COCO_WEIGHTS`/`_COCO_KEEP`, `_SPECIALTY_WEIGHTS`/`_SPECIALTY_KEEP`/
    `_SPECIALTY_CONF`); each falls back to its live `YOLO_*` value when unset.
  - Follow / Tello: `FOLLOW_TAG_SIZE_M`, `FOLLOW_TAG_ID`, `TELLO_RETRY_S`,
    `TELLO_DISABLE` (`1` skips the laptop Tello client/camera/follow at startup →
    `tello: "disabled"`; for the demo where the phone owns the Tello).
  - Reasoning: `INTEL_MODEL` (default `gemma3:4b`, `off` disables), `INTEL_VISION`
    (default `1` — image-aware; `0` is the ~30× faster text-only path),
    `INTEL_INTERVAL_S` (default `5`).
  - Hardening: `DASHBOARD_ORIGINS` (CORS allowlist), `OPERATOR_KEY` (optional
    `X-Operator-Key` gate on state-mutating POSTs), `MAX_UPLOAD_MB` (default `500`).
  Tests use `FakeClock` where timing matters.

See [`../README.md`](../README.md) for run/test, [`../../CLAUDE.md`](../../CLAUDE.md)
for the hard constraints.
