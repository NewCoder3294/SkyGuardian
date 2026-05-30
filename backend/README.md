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
pytest                                 # 34 tests, deterministic (FakeClock)
```

Run the server (binds `0.0.0.0` so both clients reach it):

```bash
# real Tello feed, no mock in the path:
USE_MOCK=0 TELLO_SOURCE=tello uvicorn app.server:app --host 0.0.0.0 --port 8011

# hardware-free UI dev (drifting demo entities + synthetic frames):
./run.sh                               # USE_MOCK=1, --reload, port 8000
```

Endpoints: `ws://<host>:<port>/ws` · `GET /health` · `GET /video/tello` ·
`GET /video/mavic` (both MJPEG).

### Env vars

| Var | Default | Meaning |
|---|---|---|
| `USE_MOCK` | `1` | `1` injects drifting demo entities + reports `mock` health. Set `0` for real hardware. |
| `TELLO_SOURCE` | `tello` | `tello` (live Tello: raw SDK over UDP + OpenCV/ffmpeg decode, not djitellopy) · `url:<stream>` (any OpenCV/RTSP/HTTP) · `mock` (synthetic) · unset/other → honest empty feed. Phone reads `/video/tello`. |
| `MAVIC_SOURCE` | _(unset)_ | Same grammar; unset → disabled (empty feed). Dashboard reads `/video/mavic`. |
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
| [`video.py`](./app/video.py) | ✅ | MJPEG relay; `make_source` selects Tello / URL stream / mock / disabled. |
| [`server.py`](./app/server.py) | ✅ | FastAPI app: `/ws`, `/health`, `/video/{tello,mavic}`, broadcast loop. |
| [`clock.py`](./app/clock.py) | ✅ | Injectable clock (`RealClock` / `FakeClock`) for deterministic tests. |
| [`mock_source.py`](./app/mock_source.py) | ✅ | Drifting demo entities for hardware-free UI dev (`USE_MOCK=1`). |
| [`perception/`](./app/perception/README.md) | 🟡 | Mavic recon. `slam/` built (GPS-less monocular mapping); YOLO + fusion planned. |
| [`follow/`](./app/follow/README.md) | ⬜ | Tello soldier-follow controller (AprilTag station-keep). The make-or-break piece. |
| [`tello/`](./app/tello/README.md) | ⬜ | Tello transport (djitellopy wrapper + video grab). Consumed only by `follow/`. |

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
