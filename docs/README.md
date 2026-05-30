# docs — Design & Subsystem Docs

Index of the design and per-subsystem docs for SkyGuardian. The root
[`README.md`](../README.md) (status + repo layout + run) and
[`CLAUDE.md`](../CLAUDE.md) (the mission + hard constraints) are the **source of
truth**; the files here go deep on one subsystem each.

## System at a glance

SkyGuardian is an **offline-first, no-GPS, recon-and-situational-awareness-only**
system for dismounted soldiers. Three machines, one local network, no cloud:

```
            [ Soldier w/ Phone (iOS) ]
                  |  voice intent (Gemma 3n via Cactus, on-device) + map subscribe
                  v
[ Manned Mavic ] --video--> [ LAPTOP (the brain) ] <--AP--> [ Tello (follows soldier via AprilTag) ]
                                |  YOLO + depth (detect)
                                |  SLAM (pose / metric local map)
                                |  World model
                                |  FastAPI + WebSocket server
                                v
                       [ Web dashboard ]  +  [ iOS app ]
                          (both subscribe to the same local server)
```

- **Mavic** = manned recon drone (human-piloted), shown as **"leader"** in the
  dashboard. Feeds video to the laptop. The laptop never flies it.
- **Tello** = companion drone that follows the soldier via an AprilTag, shown as
  **"follower"**. A single plain Tello in AP mode; only the laptop commands it.
- **Laptop ("the brain")** = owns the Tello link, runs YOLO + depth + SLAM on the
  Mavic feed, runs the world model and the local FastAPI/WebSocket server, and
  serves the dashboard's MJPEG/JPEG video.
- **Phone** = iOS/SwiftUI client. Reads map + entities, sends voice intent, and
  provides device location. Never commands the Tello directly.

## The spine (backend — `backend/app/`)

The local server is the single source of truth. `server.py` binds `0.0.0.0:8000`
(`backend/run.sh` → `uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload`)
and exposes:

- `GET /ws` — one WebSocket. Broadcasts `world_snapshot` + `mission_state` +
  `health` + `detections` at `BROADCAST_HZ` (default 10); accepts validated
  client `intent` and `device_location` messages (Contract B).
- `GET /health` — JSON liveness (clients, mission stage, tello/mavic/perception).
- `GET /video/leader.jpg` / `GET /video/follower.jpg` — single-frame JPEG, polled.
- `GET /video/leader.mjpg` / `GET /video/follower.mjpg` — legacy MJPEG
  (`multipart/x-mixed-replace`), kept for debugging.
- `GET /video/source`, `POST /video/source/rtmp`, `POST /video/source/upload`,
  `GET /video/upload/status`, `GET /video/file/{name}`, `GET /video/detections/{name}`
  — the leader source selector + pre-recorded clip upload/playback path.

Producers, all robust to "no hardware present" (they report a health string
instead of crashing):

- **`perception/pipeline.py`** — reads Mavic frames (`MAVIC_SOURCE` env), runs
  SLAM + YOLO (+ optional monocular depth), upserts entities. Idle when no source.
- **`follow/controller.py`** (`FollowController`) — reads Tello frames, detects the
  soldier AprilTag, upserts `soldier` + `drone` entities, and sends RC to the
  Tello while `stage == FOLLOWING`. Idle when the Tello link is down.
- **`tello/client.py`** (`TelloClient`, djitellopy-backed) — the only thing that
  talks to the Tello; a supervisor thread auto-reconnects.
- `world_model.py`, `state_machine.py`, `ws_hub.py`, `clock.py` round out the spine.

Contracts live in **`backend/app/contracts.py`** (Pydantic, server-side source of
truth), mirrored by **`shared/contracts.ts`** and **`mobile/Sources/Contracts.swift`**.
Entity types: `poi`, `hazard`, `object`, `soldier`, `drone`. Closed intent
vocabulary: `follow_me`, `hold`, `recall`, `stop` (`stop`/`recall` are always-live,
highest priority).

Tests: `cd backend && .venv/bin/python -m pytest -q` (33 pass).

## Web dashboard (`frontend/`)

Next.js + Tailwind. Runs on its own port (3001) and pulls leader/follower video
as JPEG/MJPEG from the brain; everything else arrives over the `/ws` stream
(`src/lib/useWorldClient.ts`). Components: `Clock`, `ConsolePanel`, `EntityList`,
`IntelPanel`, `LocalMap`, `LocalMap3D`, `SourceSelector`, `StatusBar`,
`ThreatAlert`, `VideoFeed`, `VideoPlayer`.

## Subsystem docs

| Doc | Covers | State |
|---|---|---|
| [`SLAM.md`](./SLAM.md) | GPS-less monocular mapping — Mavic feed → metric local map via VO + AprilTag scale anchor; swappable `MonocularVO` / `ORBSLAM3Runner` backends; honest limitations | ✅ built, tested |
| [`VIDEO.md`](./VIDEO.md) | Laptop video relay — leader/follower JPEG and MJPEG endpoints; env-selected Mavic sources (`url:` / `file:` / `device:` / unset) plus the clip-upload/playback path | ✅ built, tested |
| [`VOICE.md`](./VOICE.md) | On-device voice + vision (Gemma 3n via Cactus) — mic → transcript → closed intent vocab, live-frame Q&A; `cactus.xcframework` embedded, needs the model download | 🟡 framework embedded |
| [`MOBILE.md`](./MOBILE.md) | iOS app build / TestFlight / device test — XcodeGen + ASC API ship lane, and the single-network Tello-feed walkthrough | ✅ built, tested |

## Specs

- [`superpowers/specs/2026-05-29-recon-companion-design.md`](./superpowers/specs/2026-05-29-recon-companion-design.md)
  — approved design: the recon + soldier-companion pivot, clean-reimplement reuse
  strategy, six-subsystem decomposition around the spine, contracts, and sequencing.

## See also

- [`../backend/app/README.md`](../backend/app/README.md) — backend internals.
- [`../mobile/README.md`](../mobile/README.md) — iOS app source/layout.
- [`../shared/README.md`](../shared/README.md) — the shared message contract.
- Hard constraints (offline-first · no GPS · recon only, no engagement · single
  plain Tello in AP mode) live in [`../CLAUDE.md`](../CLAUDE.md).
