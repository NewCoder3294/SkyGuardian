# Cross-Frame Drone Path — Design Spec

**Date:** 2026-05-30
**Status:** Approved (design) — pending spec review
**Repo:** recon-companion (SkyGuardian)

## Problem

The Tello's flight path renders on the **phone** map (on-device `Localizer` +
`LocalMapView.drawTrails`) but not on the **laptop dashboard** map. On the
dashboard the Tello only appears as a relative range/bearing radar (`FollowInset`),
never as a positioned track on `LocalMap2D`.

Root cause: the phone and laptop do **not** share a coordinate frame. The phone
localizes the drone in its own launch frame (operator at origin, follow-tag
distance/bearing rotated by compass heading). The dashboard map is the laptop's
SLAM frame, anchored at the launch AprilTag (`slam/types.py`: *"anchored at the
launch point (the first AprilTag anchor observation) = origin (0,0,0)"*). The two
frames have no shared reference, so the phone's drone position cannot be placed on
the laptop map. This is the documented co-registration gap (see `docs/DEMO.md` §4).

## Goal

Show the **same drone path on both maps**, correctly co-registered, so the Tello
track is consistent even when Mavic SLAM is simultaneously placing recon entities.

Non-goal: GPS, continuous external tracking of the operator, or any cloud
dependency. Offline-first and no-GPS constraints hold (see `CLAUDE.md`).

## Key decision: one shared frame via the launch anchor tag

The laptop's world frame already **is** the launch anchor AprilTag frame. We make
the phone express its localized positions in that same tag frame. With both ends in
one frame, the existing world-model broadcast carries the drone to both maps — the
same mechanism that already puts the soldier dot on both screens.

Confirmed precondition (user, 2026-05-30): at mission start the operator can point
the phone at the **same** anchor AprilTag the Mavic uses to set the map origin.

## Architecture

```
 Phone                                            Laptop (brain)
 ┌──────────────────────────────┐                ┌───────────────────────────┐
 │ AprilTagDetector              │                │ world_model (SoT)         │
 │   observes shared anchor tag  │                │   upserts phone entities  │
 │        │                      │   EntityReport │        │                  │
 │        ▼                      │  (operator +   │        ▼                  │
 │ FrameAligner (NEW)            │   drone, in    │  ws_hub broadcast         │
 │   PnP → T: launch→world frame │   world frame) │        │                  │
 │        │                      │ ─────────────▶ │        ├─▶ Dashboard      │
 │        ▼                      │     (WS)       │        │   LocalMap2D      │
 │ Localizer                     │                │        │   + trail render  │
 │   applies T → world coords    │                │        └─▶ Phone (echo)   │
 │        │                      │                └───────────────────────────┘
 │        ▼                      │
 │ WorldClient.sendEntityReport  │
 └──────────────────────────────┘
```

## Components

### 1. `FrameAligner` (new, `mobile/Sources/FrameAligner.swift`)
- **Purpose:** compute the rigid transform **T** mapping the phone's launch frame
  to the world (anchor-tag) frame.
- **How:** on observing the shared anchor tag, run PnP (Swift port of
  `tag_object_points` / `tag_camera_pose` from `backend/app/perception/slam/anchor.py`)
  to get the phone-camera pose in the tag frame, and derive T (rotation R + translation t).
- **Drift correction:** each fresh anchor observation recomputes T.
- **State:** `unaligned` until the first valid observation; `aligned(T, lastObservedAt)`
  after. No world-frame entities are published while `unaligned`.
- **Interface:** `func observe(tagCorners, K, tagSizeM) -> Result<Transform, AlignError>`;
  `func toWorld(_ p: Vec3) -> Vec3?` (nil when unaligned).
- **Depends on:** `AprilTagDetector` output, camera intrinsics `K`, `ANCHOR_TAG_SIZE_M`.

### 2. `Localizer` change (`mobile/Sources/Localizer.swift`)
- After computing operator + drone positions in the launch frame, map them through
  `FrameAligner.toWorld` before exposing/publishing.
- When unaligned, keep current on-device behavior for the local view but do **not**
  publish world entities (dashboard shows nothing rather than a wrong-frame track).

### 3. Contract — `EntityReport` (approach A)
- **New discriminated-union message** (phone → laptop), added to
  `backend/app/contracts.py`, mirrored in `shared/contracts.ts` and
  `mobile/Sources/Contracts.swift`.
- Payload: `type: "entity_report"`, `entities: [Entity]` (operator + drone) in
  **world frame**, `source: "phone"`, `t`. Reuses the existing `Entity` schema
  (`id`, `type`, `position`, `confidence`, `timestamp`, `source`, `label`).
- Bounded/validated like `FollowState`: finite coords, no NaN/inf, capped count.
- Rationale for A over extending `device_location`: keeps "my location" distinct
  from "entities I localized"; clean discriminated union per the repo's TS rules.

### 4. Backend handler (`backend/app/server.py` WS endpoint)
- On `entity_report`: validate, then upsert each entity into `world_model` with
  `source` preserved (e.g. `follow`/`phone`). Existing `_broadcast_loop` fans the
  updated snapshot to both clients — no new broadcast path.
- Apply the same fail-stale treatment as `follow_state`: phone-sourced entities age
  out via a TTL so a dead phone link doesn't leave a frozen drone on the map.

### 5. Dashboard trail rendering (`frontend/src/components/LocalMap2D.tsx`)
- Add per-entity **position-history accumulation** (ring buffer keyed by entity id),
  for moving types (`soldier`, `drone`), mirroring the phone's `WorldClient`/`LocalMapView`
  trail logic: dedupe movements under ~0.2 m, cap history (~80–240 points).
- Draw polyline trails beneath the entity glyphs (existing `drawEntities`), styled to
  match the phone (`LocalMapView.drawTrails`) so both maps look identical.
- Trail clears when its entity goes stale/absent.

## Data flow

1. Operator aims phone at shared anchor tag → `FrameAligner` computes T.
2. `Localizer` produces operator + drone positions, mapped to world frame via T.
3. `WorldClient` sends `EntityReport` over WS.
4. Backend upserts into `world_model`; `_broadcast_loop` sends `world_snapshot`.
5. Dashboard `LocalMap2D` and phone `LocalMapView` both render the drone glyph +
   accumulated trail — in the same frame, looking identical.
6. Phone re-observes the tag opportunistically → T refreshed → drift corrected.

## Error handling

- **Unaligned phone:** no world entities published; dashboard shows recon-only.
  Phone's local view still works as today.
- **Stale phone link:** TTL ages out phone-sourced entities; trail clears.
- **PnP failure:** `FrameAligner.observe` returns `AlignError`; T unchanged; surface
  an `unaligned`/`stale-alignment` indicator (reuse follow-phase UX patterns).
- **Bad/oversized report:** rejected at the contract boundary, never guessed
  (matches existing intent/device_location validation).

## Testing

- **Swift `FrameAlignerTests`:** synthetic tag corners → known camera pose →
  `toWorld` round-trips a known point within tolerance; rotation/translation
  correctness; `unaligned` returns nil.
- **Backend:** `test_contracts` extension for `EntityReport` (valid + rejects
  NaN/oversized); `world_model` upsert test (phone entity appears in snapshot;
  TTL stale-out).
- **Frontend (vitest):** trail accumulation — sub-0.2m jitter dedupe, ring-buffer
  cap, clear-on-stale.

## Out of scope (future)

- Continuous markerless re-localization (VIO on the phone) for drift-free tracking
  without re-observing the tag.
- Co-registering additional sensors or a second operator.
