# Operational-Area Lat/Long Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the dashboard operator enter a lat/long (+ radius) and have the tactical map re-fetch real OSM building footprints for that area, persist them as the served map, and auto-re-center both clients.

**Architecture:** A new `backend/app/map_area.py` holds the single fetch+project+write implementation (extracted from `scripts/fetch_buildings.py`, which becomes a thin CLI wrapper). A new operator-gated `POST /map/area` calls it, overwrites `.context/buildings.json` (backing up the previous file), and broadcasts a `buildings_updated` WS signal. Clients re-GET `/map/buildings` on that signal. A new `OperationalArea` dashboard control drives the POST.

**Tech Stack:** Python 3.13 / FastAPI / pydantic / pytest (backend, run from `backend/` with `pythonpath=.`); Next.js 14 / React / vitest (frontend); Swift / XCTest (mobile decode parity only).

**Spec:** `docs/superpowers/specs/2026-05-30-operational-area-latlong-design.md`

---

## File Structure

- **Create** `backend/app/map_area.py` — pure OSM fetch + ENU projection + atomic write-with-backup. The single implementation.
- **Modify** `scripts/fetch_buildings.py` — thin CLI wrapper that imports `app.map_area` (no duplicated projection logic).
- **Modify** `backend/app/contracts.py` — add `GeoPoint`, `BuildingsUpdated`; add `BuildingsUpdated` to the `ServerMessage` union.
- **Modify** `backend/app/server.py` — add `MapAreaRequest` model + `POST /map/area`; import `map_area`.
- **Modify** `shared/contracts.ts` — mirror `GeoPoint`, `BuildingsUpdated`; add to TS `ServerMessage` union.
- **Modify** `frontend/src/lib/useWorldClient.ts` — handle `buildings_updated`; expose `buildingsVersion`.
- **Modify** `frontend/src/components/Buildings.tsx`, `frontend/src/components/LocalMap2D.tsx` — re-fetch on `buildingsVersion`.
- **Create** `frontend/src/components/OperationalArea.tsx` — the lat/long control.
- **Modify** `frontend/src/app/operator/page.tsx` — mount `OperationalArea` on the Map tab; pass `buildingsVersion` down.
- **Create** `backend/tests/test_map_area.py`, `backend/tests/test_map_area_route.py` — backend tests.
- **Create** `frontend/src/components/OperationalArea.test.tsx`, `frontend/src/lib/useWorldClient.test.ts` (or extend existing) — frontend tests.
- **Modify** `mobile/Tests/ContractsTests.swift` — decode-safety test for `buildings_updated`.

---

## Task 1: Extract map-area logic into `backend/app/map_area.py`

**Files:**
- Create: `backend/app/map_area.py`
- Test: `backend/tests/test_map_area.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_map_area.py
import json
from pathlib import Path

import pytest

from app.map_area import (
    collect_buildings,
    fetch_and_project,
    project_enu,
    write_buildings,
)


def test_project_enu_origin_is_zero():
    assert project_enu(10.0, 20.0, 10.0, 20.0) == (0.0, 0.0)


def test_project_enu_known_offset_at_equator():
    # 0.001 deg east/north at the equator is ~111.32 m for both axes.
    east, north = project_enu(0.001, 0.001, 0.0, 0.0)
    assert abs(east - 111.32) < 0.1
    assert abs(north - 111.32) < 0.1


def test_collect_buildings_projects_one_way():
    overpass = {
        "elements": [
            {
                "type": "way",
                "id": 42,
                "tags": {"building": "yes", "name": "HQ", "building:levels": "2"},
                "geometry": [
                    {"lat": 0.0, "lon": 0.0},
                    {"lat": 0.0, "lon": 0.001},
                    {"lat": 0.001, "lon": 0.001},
                ],
            }
        ]
    }
    out = collect_buildings(overpass, origin_lat=0.0, origin_lng=0.0)
    assert len(out) == 1
    b = out[0]
    assert b["id"] == 42
    assert b["name"] == "HQ"
    assert b["height_m"] == pytest.approx(6.4, abs=0.1)  # 2 levels * 3.2
    assert b["polygon"][0] == [0.0, 0.0]
    assert b["polygon"][1][0] == pytest.approx(111.32, abs=0.1)  # east


def test_write_buildings_backs_up_then_overwrites(tmp_path: Path):
    target = tmp_path / "buildings.json"
    target.write_text(json.dumps({"count": 1, "old": True}))
    write_buildings({"count": 2, "new": True}, target, backup=True)
    assert json.loads(target.read_text())["new"] is True
    bak = target.with_suffix(".json.bak")
    assert json.loads(bak.read_text())["old"] is True


def test_write_buildings_no_backup_when_absent(tmp_path: Path):
    target = tmp_path / "buildings.json"
    write_buildings({"count": 0}, target, backup=True)
    assert json.loads(target.read_text())["count"] == 0
    assert not target.with_suffix(".json.bak").exists()


def test_fetch_and_project_uses_injected_fetcher():
    # fetch_and_project delegates network I/O to a fetcher we can inject, so the
    # projection path is testable offline.
    overpass = {"elements": [{"type": "way", "id": 1, "tags": {"building": "yes"},
                              "geometry": [{"lat": 0.0, "lon": 0.0},
                                           {"lat": 0.0, "lon": 0.001},
                                           {"lat": 0.001, "lon": 0.0}]}]}
    payload = fetch_and_project(1.0, 2.0, 300, _fetcher=lambda q: overpass)
    assert payload["origin"] == {"lat": 1.0, "lng": 2.0}
    assert payload["radius_m"] == 300
    assert payload["count"] == 1
    assert len(payload["buildings"]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_map_area.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.map_area'`.

- [ ] **Step 3: Create `backend/app/map_area.py`**

Move the pure logic out of `scripts/fetch_buildings.py` verbatim, renaming `_project_enu` → `project_enu` (public, tested), and add the two new public functions. Network I/O is injectable via `_fetcher`.

```python
# backend/app/map_area.py
"""OSM-buildings fetch + ENU projection + atomic write for the offline map layer.

Single implementation shared by the one-time CLI (`scripts/fetch_buildings.py`)
and the dashboard's POST /map/area endpoint. Fetching OSM REQUIRES internet and
is a pre-mission staging step only — runtime serves the cached result offline.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Callable, Iterable
from urllib import request

_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
)


def overpass_query(lat: float, lng: float, radius_m: int) -> str:
    return (
        f"[out:json][timeout:60];"
        f'(way["building"](around:{radius_m},{lat},{lng});'
        f'relation["building"](around:{radius_m},{lat},{lng}););'
        "out geom tags;"
    )


def fetch_overpass(query: str) -> dict:
    """POST to Overpass; try each mirror until one returns 200. Raises
    RuntimeError if every mirror fails (e.g. offline)."""
    last_err: Exception | None = None
    body = query.encode("utf-8")
    for url in _OVERPASS_ENDPOINTS:
        try:
            req = request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "SkyGuardian/1.0 buildings-fetcher (one-time, local cache)",
                },
            )
            with request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - any failure → try next mirror
            last_err = exc
            continue
    raise RuntimeError(f"All Overpass endpoints failed; last: {last_err}")


def project_enu(lat: float, lng: float, origin_lat: float, origin_lng: float) -> tuple[float, float]:
    """(lat, lng) -> (east_m, north_m) relative to origin. Equirectangular
    approximation; <1 m error over the few-hundred-metre radii we care about."""
    earth_r = 6_378_137.0
    olat = math.radians(origin_lat)
    east = math.radians(lng - origin_lng) * earth_r * math.cos(olat)
    north = math.radians(lat - origin_lat) * earth_r
    return (east, north)


def _height_metres(tags: dict) -> float:
    raw = tags.get("height") or tags.get("building:height")
    if raw:
        try:
            return float(str(raw).split()[0].replace("m", "").strip())
        except ValueError:
            pass
    levels = tags.get("building:levels") or tags.get("levels")
    if levels:
        try:
            return max(3.0, float(levels) * 3.2)
        except ValueError:
            pass
    return 6.0


def _polygons_from_way(way: dict) -> Iterable[list[list[float]]]:
    geom = way.get("geometry") or []
    if len(geom) < 3:
        return
    ring = [[p["lat"], p["lon"]] for p in geom]
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) >= 3:
        yield ring


def _polygons_from_relation(rel: dict) -> Iterable[list[list[float]]]:
    for m in rel.get("members", []):
        if m.get("type") != "way" or m.get("role") not in (None, "", "outer"):
            continue
        geom = m.get("geometry") or []
        ring = [[p["lat"], p["lon"]] for p in geom]
        if ring and ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) >= 3:
            yield ring


def collect_buildings(overpass_json: dict, origin_lat: float, origin_lng: float) -> list[dict]:
    out: list[dict] = []
    for el in overpass_json.get("elements", []):
        tags = el.get("tags") or {}
        if "building" not in tags:
            continue
        height = _height_metres(tags)
        name = tags.get("name") or tags.get("addr:housename")
        if el.get("type") == "way":
            rings = list(_polygons_from_way(el))
        elif el.get("type") == "relation":
            rings = list(_polygons_from_relation(el))
        else:
            continue
        for ring in rings:
            projected = [list(project_enu(p[0], p[1], origin_lat, origin_lng)) for p in ring]
            out.append({
                "id": el.get("id"),
                "name": name,
                "height_m": round(height, 1),
                "polygon": [[round(x, 2), round(y, 2)] for x, y in projected],
            })
    return out


def fetch_and_project(
    lat: float,
    lng: float,
    radius_m: int,
    *,
    _fetcher: Callable[[str], dict] | None = None,
) -> dict:
    """Fetch OSM buildings around (lat, lng) and project them to the local frame.
    Returns the same payload shape as .context/buildings.json. `_fetcher` is a
    test seam; defaults to the live Overpass fetch."""
    fetcher = _fetcher or fetch_overpass
    raw = fetcher(overpass_query(lat, lng, radius_m))
    buildings = collect_buildings(raw, lat, lng)
    return {
        "origin": {"lat": lat, "lng": lng},
        "radius_m": radius_m,
        "count": len(buildings),
        "buildings": buildings,
    }


def write_buildings(payload: dict, path: Path, *, backup: bool = True) -> None:
    """Atomically write `payload` to `path`. If `backup` and `path` exists, copy
    it to `<path>.bak` first so a bad fetch is recoverable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        path.with_suffix(path.suffix + ".bak").write_bytes(path.read_bytes())
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_map_area.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/map_area.py backend/tests/test_map_area.py
git commit -m "feat(backend): extract map_area fetch/project/write logic with tests"
```

---

## Task 2: Make `scripts/fetch_buildings.py` a thin CLI wrapper

**Files:**
- Modify: `scripts/fetch_buildings.py`
- Test: `backend/tests/test_map_area.py` (add one import/delegation test)

- [ ] **Step 1: Add a failing test that the script delegates to `map_area`**

Append to `backend/tests/test_map_area.py`:

```python
def test_fetch_buildings_script_reuses_map_area():
    # The CLI must not re-implement projection; it imports from app.map_area.
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "fetch_buildings.py"
    src = script.read_text()
    assert "from app.map_area import" in src or "import app.map_area" in src
    assert "def project_enu" not in src  # logic lives in map_area, not duplicated
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_map_area.py::test_fetch_buildings_script_reuses_map_area -v`
Expected: FAIL — the script still defines `project_enu` / `collect_buildings` inline.

- [ ] **Step 3: Rewrite `scripts/fetch_buildings.py` as a wrapper**

```python
"""One-time OSM-buildings downloader for the offline map layer (CLI wrapper).

The fetch + projection + write logic lives in backend/app/map_area.py so the
dashboard's POST /map/area and this CLI share one implementation. REQUIRES
internet (Overpass); run once before going offline.

Usage:
  python3 scripts/fetch_buildings.py --lat 37.7749 --lng -122.4194 --radius 400 \
      --out .context/buildings.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `app` importable when run as a loose script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.map_area import fetch_and_project, write_buildings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="One-time OSM building cache for offline map.")
    ap.add_argument("--lat", type=float, required=True, help="origin latitude (degrees)")
    ap.add_argument("--lng", type=float, required=True, help="origin longitude (degrees)")
    ap.add_argument("--radius", type=int, default=400, help="metres around origin (default 400)")
    ap.add_argument("--out", type=Path, default=Path(".context") / "buildings.json", help="output JSON path")
    args = ap.parse_args()

    print(f"[buildings] querying overpass for buildings within {args.radius}m "
          f"of ({args.lat:.5f}, {args.lng:.5f})…")
    payload = fetch_and_project(args.lat, args.lng, args.radius)
    print(f"[buildings] collected {payload['count']} building polygons")
    write_buildings(payload, args.out, backup=True)
    print(f"[buildings] wrote {args.out} ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_map_area.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_buildings.py backend/tests/test_map_area.py
git commit -m "refactor(scripts): fetch_buildings.py delegates to app.map_area"
```

---

## Task 3: Add `GeoPoint` + `BuildingsUpdated` to backend contracts

**Files:**
- Modify: `backend/app/contracts.py` (add models after `FollowState`, update `ServerMessage` union at line ~162)
- Test: `backend/tests/test_contracts.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_contracts.py`:

```python
def test_buildings_updated_serializes():
    from app.contracts import BuildingsUpdated, GeoPoint

    msg = BuildingsUpdated(origin=GeoPoint(lat=32.0, lng=-117.0), radius_m=400, count=12, t=3.5)
    dumped = msg.model_dump(mode="json")
    assert dumped["type"] == "buildings_updated"
    assert dumped["origin"] == {"lat": 32.0, "lng": -117.0}
    assert dumped["radius_m"] == 400
    assert dumped["count"] == 12
    assert dumped["t"] == 3.5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py::test_buildings_updated_serializes -v`
Expected: FAIL — `ImportError: cannot import name 'BuildingsUpdated'`.

- [ ] **Step 3: Add the models and extend the union**

In `backend/app/contracts.py`, immediately before the line `ServerMessage = Union[...]`:

```python
class GeoPoint(BaseModel):
    """A WGS84 lat/lng. Used to geo-reference the local map frame's origin."""
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)


class BuildingsUpdated(BaseModel):
    """Signal that the served OSM buildings layer changed (operator set a new
    operational area). Clients re-GET /map/buildings on receipt — the polygon
    blob is intentionally NOT carried over the socket."""
    type: Literal["buildings_updated"] = "buildings_updated"
    origin: GeoPoint
    radius_m: int
    count: int
    t: float
```

Then change the union line from:

```python
ServerMessage = Union[WorldSnapshot, MissionState, Health, Detections, FollowState]
```

to:

```python
ServerMessage = Union[WorldSnapshot, MissionState, Health, Detections, FollowState, BuildingsUpdated]
```

Confirm `Field` is already imported in `contracts.py` (it is — `DetectionBox` uses it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -v`
Expected: PASS (all existing + the new test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts.py backend/tests/test_contracts.py
git commit -m "feat(contracts): add GeoPoint + buildings_updated message"
```

---

## Task 4: Add `POST /map/area` route

**Files:**
- Modify: `backend/app/server.py` (import `map_area`; add `MapAreaRequest` near other request models; add the route near `GET /map/buildings` at line ~643)
- Test: `backend/tests/test_map_area_route.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_map_area_route.py
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import server
from app.contracts import BuildingsUpdated, MapAreaRequest


class FakeHub:
    def __init__(self):
        self.sent = []

    async def broadcast(self, message):
        self.sent.append(message)


def _payload():
    return {"origin": {"lat": 1.0, "lng": 2.0}, "radius_m": 300, "count": 1,
            "buildings": [{"id": 1, "name": None, "height_m": 6.0, "polygon": [[0, 0], [1, 0], [1, 1]]}]}


def test_map_area_request_rejects_out_of_range():
    with pytest.raises(ValidationError):
        MapAreaRequest(lat=999.0, lng=0.0, radius_m=400)
    with pytest.raises(ValidationError):
        MapAreaRequest(lat=0.0, lng=0.0, radius_m=5)  # below 50 m floor


def test_map_area_success_writes_and_broadcasts(tmp_path: Path, monkeypatch):
    target = tmp_path / "buildings.json"
    fake_hub = FakeHub()
    monkeypatch.setattr(server, "_BUILDINGS_PATH", target)
    monkeypatch.setattr(server, "hub", fake_hub)
    monkeypatch.setattr(server.map_area, "fetch_and_project", lambda lat, lng, r: _payload())

    req = MapAreaRequest(lat=1.0, lng=2.0, radius_m=300)
    result = asyncio.run(server.post_map_area(req, None))

    assert result == {"origin": {"lat": 1.0, "lng": 2.0}, "radius_m": 300, "count": 1}
    assert json.loads(target.read_text())["count"] == 1
    assert len(fake_hub.sent) == 1
    msg = fake_hub.sent[0]
    assert isinstance(msg, BuildingsUpdated)
    assert msg.origin.lat == 1.0 and msg.count == 1


def test_map_area_offline_leaves_file_untouched(tmp_path: Path, monkeypatch):
    target = tmp_path / "buildings.json"
    target.write_text(json.dumps({"count": 99, "sentinel": True}))
    fake_hub = FakeHub()
    monkeypatch.setattr(server, "_BUILDINGS_PATH", target)
    monkeypatch.setattr(server, "hub", fake_hub)

    def boom(lat, lng, r):
        raise RuntimeError("All Overpass endpoints failed")

    monkeypatch.setattr(server.map_area, "fetch_and_project", boom)

    req = MapAreaRequest(lat=1.0, lng=2.0, radius_m=300)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(server.post_map_area(req, None))
    assert ei.value.status_code == 503
    assert json.loads(target.read_text())["sentinel"] is True  # unchanged
    assert fake_hub.sent == []


def test_require_operator_rejects_when_key_set(monkeypatch):
    monkeypatch.setattr(server, "_OPERATOR_KEY", "secret")
    with pytest.raises(HTTPException) as ei:
        server._require_operator(x_operator_key="wrong")
    assert ei.value.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_map_area_route.py -v`
Expected: FAIL — `ImportError: cannot import name 'MapAreaRequest'` / `server` has no `post_map_area`.

- [ ] **Step 3: Add the request model, import, and route**

In `backend/app/contracts.py`, after `BuildingsUpdated`, add the request model (it lives with the wire contracts):

```python
class MapAreaRequest(BaseModel):
    """Operator request to re-fetch the OSM buildings layer for a new area."""
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    radius_m: int = Field(default=400, ge=50, le=2000)
```

In `backend/app/server.py`, add to the contracts import block (the existing `from .contracts import (...)` group) the names `BuildingsUpdated` and `MapAreaRequest`, and add a module import near the other `from .` imports:

```python
from . import map_area
```

Then add the route right after the `GET /map/buildings` handler (~line 656). The handler is referenced by tests as `server.post_map_area`, so it must be a module-level `async def`:

```python
@app.post("/map/area")
async def post_map_area(
    req: MapAreaRequest,
    _: None = Depends(_require_operator),
) -> dict:
    """Re-fetch OSM buildings for a new operational area, overwrite the served
    cache, and broadcast a buildings_updated signal. REQUIRES internet at call
    time (pre-mission staging); on failure the cached layer is left untouched."""
    try:
        payload = map_area.fetch_and_project(req.lat, req.lng, req.radius_m)
    except Exception as exc:  # noqa: BLE001 - any fetch failure → 503, cache intact
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch buildings (requires internet); cached area unchanged: {exc}",
        )
    map_area.write_buildings(payload, _BUILDINGS_PATH, backup=True)
    await hub.broadcast(
        BuildingsUpdated(
            origin=payload["origin"],
            radius_m=payload["radius_m"],
            count=payload["count"],
            t=clock.now(),
        )
    )
    return {"origin": payload["origin"], "radius_m": payload["radius_m"], "count": payload["count"]}
```

(`BuildingsUpdated(origin=payload["origin"], ...)` accepts the `{"lat","lng"}` dict because pydantic coerces it into `GeoPoint`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_map_area_route.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts.py backend/app/server.py backend/tests/test_map_area_route.py
git commit -m "feat(backend): POST /map/area re-fetches + broadcasts buildings layer"
```

---

## Task 5: Mirror contracts in `shared/contracts.ts`

**Files:**
- Modify: `shared/contracts.ts` (add interfaces near `FollowState`; extend `ServerMessage` union)

- [ ] **Step 1: Add the interfaces**

In `shared/contracts.ts`, after the `FollowState` interface, add:

```ts
/** A WGS84 lat/lng — geo-reference for the local map frame origin. */
export interface GeoPoint {
  lat: number;
  lng: number;
}

/**
 * Signal that the served OSM buildings layer changed (operator set a new
 * operational area). Clients re-GET /map/buildings on receipt.
 */
export interface BuildingsUpdated {
  type: "buildings_updated";
  origin: GeoPoint;
  radius_m: number;
  count: number;
  t: number;
}
```

- [ ] **Step 2: Extend the `ServerMessage` union**

Change:

```ts
export type ServerMessage =
  | WorldSnapshot
  | MissionState
  | Health
  | Detections
  | FollowState;
```

to add `| BuildingsUpdated;` as the final member.

- [ ] **Step 3: Verify the frontend still type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (a clean baseline; the new union member is additive).

- [ ] **Step 4: Commit**

```bash
git add shared/contracts.ts
git commit -m "feat(contracts): mirror buildings_updated in shared TS contracts"
```

---

## Task 6: Handle `buildings_updated` in `useWorldClient` + re-fetch buildings

**Files:**
- Create: `frontend/vitest.config.ts` (jsdom env for component/hook tests)
- Modify: `frontend/src/lib/useWorldClient.ts`
- Modify: `frontend/src/components/Buildings.tsx`, `frontend/src/components/LocalMap2D.tsx`
- Test: `frontend/src/lib/useWorldClient.test.ts` (create)

- [ ] **Step 0: Set up a DOM test environment (one-time)**

The existing vitest specs (`feedUrl.test.ts`, `wsConfig.test.ts`) are pure-logic and run in vitest's default node environment with no config file. Component/hook tests need jsdom + React Testing Library. Install and configure:

```bash
cd frontend && npm i -D jsdom @testing-library/react @testing-library/dom
```

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

// jsdom so component/hook tests have a DOM; `automatic` JSX so .tsx tests don't
// need an explicit React import. The existing pure-logic specs run fine here too.
export default defineConfig({
  test: {
    environment: "jsdom",
  },
  esbuild: {
    jsx: "automatic",
  },
});
```

Verify the existing specs still pass under the new config:
Run: `cd frontend && npx vitest run src/lib/feedUrl.test.ts src/lib/wsConfig.test.ts`
Expected: PASS (no regressions).

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/useWorldClient.test.ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWorldClient } from "./useWorldClient";

// Minimal fake WebSocket capturing the instance so the test can push frames.
class FakeWS {
  static last: FakeWS | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  readyState = 1;
  constructor(public url: string) {
    FakeWS.last = this;
  }
  send() {}
  close() {}
}

describe("useWorldClient buildings_updated", () => {
  beforeEach(() => {
    (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS as unknown;
  });
  afterEach(() => vi.restoreAllMocks());

  it("bumps buildingsVersion on a buildings_updated frame", () => {
    const { result } = renderHook(() => useWorldClient("ws://x/ws"));
    const v0 = result.current.buildingsVersion;
    act(() => {
      FakeWS.last!.onmessage!({
        data: JSON.stringify({
          type: "buildings_updated",
          origin: { lat: 1, lng: 2 },
          radius_m: 400,
          count: 5,
          t: 1,
        }),
      });
    });
    expect(result.current.buildingsVersion).toBe(v0 + 1);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/lib/useWorldClient.test.ts`
Expected: FAIL — `buildingsVersion` is `undefined`.

- [ ] **Step 3: Add `buildingsVersion` to the hook**

In `frontend/src/lib/useWorldClient.ts`:

Add to the `WorldClientState` interface:

```ts
  /** Increments each time the server signals the buildings layer changed,
   *  so map components can re-fetch /map/buildings. */
  buildingsVersion: number;
```

Add the state near the other `useState` declarations:

```ts
  const [buildingsVersion, setBuildingsVersion] = useState(0);
```

Add a case in the `apply` switch:

```ts
      case "buildings_updated":
        setBuildingsVersion((v) => v + 1);
        break;
```

Add `buildingsVersion` to the returned object (the hook's final `return { ... }`).

- [ ] **Step 4: Wire map components to re-fetch on version**

In `frontend/src/components/Buildings.tsx`: add `buildingsVersion?: number;` to `Props`, accept it in the destructure (`buildingsVersion = 0`), and add it to the fetch `useEffect` dependency array (currently `[apiBase]` → `[apiBase, buildingsVersion]`).

In `frontend/src/components/LocalMap2D.tsx`: add `buildingsVersion?: number;` to its `Props`, accept it, and append it to the "Load buildings once" effect deps (currently `[apiBase, fitToBuildings]` → `[apiBase, fitToBuildings, buildingsVersion]`).

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/useWorldClient.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/vitest.config.ts frontend/src/lib/useWorldClient.ts frontend/src/components/Buildings.tsx frontend/src/components/LocalMap2D.tsx frontend/src/lib/useWorldClient.test.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(dashboard): re-fetch buildings on buildings_updated signal"
```

---

## Task 7: `OperationalArea` control + mount on Map tab

**Files:**
- Create: `frontend/src/components/OperationalArea.tsx`
- Modify: `frontend/src/app/operator/page.tsx`
- Test: `frontend/src/components/OperationalArea.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/OperationalArea.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationalArea } from "./OperationalArea";

afterEach(() => vi.restoreAllMocks());

function setFields() {
  fireEvent.change(screen.getByLabelText(/latitude/i), { target: { value: "32.8" } });
  fireEvent.change(screen.getByLabelText(/longitude/i), { target: { value: "-117.2" } });
}

describe("OperationalArea", () => {
  it("posts lat/lng/radius and shows the building count on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ origin: { lat: 32.8, lng: -117.2 }, radius_m: 400, count: 7 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<OperationalArea apiBase="http://api" />);
    setFields();
    fireEvent.click(screen.getByRole("button", { name: /set area/i }));

    await waitFor(() => expect(screen.getByText(/7 buildings/i)).toBeTruthy());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/map/area");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ lat: 32.8, lng: -117.2, radius_m: 400 });
  });

  it("shows an offline error when the fetch returns 503", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: "requires internet" }),
    }));
    render(<OperationalArea apiBase="http://api" />);
    setFields();
    fireEvent.click(screen.getByRole("button", { name: /set area/i }));
    await waitFor(() => expect(screen.getByText(/no internet/i)).toBeTruthy());
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/components/OperationalArea.test.tsx`
Expected: FAIL — module `./OperationalArea` does not exist.

- [ ] **Step 3: Create the component**

```tsx
// frontend/src/components/OperationalArea.tsx
"use client";

import { useState } from "react";

type Status =
  | { kind: "idle" }
  | { kind: "fetching" }
  | { kind: "success"; count: number }
  | { kind: "error"; message: string };

interface Props {
  apiBase: string;
}

const OPERATOR_KEY = process.env.NEXT_PUBLIC_OPERATOR_KEY || "";

/**
 * Operator control to re-anchor the map's buildings layer on a new lat/long.
 * This is a PRE-MISSION staging action: it hits the internet at the moment of
 * fetch (OSM Overpass) and then the system runs fully offline on the result.
 */
export function OperationalArea({ apiBase }: Props) {
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [radius, setRadius] = useState("400");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const submit = async () => {
    const body = { lat: Number(lat), lng: Number(lng), radius_m: Number(radius) };
    setStatus({ kind: "fetching" });
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (OPERATOR_KEY) headers["X-Operator-Key"] = OPERATOR_KEY;
      const res = await fetch(`${apiBase}/map/area`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        cache: "no-store",
      });
      if (!res.ok) {
        const msg = res.status === 503
          ? "No internet — pre-mission only"
          : `Failed (HTTP ${res.status})`;
        setStatus({ kind: "error", message: msg });
        return;
      }
      const data = (await res.json()) as { count: number };
      setStatus({ kind: "success", count: data.count });
    } catch {
      setStatus({ kind: "error", message: "No internet — pre-mission only" });
    }
  };

  const fetching = status.kind === "fetching";

  return (
    <div className="border border-border bg-surface-elevated p-3 font-mono text-[11px] text-text">
      <div className="mb-2 uppercase tracking-[0.2em] text-text-dim">Operational Area</div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-text-dim">Latitude</span>
          <input
            aria-label="latitude"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            inputMode="decimal"
            className="w-28 border border-border bg-surface px-2 py-1 tabular-nums text-data outline-none focus:border-border-strong"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-text-dim">Longitude</span>
          <input
            aria-label="longitude"
            value={lng}
            onChange={(e) => setLng(e.target.value)}
            inputMode="decimal"
            className="w-28 border border-border bg-surface px-2 py-1 tabular-nums text-data outline-none focus:border-border-strong"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-text-dim">Radius m</span>
          <input
            aria-label="radius"
            value={radius}
            onChange={(e) => setRadius(e.target.value)}
            inputMode="numeric"
            className="w-20 border border-border bg-surface px-2 py-1 tabular-nums text-data outline-none focus:border-border-strong"
          />
        </label>
        <button
          onClick={submit}
          disabled={fetching}
          className="border border-border-strong bg-surface px-3 py-1 uppercase tracking-wider text-text hover:bg-surface/70 disabled:opacity-40"
        >
          {fetching ? "Fetching…" : "Set Area"}
        </button>
      </div>
      <div className="mt-2 h-4 text-[10px]">
        {status.kind === "success" && (
          <span className="text-ok">✓ {status.count} buildings cached for this area</span>
        )}
        {status.kind === "error" && <span className="text-fail">{status.message}</span>}
        {status.kind === "idle" && (
          <span className="text-text-dim">Requires internet — pre-mission staging only</span>
        )}
      </div>
    </div>
  );
}
```

Note: the Tailwind token classes (`bg-surface-elevated`, `text-data`, `text-ok`, `text-fail`, `border-border`, `border-border-strong`, `text-text-dim`) are the existing NATO-C2 tokens used across the dashboard. Match whatever names the current components use; if a token differs, use the existing one rather than inventing a new class.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/OperationalArea.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Mount it on the Map tab**

In `frontend/src/app/operator/page.tsx`:
- Import: `import { OperationalArea } from "@/components/OperationalArea";`
- Pass `buildingsVersion={wsLive.buildingsVersion}` into `<LocalMap2D ... />`, `<LocalMap3D ... />` (LocalMap3D renders `<Buildings>` — thread the prop through to it), and `<Buildings>` wherever rendered.
- Inside the `{tab === "map" && ( ... )}` block, add the control as an overlay panel that does not block the map. Place it alongside the existing `IntelSummaryCard` overlay (top-right is free; the IntelSummaryCard sits bottom-left):

```tsx
<div className="pointer-events-auto absolute right-3 top-3 z-10 max-w-sm">
  <OperationalArea apiBase={apiBase} />
</div>
```

- [ ] **Step 6: Verify build + typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. (Do NOT run `npm run build` if a dev server is active — it corrupts `.next/`.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/OperationalArea.tsx frontend/src/components/OperationalArea.test.tsx frontend/src/app/operator/page.tsx
git commit -m "feat(dashboard): operational-area lat/long control on Map tab"
```

---

## Task 8: Mobile decode-safety for `buildings_updated`

**Files:**
- Modify: `mobile/Tests/ContractsTests.swift` (append)

The mobile `ServerMessage` decoder (`mobile/Sources/Contracts.swift`) already routes unrecognized `type` values to `.unknown(type)`, and the mobile app does not render the OSM buildings layer. So `buildings_updated` is a safe no-op there. This task just locks that in with a test (no production code change).

- [ ] **Step 1: Add the test**

Append to `mobile/Tests/ContractsTests.swift` (inside the `ContractsTests` class):

```swift
func testBuildingsUpdatedDecodesAsUnknown() throws {
    let json = #"{"type":"buildings_updated","origin":{"lat":32.0,"lng":-117.0},"radius_m":400,"count":12,"t":3.5}"#
    let message = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
    guard case .unknown(let t) = message else { return XCTFail("should be unknown (mobile does not consume buildings)") }
    XCTAssertEqual(t, "buildings_updated")
}
```

- [ ] **Step 2: Run the mobile tests**

Run (from `mobile/`, regenerating the project per the documented working invocation):
```bash
cd mobile && xcodegen generate && \
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  SWIFT_ENABLE_EXPLICIT_MODULES=NO \
  "OTHER_SWIFT_FLAGS=-Xcc -I$(pwd)/Vendor/apriltag" \
  "HEADER_SEARCH_PATHS=$(pwd)/Vendor/apriltag" 2>&1 | tail -20
```
Expected: test suite passes including `testBuildingsUpdatedDecodesAsUnknown`.

- [ ] **Step 3: Commit**

```bash
git add mobile/Tests/ContractsTests.swift
git commit -m "test(mobile): buildings_updated decodes safely as unknown"
```

---

## Final verification

- [ ] Backend full suite: `cd backend && .venv/bin/python -m pytest -q` — all pass.
- [ ] Frontend tests: `cd frontend && npx vitest run` — all pass.
- [ ] Frontend typecheck: `cd frontend && npx tsc --noEmit` — clean.
- [ ] Manual smoke (optional, needs internet): start backend, open `/operator` → Map tab, enter a real lat/long + radius, click Set Area; confirm the map re-centers on new buildings and the count shows. Verify `.context/buildings.json.bak` was created.
- [ ] Dispatch a final code review across the whole change before finishing the branch.
