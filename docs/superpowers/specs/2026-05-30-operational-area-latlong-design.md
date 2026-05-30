# Operational-Area Lat/Long Input — Design

**Date:** 2026-05-30 · **Track:** Web dashboard + map

## Goal

Let the operator type a latitude/longitude (and radius) in the dashboard and have
the tactical map re-center on real OpenStreetMap building footprints for that area.

This is a **pre-mission staging** action: it touches the internet only at the
moment of fetch, exactly like the already-sanctioned `scripts/fetch_buildings.py`
exception documented in `CLAUDE.md`. Runtime stays fully offline, serving whatever
was last fetched. The UI must label the control as "requires internet — pre-mission
only" so it is never mistaken for a runtime dependency.

## Background (current state)

- The dashboard renders entities in a **local metre frame**: origin = launch point,
  `+x` = east, `+y` = north. `frontend/src/lib/projection.ts` (`MapProjection`)
  only scales metres → screen pixels.
- `.context/buildings.json` carries `{origin:{lat,lng}, radius_m, count, buildings:[…]}`
  where each building polygon is already projected into the local metre frame
  relative to `origin`. Currently `origin` is UCSD (`32.879, -117.232`).
- Those footprints are produced by `scripts/fetch_buildings.py --lat --lng --radius`,
  which queries the OSM Overpass API and projects polygons into local metres. This
  is the **only** internet touch in the system, and it is a one-time pre-mission step.
- The backend serves the file read-only at `GET /map/buildings`
  (`backend/app/server.py`). The dashboard fetches it once over HTTP in
  `frontend/src/components/Buildings.tsx` and `LocalMap2D.tsx`.
- State-mutating routes are gated by `Depends(_require_operator)` (header
  `x-operator-key`, enforced only when `OPERATOR_KEY` is set).
- WS fan-out: `app/ws_hub.py` `broadcast(message: ServerMessage)`; message types are
  defined in `app/contracts.py` (`world_snapshot`, `mission_state`, `health`,
  `detections`, `follow_state`, …) and mirrored in `shared/contracts.ts` and
  `mobile/Sources/Contracts.swift`.

## Decisions (confirmed)

1. Entering lat/long **re-fetches real OSM buildings** for that area (needs internet
   at that moment; runtime stays offline on the last fetch).
2. A successful fetch **overwrites the canonical `.context/buildings.json`** and
   **broadcasts** an update so both the dashboard and the mobile app re-center. The
   previous file is backed up once (`.bak`) so a bad fetch is recoverable.
3. Radius defaults to **400 m** (current value), operator-overridable.
4. The entered point becomes the buildings origin. Entities remain in their local
   metre frame around `(0,0)` — unchanged from today.

## Architecture / data flow

```
Dashboard "Operational Area" control (lat, lng, radius)
   │  POST /map/area   {lat, lng, radius_m}      (operator-key gated)
   ▼
Backend  ─ validate → fetch OSM (Overpass) → project to local metres
         ─ back up existing buildings.json once → overwrite it
         ─ broadcast WS  buildings_updated {origin, radius_m, count, t}
   │
   ▼  (both clients on buildings_updated → re-GET /map/buildings → re-center)
Dashboard map  +  Mobile map
```

## Components

### 1. `backend/app/map_area.py` (new)

Extract the pure fetch+project+write logic so there is a single implementation:

- `fetch_and_project(lat: float, lng: float, radius_m: int) -> dict` — builds the
  Overpass query, fetches (trying the mirror list), projects each polygon into the
  local metre frame (x=east, y=north) relative to `(lat,lng)`, and returns the same
  payload shape as `buildings.json` (`{origin, radius_m, count, buildings}`).
- `write_buildings(payload: dict, path: Path, *, backup: bool = True) -> None` —
  if `backup` and `path` exists, copy it to `path.with_suffix(path.suffix + ".bak")`
  first, then write `payload` atomically (write temp, `os.replace`).

`scripts/fetch_buildings.py` becomes a thin CLI wrapper that imports these (DRY — one
projection implementation, not two). The projection math currently in the script
moves into `map_area.py` verbatim.

### 2. `POST /map/area` (new route in `server.py`)

- Guarded by `Depends(_require_operator)`.
- Request body (pydantic, in `contracts.py`): `MapAreaRequest{lat, lng, radius_m=400}`.
  Validation: `-90 <= lat <= 90`, `-180 <= lng <= 180`, `50 <= radius_m <= 2000`.
  Out-of-range → `422` (pydantic) / explicit `400` with message.
- On success: `payload = fetch_and_project(...)`; `write_buildings(payload, _BUILDINGS_PATH)`;
  `await hub.broadcast(BuildingsUpdated(origin=…, radius_m=…, count=…, t=clock.now()))`;
  return `{origin, radius_m, count}`.
- Overpass/network failure (offline) → raise `HTTPException(503, "…requires internet;
  cached area unchanged")`. The existing `buildings.json` is left untouched (we only
  write after a successful fetch).
- Zero buildings returned → still write (`count: 0`) and return normally; the UI warns.

### 3. `buildings_updated` WS message (new wire type)

Added to `app/contracts.py` as the source of truth, then mirrored in
`shared/contracts.ts` and `mobile/Sources/Contracts.swift`:

```python
class BuildingsUpdated(BaseModel):
    type: Literal["buildings_updated"] = "buildings_updated"
    origin: GeoPoint          # {lat, lng}
    radius_m: int
    count: int
    t: float
```

Carries a signal, not the polygon blob — clients re-pull `/map/buildings` on receipt
(avoids duplicating a large payload over the socket). Added to the `ServerMessage`
union so `broadcast` accepts it.

### 4. Frontend "Operational Area" control (Map tab)

- New component `frontend/src/components/OperationalArea.tsx`: lat / lng / radius
  number inputs + a "Set Area" button, styled with the existing NATO-C2 tokens
  (hard corners, amber data numerals, foliage-green OK, signal-red error).
- State machine: `idle → fetching → success(count) | error(message)`. Error copy for
  the offline case: "No internet — pre-mission only." Disabled button while fetching.
- Posts to `/map/area` with the `x-operator-key` header when configured (reuse
  whatever the dashboard already uses for operator-gated calls; if none exists yet,
  read from `NEXT_PUBLIC_OPERATOR_KEY`).
- `useWorldClient` handles the `buildings_updated` message by bumping a
  `buildingsVersion` counter exposed to consumers. `Buildings.tsx` and
  `LocalMap2D.tsx` add `buildingsVersion` to their fetch `useEffect` dependency so
  they re-GET `/map/buildings` and re-center automatically.

### 5. Mobile

- Mirror `BuildingsUpdated` in `Contracts.swift` (decode parity — the decoder already
  tolerates unknown types, so this is non-breaking).
- If the mobile map renders the OSM building layer, trigger a re-pull of
  `/map/buildings` on receipt; otherwise the decode is a safe no-op. The input UI is
  dashboard-only. Scope kept minimal.

## Error handling

| Condition | Behavior |
|---|---|
| Offline / all Overpass mirrors fail | `503` + clear message; cached `buildings.json` untouched; map unchanged |
| Invalid lat/lng/radius | `400`/`422` with message; no fetch attempted |
| Overpass returns 0 buildings | File written with `count: 0`; UI warns "0 buildings found for this area" |
| Bad/garbled fetch overwrote file | Previous file recoverable from `.bak` |
| `OPERATOR_KEY` set, header missing/wrong | `401`/`403` from `_require_operator` |

## Testing

**Backend (pytest):**
- `map_area.fetch_and_project` projects a mocked Overpass response to the expected
  local-metre offsets (known lat/lng deltas → known x/y metres).
- `write_buildings` backs up an existing file to `.bak` then overwrites; atomic write.
- `POST /map/area` validation rejects out-of-range lat/lng/radius.
- `POST /map/area` offline path: patched `fetch_and_project` raising → `503` and the
  on-disk file is unchanged.
- `POST /map/area` success broadcasts a `buildings_updated` message (assert via a
  recording hub) and returns `{origin, radius_m, count}`.
- Operator-key gating: with `OPERATOR_KEY` set, missing/wrong header → rejected.

**Frontend (vitest):**
- `OperationalArea` state machine: idle → fetching → success/error transitions on
  mocked fetch resolve/reject.
- A `buildings_updated` WS event bumps `buildingsVersion` and triggers a
  `/map/buildings` re-fetch (mock fetch, assert second call).

**Mobile (XCTest):**
- `ContractsTests` decodes a `buildings_updated` frame into the new case.

## Non-goals

- No runtime/online map tiles. Buildings remain a pre-fetched, served-locally layer.
- No GPS, no automatic device-location anchoring — lat/long is operator-entered.
- No multi-area caching/snapping (that was an alternative; not chosen).
- No change to entity positioning or the SLAM local frame.
