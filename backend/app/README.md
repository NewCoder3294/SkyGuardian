# `app/` — the spine (laptop brain, Python)

The core package both clients read from and command through. Producers (perception,
follow, mock) write entities into one world model; consumers (iOS app, dashboard)
subscribe over a WebSocket; the state machine arbitrates client intent into Tello
stage. `stop`/`recall` are always-live and highest priority. Clients **never**
command the Tello directly.

## Owns
The single source of truth: the world model, the WebSocket protocol, the mission
state machine (arbiter), and the video relay. Bound to `0.0.0.0` so the phone and
dashboard reach it on the local network.

## Flow

```
 perception/ (yolo+slam) ─┐
 follow/      (apriltag)  ├─upsert──► WorldModel ──snapshot──┐
 mock_source  (dev only)  ─┘          (TTL lifecycle)        │
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
| [`video.py`](./video.py) | MJPEG relay. `FrameSource` Protocol + `TelloVideoSource` (raw SDK/UDP + OpenCV decode, not djitellopy), `StreamVideoSource` (Mavic RTSP/HTTP), `MockCameraSource`, `DisabledSource`; `make_source(spec)` | ✅ |
| [`server.py`](./server.py) | FastAPI app: `/ws`, `/health`, `/video/{tello,mavic}`; the broadcast loop at `BROADCAST_HZ`; wires all of the above | ✅ |
| [`clock.py`](./clock.py) | Injectable clock (`RealClock` / `FakeClock`) so TTL + broadcast timing are deterministic under test | ✅ |
| [`mock_source.py`](./mock_source.py) | Dev-only entity injector (drifting soldier/drone/POI/hazard) for hardware-free UI work; opt-in via `USE_MOCK` | ✅ |

## Subpackages

- [`perception/`](./perception/) — Mavic recon: YOLO + SLAM → entities (Track 2).
  `slam/` is ✅ built ([`docs/SLAM.md`](../../docs/SLAM.md)); `yolo.py` / `fusion.py` ⬜ planned.
- [`follow/`](./follow/) — Tello soldier-follow controller, AprilTag station-keep (Track 1, the make-or-break). ⬜ stub (README only).
- [`tello/`](./tello/) — low-level Tello transport, isolated from follow policy. ⬜ stub (README only). Note: live Tello video already lives in `video.py`; this package is for the control link `follow/` will use.

## Build notes
- Producers only ever `upsert`; the world model alone owns status. Read the latest
  via `snapshot()` (applies the TTL tick first).
- `parse_client_message` rejects unknown/malformed intent (`continue`, no guess).
- `stop`/`recall` bypass the transition table — honored from any stage.
- Run from `backend/`: `uvicorn app.server:app --host 0.0.0.0 --port 8011`.
  Env: `TELLO_SOURCE=tello|url:<stream>|mock` (default `tello`),
  `MAVIC_SOURCE=url:<stream>` (unset → empty feed), `USE_MOCK=1` to inject demo
  entities, `BROADCAST_HZ` (default `10`). Tests use `FakeClock` — deterministic.

See [`../README.md`](../README.md) for run/test, [`../../CLAUDE.md`](../../CLAUDE.md)
for the hard constraints.
