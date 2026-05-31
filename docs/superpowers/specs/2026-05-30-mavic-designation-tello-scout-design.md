# Mavic Target Designation + Tello Scout — Design Spec

**Date:** 2026-05-30
**Status:** Approved (design) — pending spec review
**Branch:** feat/laptop-approach-real
**Repo:** recon-companion (SkyGuardian)

## Problem & motivation

The codebase ships an `ApproachController` + `_NoTargetDetector` that is a runtime no-op
(no YOLO target detector wired) and, on review, **off-mission**: a drone autonomously
flying *at* a detected target reads as targeting, which violates the project's hard
constraint — *"recon and situational awareness only. No engagement, no targeting, no
attack behavior."* (`CLAUDE.md`). It also assumes the laptop flies the Tello, but the
real topology is **laptop → Mavic recon**, **phone → Tello companion**.

This design replaces that drift with two **role-consistent** capabilities:

- **Mavic** = long-range recon (laptop runs YOLO/SLAM on its feed; not autonomously flown).
- **Tello** = the soldier's companion "pet" — follows the soldier (AprilTag), commanded by the soldier (phone).

## Goals

- **Phase 1 (primary, safe):** the recon Mavic feed automatically **designates** the
  single highest-priority detection — marks it on both maps with threat context. Pure
  situational awareness. No flight.
- **Phase 2 (stretch, risky):** the soldier can command the Tello to perform a **bounded,
  soldier-directed scout maneuver** (forward-and-return), then resume following.

Non-goals: autonomous targeting/pursuit, autonomous Mavic flight, any engagement behavior,
cloud/GPS. Phase 2 is explicitly optional and ships only if Phase 1 is green.

## Phasing & risk

Phase 1 and Phase 2 are independent and on different surfaces (backend/dashboard vs.
mobile flight), so Phase 1 ships even if Phase 2 does not. Implement Phase 1 fully first.

---

## Phase 1 — Mavic Target Designation

### Architecture

```
 Mavic feed → perception (YOLO) → world_model (detection entities)
                                        │
 intel reasoner → threat_level ─────────┤
                                        ▼
                                  Designator (NEW)
                            ranks detections, picks top
                                        │ emits/updates
                                        ▼
                         world_model entity id="designated_target"
                                        │ existing world_snapshot broadcast
                              ┌─────────┴─────────┐
                              ▼                   ▼
                        Dashboard map         Phone map
                     (highlight glyph)     (renders + optional banner)
```

### Components

**`backend/app/designation.py` — `Designator`** (NEW, pure/isolated)
- **Purpose:** from the current world entities + latest intel threat level, select the
  single highest-priority recon detection and produce a designation.
- **Selection:** consider entities with `source == YOLO` whose `label` is in a configurable
  high-value set (default: `{"person", "car", "truck", "vehicle", "backpack"}`). Rank by
  `confidence` desc; tie-break by proximity to launch origin (smaller `‖position‖` first,
  deterministic). Return the top one, or `None` if no candidate.
- **Interface:** `select(entities: list[Entity], threat_level: str) -> Optional[Designation]`
  where `Designation` carries the chosen entity's id, position, label, confidence, threat_level.
- **Pure:** no I/O, no clock; deterministic given inputs → unit-testable.

**Backend wiring (`backend/app/server.py`)**
- Replace the `_NoTargetDetector`/`approach` no-op path. In the perception broadcast cadence
  (the existing loop that already has world + intel), call `Designator.select(...)`:
  - If a target is selected, `world.upsert` an entity `id="designated_target"`,
    `type=EntityType.POI`, `position=<target pos>`, `label=f"DESIGNATED: {cls}"`,
    `source=EntitySource.YOLO`, `confidence=<target conf>`, `ttl_s=3.0` (clears when recon
    stops seeing it).
  - If `None`, do nothing (the TTL ages out any prior designation).
- **Leave the dormant `ApproachController`/`_NoTargetDetector`/`_approach_loop`/
  `Command.APPROACH` code untouched.** It is a harmless runtime no-op (the loop only starts
  when `not TELLO_DISABLED`, which is false in the demo) and removing it would ripple across
  the backend + `shared/contracts.ts` + mobile `Command` enum (breaking the `allCases == 5`
  test) — needless churn and risk before judging. The audit's concern was *claiming* approach
  in the pitch, which is a presentation discipline, not a code requirement. Designation is
  additive and independent. (Removing the dead approach path is noted as optional later cleanup.)

**Dashboard (`frontend/src/components/LocalMap2D.tsx`)**
- Render an entity whose `id === "designated_target"` (or label starts `DESIGNATED`) with a
  distinct glyph: a pulsing/empty ring around the position + threat-colored stroke (red for
  high/elevated threat, amber otherwise), drawn above normal entity glyphs, with the label.
- Existing entities render unchanged.

**Phone (`mobile/`)** — optional within Phase 1
- The designated entity already arrives via `world_snapshot` and renders on the phone map.
- Optional: a small "TARGET DESIGNATED" banner when a `designated_target` entity is present
  (read-only; no new contract).

### Data flow
1. Perception emits YOLO detections into `world_model` (existing).
2. Intel reasoner updates `threat_level` (existing).
3. Each cadence, `Designator.select` ranks detections → top target (or none).
4. Backend upserts/clears the `designated_target` entity.
5. `world_snapshot` broadcasts to both clients; dashboard highlights it; phone shows it.

### Error handling
- No candidates → no designation entity emitted; prior one TTL-clears (never sticky).
- Malformed/empty entity list → `select` returns `None` (no crash).
- Designation is advisory situational awareness; it commands nothing.

### Testing
- `backend/tests/test_designation.py`: ranking (confidence order), high-value class filter,
  tie-break by proximity, empty → None, non-YOLO ignored.
- Backend integration: upsert path emits `designated_target`; clears when no candidate (TTL).
- Frontend vitest: a helper that decides designation styling given an entity (pure), tested
  for ring/threat-color selection.

---

## Phase 2 — Tello Soldier-Commanded Scout (stretch)

### Idea
The soldier commands the pet to scout briefly, then return — soldier-directed and bounded,
never targeting.

### Components (mobile/Swift)
- **New command:** a soldier-triggered `scout` action (button + confirmation dialog, like the
  existing takeoff/track confirmations). Not voice-only.
- **Scout maneuver (`mobile/Sources/` flight logic):** pause the AprilTag follow loop → run a
  **bounded** sequence via `TelloCommander`: forward ~N m (default 3 m, capped), brief hover/scan
  (~2 s), then reverse to return, then resume follow. All distances/durations bounded constants.
- **Safety:** hard **LAND/STOP** always preempts (existing). Uses `ArmingLock` owner `"scout"`
  so control is explicit. Aborts to hover-then-resume on any error or timeout.
- **No laptop involvement** — the phone owns the Tello.

### Risk & testing
- Real Tello flight, phone-side → **device testing only** (no headless/simulator). Build with
  Xcode, dry-run with props off / in a safe space. This is why it's the stretch phase.
- Swift unit test for the maneuver state machine (sequence + bounds + abort) without hardware.

---

## Out of scope (future)
- Cross-frame: designating a target in the Mavic SLAM frame and having the Tello navigate to
  it (requires the co-registration work + autonomous Tello nav; off-mission as pursuit anyway).
- Voice-triggered scout (button-first per the safety rule).
