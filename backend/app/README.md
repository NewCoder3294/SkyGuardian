# `app/` — the spine (laptop brain, Python)

The core package both clients read from and command through. Producers (perception,
follow, device location) write entities into one world model; consumers (iOS app, dashboard)
subscribe over a WebSocket; the state machine arbitrates client intent into Tello
stage. `stop`/`recall` are always-live and highest priority. Clients **never**
command the Tello directly.

## Owns
The single source of truth: the world model, the WebSocket protocol, the mission
state machine (arbiter), and the video relay. Bound to `0.0.0.0` so the phone and
dashboard reach it on the local network.

## Flow

```
 perception/     (yolo+slam) ─┐
 follow/         (apriltag)  ├─upsert──► WorldModel ──snapshot──┐
 device_location (phone)     ─┘          (TTL lifecycle)        │
                                                             ├─► Hub.broadcast ──► clients
 clients ──intent──► server ──► MissionStateMachine.apply ──┘   (world_snapshot,
            (Contract B)         (arbiter → stage → follow/)     mission_state, health)
                                                             video.py ──MJPEG──► /video/{tello,mavic}
```

Every interface meets at two contracts (`contracts.py`):
- **Contract A — Entity:** the world-model data shape (mirrored in
  [`shared/contracts.ts`](../../shared/contracts.ts) ↔
  [`mobile/Sources/Contracts.swift`](../../mobile/Sources/Contracts.swift)).
- **Contract B — WebSocket messages:** `world_snapshot` / `mission_state` /
  `health` (server→clients) and `intent` / `device_location` (clients→server).

## Modules

| File | Role | State |
|---|---|---|
| [`contracts.py`](./contracts.py) | Contract A (`Entity`, `Vec3`, enums) + Contract B (WS messages); Pydantic-validated at the boundary, unknown intent rejected not guessed | ✅ |
| [`world_model.py`](./world_model.py) | Single source of truth. `upsert`/`remove`/`snapshot`; owns the `active → stale → lost` TTL lifecycle (producers never set `lost`) and GC | ✅ |
| [`state_machine.py`](./state_machine.py) | The arbiter. `idle/following/holding` transitions + always-live `stop`/`recall`; named-failure log. Drives `follow/` once wired | ✅ skeleton |
| [`ws_hub.py`](./ws_hub.py) | WebSocket fan-out; `Connection` Protocol so it tests without a real socket; drops clients that error on send | ✅ |
| [`video.py`](./video.py) | Frame source abstraction. `NullSource` for no configured source and `StreamVideoSource` for URL/file/device streams; `make_source(spec)` | ✅ |
| [`server.py`](./server.py) | FastAPI app: `/ws`, `/health`, leader/follower video endpoints; the broadcast loop at `BROADCAST_HZ`; wires all of the above | ✅ |
| [`clock.py`](./clock.py) | Injectable clock (`RealClock` / `FakeClock`) so TTL + broadcast timing are deterministic under test | ✅ |

## Subpackages

- [`perception/`](./perception/) — Mavic recon: YOLO + SLAM -> entities (Track 2).
  `slam/`, `yolo.py`, `depth.py`, and `fusion.py` are wired through `pipeline.py`.
- [`follow/`](./follow/) — Tello soldier-follow controller, AprilTag station-keep (Track 1, the make-or-break).
- [`tello/`](./tello/) — low-level Tello transport and video source, isolated from follow policy.

## Build notes
- Producers only ever `upsert`; the world model alone owns status. Read the latest
  via `snapshot()` (applies the TTL tick first).
- `parse_client_message` rejects unknown/malformed intent (`continue`, no guess).
- `stop`/`recall` bypass the transition table — honored from any stage.
- Run from `backend/`: `uvicorn app.server:app --host 0.0.0.0 --port 8001`.
  Env: `MAVIC_SOURCE=url:<stream>|file:<path>|device:<index>` (unset -> empty feed)
  and `BROADCAST_HZ` (default `10`). Tests use `FakeClock` where timing matters.

See [`../README.md`](../README.md) for run/test, [`../../CLAUDE.md`](../../CLAUDE.md)
for the hard constraints.
