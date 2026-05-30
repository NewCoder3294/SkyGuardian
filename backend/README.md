# `backend/` — the laptop brain (Track 2 · Brain · Python)

The single source of truth. Owns the world model, the mission state machine, the
WebSocket fan-out, the MJPEG video relay, and (later) the only Tello connection.
Both clients — the [iOS app](../mobile/README.md) and the web dashboard — subscribe
here; they never duplicate state and never command the Tello directly.

Offline-first, no GPS, recon/situational-awareness only. See [`../CLAUDE.md`](../CLAUDE.md)
for the hard constraints.

## Setup, test, run

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest/httpx
pytest
```

Run the server (binds `0.0.0.0` so both clients reach it):

```bash
MAVIC_SOURCE=url:rtmp://localhost:1935/leader \
YOLO_WEIGHTS=$PWD/../models/yolo/yolov8l-worldv2.pt \
uvicorn app.server:app --host 0.0.0.0 --port 8001
```

Endpoints: `ws://<host>:<port>/ws` · `GET /health` · `GET /video/leader.jpg` ·
`GET /video/follower.jpg` · legacy MJPEG endpoints at `/video/{leader,follower}.mjpg`.

### Env vars

| Var | Default | Meaning |
|---|---|---|
| `MAVIC_SOURCE` | _(unset)_ | `url:<stream>`, `file:<path>`, or `device:<index>`; unset means no frames. Dashboard reads `/video/leader.jpg`. |
| `YOLO_WEIGHTS` | _(unset)_ | Local YOLO/YOLO-World weights. Without weights, perception runs SLAM-only. |
| `DEPTH_MODEL` | DepthAnything-V2-Small | HF model id, local cache, or `off`. |
| `PERCEPTION_FPS` | `5` | Perception loop rate. |
| `TELLO_RETRY_S` | `3` | Tello supervisor reconnect interval. |
| `BROADCAST_HZ` | `10` | Snapshot/state/health fan-out rate. |

## The two contracts everything meets at

Defined in [`app/contracts.py`](./app/contracts.py) (Pydantic), mirrored in
[`../shared/contracts.ts`](../shared/contracts.ts) and `mobile/Sources/Contracts.swift`.

- **Contract A — Entity:** `id` · `type` (`poi`/`hazard`/`object`/`soldier`/`drone`)
  · `position` (`Vec3`, local frame, metres, no GPS) · `confidence` · `timestamp`
  · `source` (`yolo`/`slam`/`follow`/`manual`) · `ttl_s` · `status`
  (`active`/`stale`/`lost`, owned by the world model, never the producer).
- **Contract B — WebSocket protocol:** server→clients `world_snapshot` /
  `mission_state` / `health`; clients→server `intent` (closed command vocab:
  `follow_me`/`hold`/`recall`/`stop`) / `device_location`. `parse_client_message`
  validates inbound messages; unknown/malformed intent is rejected, never guessed.
  `stop`/`recall` are always-live, highest priority, honored from any stage.

## `app/` package layout

| Module | State | Role |
|---|---|---|
| [`contracts.py`](./app/contracts.py) | ✅ | Contract A + B, Pydantic. |
| [`world_model.py`](./app/world_model.py) | ✅ | Single source of truth; entity upsert + TTL lifecycle (`active`→`stale`→`lost`). |
| [`state_machine.py`](./app/state_machine.py) | ✅ | Mission arbiter + event log. Stages `idle`→`following`→`holding`; `recall`/`stopped` from anywhere. |
| [`ws_hub.py`](./app/ws_hub.py) | ✅ | WebSocket client registry + broadcast fan-out. |
| [`video.py`](./app/video.py) | ✅ | Frame source abstraction; `make_source` selects URL/file/device streams or empty source. |
| [`server.py`](./app/server.py) | ✅ | FastAPI app: `/ws`, `/health`, leader/follower video endpoints, broadcast loop. |
| [`clock.py`](./app/clock.py) | ✅ | Injectable clock (`RealClock` / `FakeClock`) for deterministic tests. |
| [`perception/`](./app/perception/README.md) | 🟡 | Mavic recon: SLAM, YOLO, depth, and fusion pipeline. |
| [`follow/`](./app/follow/README.md) | 🟡 | Tello soldier-follow controller (AprilTag station-keep). |
| [`tello/`](./app/tello/README.md) | 🟡 | Tello transport (djitellopy wrapper + video grab). Consumed by `follow/`. |

## Build notes

- Tests are deterministic: inject `FakeClock`, no wall-clock or RNG in assertions.
  `tests/` covers contracts, world model, state machine, video relay, and SLAM.
- The video relay decodes streams with OpenCV/ffmpeg, deliberately **not**
  djitellopy, so the relay stays independent of the (planned) flight transport.
- Producers (`perception`, `follow`) upsert entities; the world model alone owns
  `status` demotion. Clients subscribe and arbitrate intent through the state
  machine — never the Tello directly.

## Docs

[`../docs/SLAM.md`](../docs/SLAM.md) · [`../docs/VIDEO.md`](../docs/VIDEO.md) ·
[`../docs/VOICE.md`](../docs/VOICE.md) · [`../docs/MOBILE.md`](../docs/MOBILE.md)
