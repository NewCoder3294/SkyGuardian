# `backend/` — the laptop brain (Track 2 · Brain · Python)

The single source of truth. Owns the world model, the mission state machine, the
WebSocket fan-out, the video relay, on-device reasoning, and a Tello controller.
Both clients — the [iOS app](../mobile/README.md) and the web dashboard —
subscribe here and never duplicate state.

> Tello control note: the backend ships a `FollowController` + `ApproachController`
> + `TelloClient`, but in the current build the **phone is the primary Tello
> controller** (on-device visual-"me" / AprilTag-designated follow + voice,
> commanding the Tello directly over its AP at `192.168.10.1:8889`). The laptop
> controllers are an *alternate*. Exactly one controller is armed at a time, now
> enforced by a **code interlock** (`app/follow/arming.py` `ArmingLock`): a laptop
> controller must hold the exclusive lock before driving the Tello, and arming
> owner `"phone"` disarms every laptop controller. It backstops — but does not
> replace — the operating rule, since the phone talks to the Tello over its own AP
> outside the lock. See [`../CLAUDE.md`](../CLAUDE.md).

Offline-first, no GPS, recon/situational-awareness only. See [`../CLAUDE.md`](../CLAUDE.md)
for the hard constraints.

## Setup, test, run

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps (-r requirements.txt) + pytest/httpx
```

`requirements.txt` is runtime only (fastapi, uvicorn[standard], pydantic,
websockets, python-multipart, numpy, opencv-python-headless, pupil-apriltags,
ultralytics, djitellopy). `requirements-dev.txt` includes it and adds
`pytest` + `httpx` (FastAPI test client).

Tests run against the venv interpreter and are deterministic (inject `FakeClock`,
no wall-clock or RNG in assertions):

```bash
cd backend && .venv/bin/python -m pytest -q   # 187 passing
```

Run the server (`run.sh` binds `0.0.0.0:8000` with `--reload`, so both clients
reach it):

```bash
./run.sh
```

There are also two pre-wired demo profiles and an RTMP relay launcher:

- `./run-indoor.sh` — live indoor demo: COCO `yolov8s` for person + backpack,
  the specialty `threat-yolov8n` for `gun` at `YOLO_SPECIALTY_CONF=0.40`,
  YOLO-World off, depth off, `imgsz=480`. Defaults `TELLO_DISABLE=1`.
- `./run-outdoor.sh` — outdoor recon over a recorded clip: YOLO-World back on
  with a defense vocab, COCO `yolov8l` + specialty detector, depth off,
  `imgsz=640`. Defaults `TELLO_DISABLE=1`.
- `./run-relay.sh` — starts the local MediaMTX RTMP relay
  (`mediamtx backend/mediamtx.yml`); publishers push to
  `rtmp://<laptop-lan-ip>:1935/live` and the brain reads the loopback side.

Or invoke uvicorn directly with explicit config:

```bash
MAVIC_SOURCE=url:rtmp://localhost:1935/live \
YOLO_WEIGHTS=$PWD/../models/yolo/yolov8l-worldv2.pt \
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

The server boots cleanly with **no** env vars set — every hardware-facing
producer (Mavic source, Tello link, perception, follow) reports its health
string instead of crashing when nothing is connected, and the intel reasoner
silently disables itself if Ollama is unreachable. Set `TELLO_DISABLE=1` when the
phone owns the Tello (the current demo topology): the backend then skips the
Tello client / camera / follow producers entirely and reports `tello: "disabled"`,
so the laptop can sit on the Tello AP serving the dashboard without contending
for the drone. Mavic recon (perception) is unaffected.

### Endpoints

All routes live in [`server.py`](./app/server.py).

**WebSocket / health**
- `ws://<host>:8000/ws` — Contract B WebSocket (world/mission/health/detections/
  follow_state out; intent/device_location/follow_state/entity_report/label_event
  in). `follow_state` is the phone's relative Tello range/bearing from the soldier
  (plus `target_type`/`target_label` for the dashboard's ME/TAG badge); the laptop
  stores the latest and rebroadcasts it, downgrading to `phase="stale"` after ~2 s
  of silence. `entity_report` upserts the phone's world-frame entities (operator +
  drone) directly into the world model; `label_event` records an operator
  label decision for the data flywheel.
- `GET /health` — JSON liveness + client count + stage + tello/mavic/perception
  health.

**Video**
- `GET /video/leader.jpg` · `GET /video/follower.jpg` — single-frame JPEG,
  polled by the dashboard at ~10 Hz (`204` when no frame yet). This is the
  primary path.
- `GET /video/leader.mjpg` · `GET /video/follower.mjpg` — legacy
  `multipart/x-mixed-replace` streams, kept for debugging.
- `GET /video/source` — current leader source state (kind/label/streaming,
  the RTMP default, and the upload status block).
- `GET /video/upload/status` — granular processing status (polled by the
  dashboard `SourceSelector` during an upload).
- `POST /video/source/rtmp` — switch the leader source to the configured RTMP
  feed (`MAVIC_SOURCE` if set, else the loopback default).
- `POST /video/source/upload` — accept an operator video clip; parks the live
  source, runs perception over the whole file, returns immediately.
- `GET /video/file/{name}` — serve an uploaded clip (HTTP byte ranges, for the
  `<video>` scrubber).
- `GET /video/detections/{name}` — pre-computed per-timestamp detections JSON
  sidecar for an uploaded clip.

**Reasoning (on-device "Gemini Live" equivalent)**
- `GET /intel/summary` — latest local-LLM assessment (`available` = Ollama
  reachable, `running` = inference in flight, plus the summary text + threat
  level + labels). See [`reasoning/intel.py`](./app/reasoning/intel.py).
- `POST /intel/chat` — operator Q&A over the same local model, grounded in the
  latest summary + most-recent detection labels.
- `POST /intel/deep-look` — on-demand single vision pass through a separate
  always-vision reasoner (regardless of `INTEL_VISION`).

**Map**
- `GET /map/buildings` — pre-cached OSM building polygons (projected to local
  metres), served read-only from `.context/buildings.json`. `404` until the
  operator runs `scripts/fetch_buildings.py` once with internet.
- `POST /map/area` — operator request (`MapAreaRequest`: `lat`/`lng`/`radius_m`)
  to re-fetch the OSM buildings layer for a new operational area; on success
  broadcasts a `buildings_updated` signal so clients re-GET `/map/buildings`.

### Control-plane hardening

The state-mutating POSTs (`/video/source/rtmp`, `/video/source/upload`) are a
drone control plane even on a closed LAN, so they get a CSRF/DoS floor:

- **CORS** is an allowlist, not `*` — origins come from `DASHBOARD_ORIGINS`
  (default `http://localhost:3000,http://127.0.0.1:3000`), methods `GET`/`POST`.
- **`OPERATOR_KEY`** (optional): when set, every mutating POST must supply a
  matching `X-Operator-Key` header or it's rejected `401`. No-op when unset
  (local demos stay frictionless).
- **Upload guards**: extension allowlist (`.mp4/.mov/.m4v/.avi/.mkv/.webm`),
  size cap (`MAX_UPLOAD_MB`, default 500, streamed in 1 MiB chunks → `413` on
  overflow), single in-flight upload (`409` on a second), and a uuid-prefixed
  on-disk name so a re-upload can't clobber a clip still being scrubbed.

### Env vars

All optional. Read in [`server.py`](./app/server.py) / [`run.sh`](./run.sh).

**Mavic source / relay**

| Var | Default | Meaning |
|---|---|---|
| `MAVIC_SOURCE` | _(unset)_ | `url:<stream>`, `file:<path>`, or `device:<index>`; unset → `NullSource` (perception idles). Wrapped in a `SwitchableSource` for runtime hot-swap. |
| `MAVIC_RTMP_DEFAULT` | `url:rtmp://127.0.0.1:1935/live` | RTMP target the dashboard "RTMP" button uses when `MAVIC_SOURCE` wasn't set at boot. Matches the local MediaMTX relay expected during a demo. |

**Perception — YOLO**

| Var | Default | Meaning |
|---|---|---|
| `YOLO_WEIGHTS` | _(unset → best bundled COCO model)_ | Local YOLO / YOLO-World weights. Unset → falls back to the best bundled COCO model under `models/` (prefers `yolov8s.pt` over `yolov8n.pt`) so recon detection + designation work out of the box; absence of any weights degrades to SLAM-only. `off` explicitly disables the primary detector (COCO/specialty only). |
| `YOLO_CLASSES` | defense vocab when a `-world` checkpoint is loaded, else _(unset)_ | Comma-separated open-vocab prompt set for YOLO-World (overrides the built-in `_DEFAULT_VOCAB`). |
| `YOLO_IMGSZ` | `960` | YOLO inference image size. |
| `YOLO_CONF` | `0.20` | YOLO confidence threshold. |
| `YOLO_COCO_WEIGHTS` | _(unset)_ | Optional second detector (standard COCO YOLOv8) for high-precision person/vehicle/backpack. When set, its labels are pruned from the YOLO-World vocab so the same object isn't double-detected. |
| `YOLO_COCO_KEEP` | `person,car,truck,motorcycle,bicycle,bus,backpack` (when COCO weights set) | COCO labels trusted over open-vocab. |
| `YOLO_SPECIALTY_WEIGHTS` | _(unset)_ | Optional third detector (e.g. a weapons-finetuned YOLOv8). Runs alongside world + COCO; its raw classes are filtered to `YOLO_SPECIALTY_KEEP`. |
| `YOLO_SPECIALTY_KEEP` | _(unset → all classes pass)_ | Comma-separated class allowlist for the specialty detector. |
| `YOLO_SPECIALTY_CONF` | _(unset → uses `YOLO_CONF`)_ | Per-detector confidence threshold for the specialty model (run it strict, e.g. `0.40`, while the others stay relaxed). |
| `YOLO_DEVICE` | _(unset → auto: MPS / CUDA / library default)_ | Inference device override (`cpu`, `mps`, `cuda:0`). |

**Perception — depth / anchor / loop**

| Var | Default | Meaning |
|---|---|---|
| `DEPTH_MODEL` | `depth-anything/Depth-Anything-V2-Small-hf` | HF model id / local cache, or `off` to disable monocular depth. |
| `DEPTH_SCALE` | `5.0` | Calibrates inverse-depth → metres. |
| `DEPTH_DEVICE` | _(unset → auto: MPS / CUDA / library default)_ | Inference device override for the depth pipeline. |
| `ANCHOR_TAG_SIZE_M` | `0.20` | AprilTag physical size for the perception metric-scale anchor. |
| `PERCEPTION_FPS` | `5` | Perception loop rate (also the sample rate for offline file processing). |

**Follow / Tello**

| Var | Default | Meaning |
|---|---|---|
| `FOLLOW_TAG_SIZE_M` | `0.18` | Soldier-badge AprilTag size for the follow controller. |
| `FOLLOW_TAG_ID` | _(unset)_ | Filter the follow controller to a specific tag id; unset → any tag. |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval. |
| `TELLO_DISABLE` | `0` | `1`/`true`/`yes` skips the Tello client/camera/follow producers at startup and reports `tello: "disabled"`. Use when the phone owns the Tello so the laptop doesn't contend for it. Perception is unaffected. |

**Reasoning (Ollama, local)**

| Var | Default | Meaning |
|---|---|---|
| `INTEL_MODEL` | `gemma3:4b` | Local Ollama model for intel summary + chat. `off` disables reasoning entirely. |
| `INTEL_VISION` | `1` | `1` feeds the current JPEG to the model (image-aware, the demo default); set `0` for the ~30× faster text-only path over the YOLO label list. |
| `INTEL_INTERVAL_S` | `5` | How often the intel loop runs. |

Reasoning is fully local (Ollama at `127.0.0.1:11434`) and auto-disables if the
server is unreachable — no cloud, ever.

**Server / hardening**

| Var | Default | Meaning |
|---|---|---|
| `BROADCAST_HZ` | `10` | world/mission/health/detections fan-out rate. |
| `DASHBOARD_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS allowlist (comma-separated). |
| `OPERATOR_KEY` | _(unset)_ | Shared secret gating mutating POSTs via `X-Operator-Key`. Unset → open. |
| `MAX_UPLOAD_MB` | `500` | Upload size cap (MB). |

## The two contracts everything meets at

Defined in [`app/contracts.py`](./app/contracts.py) (Pydantic), mirrored in
[`../shared/contracts.ts`](../shared/contracts.ts) and `mobile/Sources/Contracts.swift`.

- **Contract A — Entity:** `id` · `type` (`poi`/`hazard`/`object`/`soldier`/`drone`)
  · `position` (`Vec3`, local frame, metres, no GPS) · `confidence` · `timestamp`
  · `source` (`yolo`/`slam`/`follow`/`manual`) · `ttl_s` · `status`
  (`active`/`stale`/`lost`, owned by the world model, never the producer).
- **Contract B — WebSocket protocol:** server→clients `world_snapshot` /
  `mission_state` / `health` / `detections` / `follow_state` (+ `buildings_updated`);
  clients→server `intent` (closed command vocab) / `device_location` /
  `follow_state` / `entity_report` / `label_event`. The detections `source` is
  `"leader"` (recon Mavic) / `"follower"` (companion Tello), abstracting the
  airframe make. `follow_state` carries the companion Tello's range/bearing
  relative to the soldier (`distance_m` 0–200, `bearing_deg` ±360,
  `allow_inf_nan=False`), a `phase` (`disarmed`/`searching`/`confirming`/
  `following`/`lost`/`manual`/`stale`), and the lock's `target_type`
  (`visual_me`/`tag`) + `target_label` for the dashboard's ME/TAG badge —
  deliberately *not* map coordinates, since the phone's follow frame and the Mavic
  SLAM frame aren't co-registered.
  The phone publishes it and the laptop rebroadcasts it (overwriting the advisory
  client `source`), downgrading to `phase="stale"` after ~2 s of silence so the
  dashboard never shows a confident-but-dead reading. `parse_client_message`
  validates inbound messages; unknown/malformed intent is rejected, never guessed.
  `stop`/`recall` are highest priority, honored from any stage.

## `app/` package layout

| Module | Role |
|---|---|
| [`contracts.py`](./app/contracts.py) | Contract A + B, Pydantic (incl. `FollowState` with `target_type`/`target_label`, `EntityReport`, `LabelEvent`, `MapAreaRequest`/`BuildingsUpdated`). |
| [`world_model.py`](./app/world_model.py) | Single source of truth; entity upsert + TTL lifecycle (`active`→`stale`→`lost`). |
| [`state_machine.py`](./app/state_machine.py) | Mission arbiter + event log. Stages `idle`/`following`/`holding`/`approach`; `recall`/`stopped` from anywhere; `fail(reason)` drops to `stopped`. |
| [`designation.py`](./app/designation.py) | `Designator.select` ranks ACTIVE YOLO recon detections (high-value label, confidence then proximity) and the server publishes the pick as a synthetic `designated_target` entity. Read-only. |
| [`ws_hub.py`](./app/ws_hub.py) | WebSocket client registry + broadcast fan-out (`Hub`). |
| [`video.py`](./app/video.py) | Frame-source abstraction; `make_source` selects URL/file/device or `NullSource`; `SwitchableSource` allows runtime hot-swap; `StreamVideoSource` is freshness-windowed. |
| [`clock.py`](./app/clock.py) | Injectable clock (`RealClock` / `FakeClock`) for deterministic tests. |
| [`server.py`](./app/server.py) | FastAPI app: `/ws`, `/health`, video + upload + intel + buildings + map routes, broadcast + intel + approach loops, producer wiring, `ArmingLock` routing, CORS/operator-key hardening. |
| [`reasoning/`](./app/reasoning/) | On-device reasoning over the latest frame + detections via a **local** Ollama model (`IntelReasoner`, `IntelChat`, `IntelSummary`, `ollama_alive`). The offline equivalent of "Gemini Live". |
| [`perception/`](./app/perception/README.md) | Mavic recon: SLAM, YOLO (+ optional COCO + specialty ensemble), depth, fusion pipeline (`PerceptionPipeline`), plus `file_processor.py` for offline clip processing. |
| [`follow/`](./app/follow/README.md) | Tello laptop-side flight path: `FollowController` (AprilTag station-keep) + `ApproachController`, gated behind the `ArmingLock` interlock. |
| [`tello/`](./app/tello/README.md) | Tello transport: `TelloClient` (djitellopy wrapper) + `TelloVideoSource`. |

## Producers

Wired in `server.py` and started on FastAPI `startup`. All are robust to absent
hardware.

- **`PerceptionPipeline`** reads Mavic frames from `mavic_camera` (the
  `SwitchableSource` around `MAVIC_SOURCE`), runs SLAM + YOLO (+ optional COCO
  ensemble + optional depth), and upserts entities. Idle when the source is
  `NullSource`.
- **`FollowController`** (and the alternate **`ApproachController`**) read Tello
  frames, detect the soldier AprilTag (or a YOLO target box for approach), upsert
  `soldier`/`tello` entities, and send RC to the Tello — but only when they hold
  the `ArmingLock` and the mission stage permits (`following`/`recall` for follow,
  `approach` for approach). Both fail closed: no lock, no driving. RECALL is
  bounded (hover on no tag, then fail to `stopped` after `_RECALL_MAX_S`). Idle
  when the Tello link is down (the supervisor thread auto-reconnects every
  `TELLO_RETRY_S`). Set `TELLO_DISABLE=1` to skip the Tello client, camera, and
  these controllers at startup entirely (health reports `tello: "disabled"`) —
  the supported demo topology where the phone owns the Tello.
- **`follow_state`** from the phone (the relative Tello range/bearing/phase) is
  stored with a laptop receipt time and rebroadcast each tick; the broadcast loop
  downgrades it to `phase="stale"` after `_FOLLOW_STALE_S` (~2 s) of silence so a
  dead link can't show a confident follow reading.
- **`device_location`** from the phone upserts a `soldier` entity with
  `source=manual` — the fallback marker before the follow controller produces
  one, overwritten once it has a higher-quality reading.
- **Intel loop** (`_intel_loop`): when `INTEL_MODEL != off` and Ollama is
  reachable, runs `IntelReasoner.summarise` every `INTEL_INTERVAL_S` over the
  latest perception state and publishes via `/intel/summary`.

## Offline clip processing

`POST /video/source/upload` parks the live source (`NullSource`), saves the clip
under `.context/uploads/` (uuid-prefixed name), and runs
`perception/file_processor.process_video_file` over the whole file in a worker
thread (YOLO + depth ~150 ms/frame is too slow for live HD playback on CPU). It
writes a `<name>.detections.json` sidecar. The dashboard polls
`/video/upload/status` until `state=="ready"`, then plays the raw file natively
(`<video controls>`) and overlays detections from the cached JSON at
`video.currentTime`.

## Build notes

- The video relay decodes streams with OpenCV/ffmpeg, deliberately **not**
  djitellopy, so the relay stays independent of the flight transport.
- Producers (`perception`, `follow`) upsert entities; the world model alone owns
  `status` demotion. Clients subscribe and arbitrate intent through the state
  machine.
- The broadcast loop and intel loop each wrap a tick in `try/except` so one bad
  tick can't kill the single producer of world/mission/health.
- `tests/` covers contracts, world model, state machine, video relay, upload
  guards (`test_upload_guards.py`), the `follow_state` contract + rebroadcast/
  fail-stale path (`test_follow_state.py`), the `TELLO_DISABLE` startup skip
  (`test_tello_disable.py`), the `ArmingLock` + bounded-RECALL + freshness-window
  hardening (`test_arming.py`, `test_audit_fixes.py`), designation
  (`test_designation*.py`), the approach controller (`test_approach*.py`),
  perception integration (`test_pipeline_integration.py`), map-area + buildings
  (`test_map_area*.py`), capture packaging/export (`test_capture_*`,
  `test_foundry_*`), and SLAM (`tests/slam/`). See [`tests/README.md`](./tests/README.md).

## Docs

[`../docs/SLAM.md`](../docs/SLAM.md) · [`../docs/VIDEO.md`](../docs/VIDEO.md) ·
[`../docs/VOICE.md`](../docs/VOICE.md) · [`../docs/MOBILE.md`](../docs/MOBILE.md)
