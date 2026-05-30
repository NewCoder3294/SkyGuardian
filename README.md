# Recon & Companion Drone System

Offline-first situational awareness for dismounted soldiers. A piloted recon
Mavic maps an area (local YOLO + SLAM); a Tello companion follows the soldier via
an AprilTag; a mobile app and web dashboard read the same live world model and
talk to the system by voice + buttons. **No cloud, no internet, no GPS. Recon and
situational awareness only — no engagement, ever.**

See [`CLAUDE.md`](./CLAUDE.md) for the full spec and hard constraints, and
[`docs/superpowers/specs/`](./docs/superpowers/specs/) for the design.

## Repo layout

```
recon-companion/
├── CLAUDE.md              # the spec + hard constraints (source of truth)
├── README.md             # this file
├── shared/
│   └── contracts.ts      # Contract A+B as TS types (clients import this)
├── backend/              # LAPTOP BRAIN (Python) — the spine + producers
│   ├── app/
│   │   ├── contracts.py      # Contract A (Entity) + B (WS messages), Pydantic
│   │   ├── world_model.py    # single source of truth; entity lifecycle/TTL
│   │   ├── state_machine.py  # mission state machine + event log (arbiter)
│   │   ├── ws_hub.py         # WebSocket fan-out
│   │   ├── server.py         # FastAPI app, 10Hz broadcast loop, intent intake
│   │   ├── mock_source.py    # fake-entity injector (hardware-free dev)
│   │   ├── clock.py          # injectable clock (deterministic tests)
│   │   ├── follow/           # Track 1 · Tello soldier-follow controller (make-or-break)
│   │   ├── perception/       # Track 2 · Mavic YOLO + SLAM → entities
│   │   └── tello/            # Track 1 · Tello transport (UDP + video)
│   ├── tests/                # pytest (deterministic, FakeClock)
│   ├── requirements.txt
│   └── run.sh
├── frontend/             # Track 3 · Web dashboard (Next.js + Tailwind + shadcn)
├── mobile/               # Track 3 · React Native app (map + device location + voice)
├── models/               # local weights (YOLO/SLAM/Gemma) — git-ignored
├── captures/             # recorded Mavic/Tello media for replay — git-ignored
├── scripts/              # bring-up, networking, dev helpers
└── docs/                 # design specs
```

Every folder has a `README.md` stating its responsibility, owner track, and interface.

## The spine (built — start here)

Two contracts every subsystem meets at:
- **Contract A — Entity:** the shared world-model data shape (`shared/contracts.ts` ↔ `backend/app/contracts.py`).
- **Contract B — WebSocket protocol:** `world_snapshot` / `mission_state` / `health`
  (server→clients) and `intent` / `device_location` (clients→server).

Producers (perception, follow) upsert entities; consumers (dashboard, mobile)
subscribe; the state machine arbitrates intent → Tello. `stop`/`recall` are
always-live and highest priority.

## Run the backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                 # run the spine tests
./run.sh               # USE_MOCK=1 by default: fake entities, no hardware needed
# → ws://0.0.0.0:8000/ws  ·  GET http://localhost:8000/health
```

With `USE_MOCK=1`, a soldier + Tello + POI + hazard drift around the local frame,
so the dashboard and mobile app can be built immediately against live data.

## Tracks (2–3 day hackathon, 2–3 people)

| Track | Owner | Scope |
|---|---|---|
| **1 · Robotics** | A | `follow/` + `tello/` — AprilTag station-keep (make-or-break, Day-1 standalone) |
| **2 · Brain** | B | spine (done) + `perception/` (YOLO + SLAM) + state machine hardening |
| **3 · Clients** | C | `frontend/` + `mobile/` + voice |

**2-person fallback:** fold Track 3 into Track 2 part-time; cut voice first.

## Hard constraints (do not violate)
Offline-first · no GPS · recon/situational-awareness only (no engagement) ·
single plain Tello (AP mode) · fresh repo (reimplement from prior approaches,
don't copy wholesale). See `CLAUDE.md`.
