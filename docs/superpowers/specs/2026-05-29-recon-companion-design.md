# Recon & Companion Drone System — Design

**Date:** 2026-05-29
**Status:** Approved (decomposition, contracts, sequencing); spine implemented.
**Spec source of truth:** `../../../CLAUDE.md`

## Pivot (confirmed)
The system is **strictly recon + soldier-companion, offline-first, no engagement**.
The earlier "Jet + Missile interceptor" design (cloud GPU, balloon-popping,
Tello-follows-Mavic) is **fully superseded** and kept only as reference. The Tello
now follows *the soldier* via an AprilTag; recon runs *local* YOLO + SLAM (no cloud).

## Reuse strategy (decided)
**Clean reimplement.** The prior repos (`tello-stream-live-pilot`, `tello-stream`,
`skyguardian-arch`) are reference-only — they inform the design and reveal pitfalls
(UDP socket binding, video freshness, AprilTag motion blur), but no code is copied.
This honors the spec's "reimplement from prior approaches, do not copy wholesale."

## Decomposition
Six subsystems around one spine. Each has one responsibility, a defined interface,
and is independently testable.

1. **WS Server + World Model (spine)** — entity store + lifecycle + 10 Hz broadcast +
   intent intake. Depends on nothing. **Built.**
2. **Follow Controller** (Track 1) — AprilTag → station-keep PD → Tello. Owns the only
   Tello connection. The make-or-break robotics piece.
3. **Perception** (Track 2) — YOLO + SLAM on Mavic feed → entities.
4. **Web Dashboard** (Track 3) — Next.js map, subscribes to spine.
5. **Mobile App** (Track 3) — React Native map + device location + intent.
6. **Voice** (Track 3) — Cactus/Gemma → closed intent enum.

**Boundary rules:** only the follow controller commands the Tello; clients subscribe
(never duplicate state); `stop`/`recall` are first-class always-live intents with a
dedicated phone button.

## Integration contracts (the only two seams)

### Contract A — Entity
`id, type(poi|hazard|object|soldier|drone), position(Vec3 metres, local frame),
confidence(0..1), timestamp, source(yolo|slam|follow|manual), label?, ttl_s, status`.
The **world model owns the lifecycle** (`active→stale→lost` by TTL); producers never
set `lost`. Local frame anchored to launch point + landmarks, no GPS.

### Contract B — WebSocket protocol
- **server→clients** (10 Hz): `world_snapshot` (full snapshot, self-healing),
  `mission_state` (stage + last_error), `health` (tello/mavic/perception).
- **clients→server:** `intent` (closed `Command` enum: `follow_me|hold|recall|stop`),
  `device_location`.
- `command` is a **closed enum** — unknown intents rejected, never guessed.
- `stop`/`recall` are always-live, highest priority, honored from any stage.

Python source of truth: `backend/app/contracts.py`. TS mirror: `shared/contracts.ts`.

## Sequencing (2–3 day hackathon, 2–3 people)
**Hour 0 (all hands):** scaffold repo, commit contracts, empty broadcast. **Done.**

| Track | Day 1 | Day 2 | Day 3 |
|---|---|---|---|
| 1 · Robotics | De-risk follow (standalone) | Wire follow → spine | Tune gains, harden loss/recall |
| 2 · Brain | Spine + state machine | Perception (recorded clips) | Live Mavic + health |
| 3 · Clients | Dashboard + fake injector | Mobile app + intent | Voice + polish |

**Checkpoints:** Day-1 Go/No-Go on the follow; Day-2 clean follow→hold→recall chain;
Day-3 diagnosable per-stage failure view. **2-person fallback:** fold Track 3 into
Track 2; cut voice first.

**Networking:** dual-WiFi is unconfirmed — Day-2 spike, not a blocker; default to the
single-network fallback (laptop + phone both on the Tello AP).

## De-risking
Mocks so no track is hardware-blocked: fake-entity injector (built, `USE_MOCK=1`),
recorded Mavic clips for perception, scripted intent sender for the state machine.

## Testing
Deterministic pytest with an injectable `FakeClock` (no wall-clock in logic). 16
tests green for the spine (world model lifecycle, state machine, contract validation).

## What's built in v1
The spine: contracts (A+B), world model with TTL lifecycle, mission state machine +
event log, WS hub, FastAPI server with 10 Hz broadcast + validated intent intake,
fake-entity injector, deterministic tests, shared TS types, full folder structure
with per-folder READMEs. Verified: server boots, broadcasts mock entities, applies
intent, rejects unknown commands, honors always-live stop.
