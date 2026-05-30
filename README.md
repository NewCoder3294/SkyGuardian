# SkyGuardian — Recon & Companion Drone System

Offline-first situational awareness for dismounted soldiers. A piloted recon
Mavic maps an area (local YOLO + SLAM); a Tello companion follows the soldier via
an AprilTag; a native iOS app and a web dashboard read the same live world model,
show the drone feeds, and talk to the system by voice + buttons. **No cloud, no
internet, no GPS. Recon and situational awareness only — no engagement, ever.**

See [`CLAUDE.md`](./CLAUDE.md) for the spec/hard constraints and
[`docs/`](./docs/) for design + subsystem docs.

## Status

| Subsystem | State |
|---|---|
| **Spine** — world model + WebSocket server + mission state machine | ✅ built, tested |
| **GPS-less SLAM mapping** (monocular VO + AprilTag metric anchor) | ✅ built, tested — [`docs/SLAM.md`](./docs/SLAM.md) |
| **Video relay** — laptop re-streams Tello/Mavic feeds as MJPEG | ✅ built, tested — [`docs/VIDEO.md`](./docs/VIDEO.md) |
| **iOS app** (SwiftUI) — tactical map, drone feed, intent, voice scaffold | ✅ built, tested, on TestFlight — [`mobile/README.md`](./mobile/README.md) |
| **On-device voice + vision** (Gemma 3n via Cactus) | 🟡 scaffolded (builds; needs iOS framework + model) — [`docs/VOICE.md`](./docs/VOICE.md) |
| **Follow controller** (AprilTag station-keep, the make-or-break) | ⬜ not started |
| **Perception** (YOLO detection → entities) | ⬜ not started |
| **Web dashboard** | ⬜ not started |

## Repo layout

```
SkyGuardian/  (local: ~/recon-companion)
├── CLAUDE.md              # the spec + hard constraints (source of truth)
├── shared/contracts.ts   # Contract A+B as TS types (web client imports this)
├── backend/              # LAPTOP BRAIN (Python)
│   ├── app/
│   │   ├── contracts.py      # Contract A (Entity) + B (WS messages), Pydantic
│   │   ├── world_model.py    # single source of truth; entity lifecycle/TTL
│   │   ├── state_machine.py  # mission state machine + event log (arbiter)
│   │   ├── ws_hub.py         # WebSocket fan-out
│   │   ├── video.py          # MJPEG relay: Tello/Mavic/stream sources
│   │   ├── server.py         # FastAPI: /ws, /health, /video/{tello,mavic}
│   │   ├── clock.py          # injectable clock (deterministic tests)
│   │   ├── perception/slam/  # GPS-less monocular mapping (built)
│   │   ├── follow/           # Tello soldier-follow controller (not started)
│   │   └── tello/            # Tello transport (not started)
│   ├── tests/                # pytest (deterministic, FakeClock) — 34 tests
│   └── requirements.txt
├── mobile/               # iOS app (Swift/SwiftUI, XcodeGen, no Expo)
│   ├── Sources/              # app code (map, feed, voice, contracts)
│   ├── Tests/                # XCTest — 15 tests
│   └── project.yml           # XcodeGen project spec
├── scripts/              # asc.py (App Store Connect API), bring-up helpers
├── models/  captures/    # local weights / recorded media (git-ignored)
└── docs/                 # SLAM.md, VIDEO.md, VOICE.md, design specs
```

## The spine — two contracts everything meets at

- **Contract A — Entity:** the shared world-model shape (`shared/contracts.ts` ↔
  `backend/app/contracts.py` ↔ `mobile/Sources/Contracts.swift`).
- **Contract B — WebSocket protocol:** `world_snapshot` / `mission_state` /
  `health` (server→clients) and `intent` / `device_location` (clients→server).

Producers (SLAM, perception, follow) upsert entities; consumers (iOS app,
dashboard) subscribe; the state machine arbitrates intent → Tello. `stop`/`recall`
are always-live and highest priority. Clients **never** command the Tello directly.

## Run the backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                   # 34 tests
# real Tello feed (default), no mock in the path:
USE_MOCK=0 TELLO_SOURCE=tello uvicorn app.server:app --host 0.0.0.0 --port 8011
#   ws://0.0.0.0:8011/ws · http://localhost:8011/health · /video/tello · /video/mavic
```

Env: `TELLO_SOURCE=tello|url:<stream>|mock` (default `tello`),
`MAVIC_SOURCE=url:<rtsp/http>|...` (default disabled → empty feed),
`USE_MOCK=1` injects drifting demo entities for UI dev (off by default).

## Build & ship the iOS app

```bash
cd mobile
xcodegen generate
xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 17'
```
TestFlight ships via the App Store Connect API key (`scripts/asc.py` + the archive
lane). Bundle id `com.nicolasdossantos.skyguardian`. See
[`docs/MOBILE.md`](./docs/MOBILE.md) for the device + Tello-feed test walkthrough.

## Hard constraints (do not violate)
Offline-first · no GPS · recon/situational-awareness only (no engagement) ·
single plain Tello (AP mode) · reimplement from prior approaches, don't copy
wholesale. See `CLAUDE.md`.
