# Offline OSM Vector Basemap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a monochrome OSM vector basemap (MapLibre + PMTiles, with labels) as a backdrop under the SLAM layer on the operator MAP tab's 2D view, cached per operational area and fully offline at runtime.

**Architecture:** Extend the existing `/map/area` staging action to also range-extract a bounded PMTiles basemap from the pinned Protomaps cloud build (online once) into `.context/basemap.pmtiles`. Serve it (and locally-bundled glyph fonts) from the backend with HTTP range support. A new MapLibre-based `LocalMapGL` renders the basemap + re-homed SLAM entities; a BASEMAP/GRID toggle falls back to the existing `LocalMap2D` canvas.

**Tech Stack:** FastAPI/Starlette (Python), `pmtiles` Go CLI (extraction), MapLibre GL JS + `pmtiles` (npm), Next.js 14 + Tailwind, vitest, pytest.

**Reference spec:** `docs/superpowers/specs/2026-05-31-offline-osm-basemap-design.md`

---

## Ground truth (read before starting)

- `backend/app/map_area.py` — buildings pattern to mirror: `overpass_query`, `fetch_overpass`, `project_enu(lat,lng,origin_lat,origin_lng)`, `collect_buildings`, `fetch_and_project(lat,lng,radius_m)`, `write_buildings(payload, path, backup=True)`. Mirror URLs/timeout/atomic-write style.
- `backend/app/server.py` — `POST /map/area` (delegates to `map_area`, broadcasts `BuildingsUpdated`, `_require_operator` dep); `_BUILDINGS_PATH = .../.context/buildings.json`; `GET /map/buildings` at ~line 777. Add new routes near there.
- `frontend/src/components/LocalMap2D.tsx` — Props: `{ entities: Entity[]; apiBase?: string; initialSpanM?: number; statusLine?: string; buildingsVersion?: number; environment?: "outdoor"|"indoor" }`. Axis: **(x,y)=(east,north) metres, north up, launch=(0,0)**. `LocalMapGL` MUST accept the same props (drop-in).
- `frontend/src/lib/projection.ts` — `MapProjection` (world +y up). Add `localMetersToLatLng` here.
- `frontend/src/lib/contracts.ts` — `Entity` type (id, type, position Vec3 east/north, status, etc.) + `Vec3`.
- `frontend/src/app/operator/page.tsx` — MAP tab renders `<LocalMap2D entities apiBase buildingsVersion environment statusLine/>` (~line 317); `mapView` (2d/3d) + `environment` toggles persisted in `localStorage`. Add a `basemap` toggle the same way.
- `frontend/src/components/OperationalArea.tsx` — SET AREA panel; POSTs `/map/area`; shows status. Add basemap-staged status.
- Operator theme is strict monochrome; **red is reserved for threats** (basemap = no red).

**Conventions:** mono = `font-mono`; tokens `bg-bg/bg-surface/text-text/text-text-dim/border-border/border-border-strong/text-fail`; `cn` at `@/lib/cn`; no `any`; TS strict; commit per task; conventional commits; NO Claude attribution; stage by explicit path (untracked dirs exist).

**Verification environment:** Backend runs on `:8000` (CORS allows `:3000`). Frontend dev for this work: run on **`:3000`** (CORS-allowed) so backend calls + the live render work. MapLibre needs WebGL → use `browse --headed` for visual checks (headless has no WebGL). Deterministic tests: `cd frontend && pnpm test` (vitest), `cd backend && .venv/bin/python -m pytest -q`.

---

## File structure

**Backend (create):** `backend/app/basemap.py`, `scripts/fetch_basemap.py`, `backend/assets/glyphs/<FontStack>/<range>.pbf` (bundled), `backend/tests/test_basemap.py`.
**Backend (modify):** `backend/app/server.py` (extend `/map/area`; add `/map/basemap.pmtiles`, `/map/basemap/meta`, `/map/fonts/{fontstack}/{range}.pbf`), `backend/requirements.txt` (note pmtiles CLI dep), `backend/tests/test_upload_guards.py` sibling style for new route tests.
**Frontend (create):** `frontend/src/lib/basemapStyle.ts`, `frontend/src/components/LocalMapGL.tsx`, `frontend/src/lib/basemapMeta.ts`, `frontend/src/lib/projection.test.ts`, `frontend/src/lib/basemapStyle.test.ts`.
**Frontend (modify):** `frontend/src/lib/projection.ts` (+func), `frontend/src/app/operator/page.tsx` (toggle), `frontend/src/components/OperationalArea.tsx` (status), `frontend/package.json` (+deps).

---

## PHASE 1 — Backend: basemap extraction

### Task 1: `pmtiles` CLI availability + bbox math

**Files:** Create `backend/app/basemap.py`; Create `backend/tests/test_basemap.py`.

- [ ] **Step 1: Failing test for bbox math**

`backend/tests/test_basemap.py`:
```python
import math
from app.basemap import bbox_from_radius

def test_bbox_from_radius_centered():
    w, s, e, n = bbox_from_radius(32.8791, -117.2322, 400)
    # ~400 m → ~0.0036 deg lat half-span
    assert n > 32.8791 and s < 32.8791
    assert e > -117.2322 and w < -117.2322
    half_lat = (n - s) / 2
    assert math.isclose(half_lat, 400 / 111320, rel_tol=0.05)
    # lng span widened by 1/cos(lat)
    half_lng = (e - w) / 2
    assert half_lng > half_lat  # at this latitude cos<1
```

- [ ] **Step 2: Run → fails** (`cd backend && .venv/bin/python -m pytest tests/test_basemap.py -q`) — ImportError.

- [ ] **Step 3: Implement bbox + extraction scaffold** in `backend/app/basemap.py`:
```python
"""OSM vector basemap (PMTiles) extraction for the offline map layer.

Range-extracts a bounded region from the pinned Protomaps cloud build into a
local .pmtiles using the `pmtiles` CLI (Go binary). Online ONLY at staging.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path

PROTOMAPS_BUILD_URL = os.environ.get(
    "PROTOMAPS_BUILD_URL", "https://build.protomaps.com/20240101.pmtiles"
)
DEFAULT_MAXZOOM = int(os.environ.get("BASEMAP_MAXZOOM", "15"))
_EARTH_M_PER_DEG_LAT = 111_320.0


@dataclass
class BasemapMeta:
    staged: bool
    bytes: int
    minzoom: int
    maxzoom: int
    bbox: list[float]          # [w, s, e, n]
    origin: dict               # {"lat":..., "lng":...}
    build_url: str
    created_at: float


def bbox_from_radius(lat: float, lng: float, radius_m: int) -> tuple[float, float, float, float]:
    """(w, s, e, n) lon/lat bounding box around (lat,lng) covering radius_m."""
    dlat = radius_m / _EARTH_M_PER_DEG_LAT
    dlng = radius_m / (_EARTH_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return (lng - dlng, lat - dlat, lng + dlng, lat + dlat)


def pmtiles_available() -> bool:
    return shutil.which("pmtiles") is not None


def extract_basemap(
    lat: float,
    lng: float,
    radius_m: int,
    *,
    out_path: Path,
    build_url: str = PROTOMAPS_BUILD_URL,
    maxzoom: int = DEFAULT_MAXZOOM,
    runner=subprocess.run,
) -> BasemapMeta:
    """Range-extract the AOI bbox from the remote build into out_path. Raises on
    failure (caller maps to HTTP 503). `runner` is injectable for tests."""
    if not pmtiles_available():
        raise RuntimeError("pmtiles CLI not installed (brew install pmtiles)")
    w, s, e, n = bbox_from_radius(lat, lng, radius_m)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".pmtiles.tmp")
    cmd = [
        "pmtiles", "extract", build_url, str(tmp),
        f"--bbox={w},{s},{e},{n}", f"--maxzoom={maxzoom}",
    ]
    proc = runner(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"pmtiles extract failed: {proc.stderr.strip()[:400]}")
    os.replace(tmp, out_path)
    meta = BasemapMeta(
        staged=True,
        bytes=out_path.stat().st_size,
        minzoom=0,
        maxzoom=maxzoom,
        bbox=[w, s, e, n],
        origin={"lat": lat, "lng": lng},
        build_url=build_url,
        created_at=time.time(),
    )
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(asdict(meta)))
    return meta


def read_meta(meta_path: Path) -> BasemapMeta:
    if not meta_path.exists():
        return BasemapMeta(False, 0, 0, 0, [], {}, "", 0.0)
    d = json.loads(meta_path.read_text())
    return BasemapMeta(**d)
```

- [ ] **Step 4: Run → bbox test passes.**

- [ ] **Step 5: Add extraction test with an injected fake runner** (no network):
```python
from pathlib import Path
from app.basemap import extract_basemap, read_meta

def test_extract_basemap_writes_meta(tmp_path, monkeypatch):
    import app.basemap as bm
    monkeypatch.setattr(bm, "pmtiles_available", lambda: True)
    out = tmp_path / "basemap.pmtiles"
    class P: returncode = 0; stderr = ""; stdout = ""
    def fake_run(cmd, **kw):
        # simulate the CLI producing the tmp file
        Path(cmd[3]).write_bytes(b"PMTilesfake")
        return P()
    meta = extract_basemap(32.87, -117.23, 400, out_path=out, runner=fake_run)
    assert out.exists() and meta.staged and meta.bytes > 0
    assert read_meta(out.with_suffix(".meta.json")).origin["lat"] == 32.87
```

- [ ] **Step 6: Run → passes.** Then ensure the `pmtiles` CLI is actually installed for real staging: run `which pmtiles || brew install pmtiles` (install if missing; this is the staging tooling).

- [ ] **Step 7: Commit**
```bash
git add backend/app/basemap.py backend/tests/test_basemap.py
git commit -m "feat(basemap): AOI bbox + pmtiles extraction module"
```

---

## PHASE 2 — Backend: serving + staging wiring

### Task 2: Serve pmtiles (range), meta, and glyphs

**Files:** Modify `backend/app/server.py`.

- [ ] **Step 1: Add path constants** near `_BUILDINGS_PATH`:
```python
_BASEMAP_PATH = _BUILDINGS_PATH.parent / "basemap.pmtiles"
_BASEMAP_META_PATH = _BUILDINGS_PATH.parent / "basemap.meta.json"
_GLYPHS_DIR = Path(__file__).resolve().parent.parent / "assets" / "glyphs"
```

- [ ] **Step 2: Range-capable pmtiles route + meta route + glyph route.** Use Starlette `FileResponse` (it honors the `Range` request header and returns 206). Add:
```python
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response

@app.get("/map/basemap.pmtiles")
async def get_basemap_pmtiles(request: Request) -> Response:
    if not _BASEMAP_PATH.exists():
        return JSONResponse({"detail": "no basemap staged"}, status_code=404)
    # FileResponse handles Range -> 206 automatically.
    return FileResponse(_BASEMAP_PATH, media_type="application/octet-stream")

@app.get("/map/basemap/meta")
async def get_basemap_meta() -> dict:
    from app.basemap import read_meta
    from dataclasses import asdict
    return asdict(read_meta(_BASEMAP_META_PATH))

@app.get("/map/fonts/{fontstack}/{rng}.pbf")
async def get_glyphs(fontstack: str, rng: str) -> Response:
    # Prevent traversal; only allow "<int>-<int>" ranges + known stacks.
    safe = (_GLYPHS_DIR / fontstack / f"{rng}.pbf").resolve()
    if _GLYPHS_DIR.resolve() not in safe.parents or not safe.exists():
        return JSONResponse({"detail": "glyph not found"}, status_code=404)
    return FileResponse(safe, media_type="application/x-protobuf")
```
(If `_BASEMAP_PATH`/meta differ from `basemap.py`'s `out_path.with_suffix(".meta.json")`, reconcile: extraction writes `<out>.meta.json`; ensure `_BASEMAP_META_PATH` matches `_BASEMAP_PATH.with_suffix(".meta.json")` → `basemap.meta.json`. They match.)

- [ ] **Step 3: Test the routes** in `backend/tests/test_basemap_routes.py`:
```python
from fastapi.testclient import TestClient
from app.server import app

def test_meta_unstaged():
    c = TestClient(app)
    r = c.get("/map/basemap/meta")
    assert r.status_code == 200 and r.json()["staged"] in (False, True)

def test_pmtiles_404_when_absent(tmp_path, monkeypatch):
    import app.server as srv
    monkeypatch.setattr(srv, "_BASEMAP_PATH", tmp_path / "nope.pmtiles")
    c = TestClient(app)
    assert c.get("/map/basemap.pmtiles").status_code == 404

def test_glyph_traversal_blocked():
    c = TestClient(app)
    assert c.get("/map/fonts/..%2f..%2fetc/0-255.pbf").status_code in (404, 400)
```

- [ ] **Step 4: Run** `cd backend && .venv/bin/python -m pytest tests/test_basemap_routes.py -q` → pass.

- [ ] **Step 5: Commit**
```bash
git add backend/app/server.py backend/tests/test_basemap_routes.py
git commit -m "feat(basemap): serve pmtiles (range), meta, and local glyphs"
```

### Task 3: Extend `/map/area` to also stage the basemap

**Files:** Modify `backend/app/server.py` (`post_map_area`).

- [ ] **Step 1: After `write_buildings(...)`, also extract the basemap (non-fatal).** Replace the return with:
```python
    basemap_meta = None
    basemap_error = None
    try:
        from app.basemap import extract_basemap
        from dataclasses import asdict
        meta = await asyncio.to_thread(
            extract_basemap, req.lat, req.lng, req.radius_m, out_path=_BASEMAP_PATH
        )
        basemap_meta = asdict(meta)
    except Exception as exc:  # noqa: BLE001 — basemap is best-effort; buildings already saved
        basemap_error = str(exc)[:200]
    return {
        "origin": payload["origin"],
        "radius_m": payload["radius_m"],
        "count": payload["count"],
        "basemap": basemap_meta,
        "basemap_error": basemap_error,
    }
```

- [ ] **Step 2: Test** — extend `test_basemap_routes.py`:
```python
def test_map_area_returns_basemap_field(monkeypatch):
    import app.server as srv
    monkeypatch.setattr(srv.map_area, "fetch_and_project", lambda *a: {"origin": {"lat": 1, "lng": 2}, "radius_m": 400, "count": 0, "buildings": []})
    monkeypatch.setattr(srv.map_area, "write_buildings", lambda *a, **k: None)
    async def fake_bcast(*a, **k): return None
    monkeypatch.setattr(srv.hub, "broadcast", fake_bcast)
    # basemap extract will fail (no pmtiles/net) → basemap None, request still 200
    c = TestClient(app)
    r = c.post("/map/area", json={"lat": 1, "lng": 2, "radius_m": 400})
    assert r.status_code == 200
    body = r.json()
    assert "basemap" in body  # present (None on failure)
```
(If `_require_operator` blocks the test, set the bypass env the other tests use, or pass the operator key header consistent with `test_upload_guards.py`.)

- [ ] **Step 3: Run → pass.**

- [ ] **Step 4: Commit**
```bash
git add backend/app/server.py backend/tests/test_basemap_routes.py
git commit -m "feat(basemap): stage basemap alongside buildings in /map/area"
```

### Task 4: Standalone staging script

**Files:** Create `scripts/fetch_basemap.py`.

- [ ] **Step 1: Implement** (mirrors `scripts/fetch_buildings.py`):
```python
#!/usr/bin/env python3
"""One-time OSM basemap (PMTiles) cache for the offline map. Needs internet
(Protomaps build) at run time; runs fully offline afterward."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.basemap import extract_basemap, DEFAULT_MAXZOOM

def main() -> int:
    ap = argparse.ArgumentParser(description="One-time OSM basemap PMTiles cache.")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lng", type=float, required=True)
    ap.add_argument("--radius", type=int, default=400)
    ap.add_argument("--maxzoom", type=int, default=DEFAULT_MAXZOOM)
    ap.add_argument("--out", type=Path, default=Path(".context") / "basemap.pmtiles")
    a = ap.parse_args()
    print(f"[basemap] extracting {a.radius}m @ {a.lat},{a.lng} z<= {a.maxzoom} ...")
    meta = extract_basemap(a.lat, a.lng, a.radius, out_path=a.out, maxzoom=a.maxzoom)
    print(f"[basemap] wrote {a.out} ({meta.bytes} bytes), bbox={meta.bbox}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify** `python scripts/fetch_basemap.py --help` runs (no extraction). Commit:
```bash
git add scripts/fetch_basemap.py
git commit -m "feat(basemap): standalone staging script"
```

---

## PHASE 3 — Backend: bundle offline glyphs

### Task 5: Download + commit a prebuilt glyph PBF set

**Files:** Create `backend/assets/glyphs/Noto Sans Regular/*.pbf` + `backend/assets/glyphs/README.md`.

- [ ] **Step 1: Fetch a prebuilt PBF glyph set (online, once)** for one font stack from the openmaptiles fonts distribution (e.g. "Noto Sans Regular"), into `backend/assets/glyphs/Noto Sans Regular/`. The set is the standard 0-255 … 65280-65535 `.pbf` ranges. Use the maintained repo `github.com/openmaptiles/fonts` (build output) or its released `noto-sans` glyph dir. Command pattern:
```bash
mkdir -p "backend/assets/glyphs/Noto Sans Regular"
# Download each needed range (Latin coverage 0-255, 256-511, ... at minimum 0-255 & 256-511 & 8192-8447 for punctuation).
# Pull the full standard set for the stack from the fonts release tarball, then keep the "Noto Sans Regular" dir.
```
Minimum viable: include at least ranges `0-255`, `256-511`, `8192-8447` (covers Latin + common punctuation); committing the full set is fine.

- [ ] **Step 2: Write `backend/assets/glyphs/README.md`** documenting the source font, license (Noto = OFL), and how to regenerate (`font-maker`/openmaptiles fonts).

- [ ] **Step 3: Verify the glyph route serves one** — start backend, `curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/map/fonts/Noto%20Sans%20Regular/0-255.pbf"` → 200.

- [ ] **Step 4: Commit**
```bash
git add "backend/assets/glyphs" 
git commit -m "feat(basemap): bundle Noto Sans glyph PBFs for offline labels"
```

---

## PHASE 4 — Frontend: projection + style (pure, tested)

### Task 6: `localMetersToLatLng`

**Files:** Modify `frontend/src/lib/projection.ts`; Create `frontend/src/lib/projection.test.ts`.

- [ ] **Step 1: Failing test** `projection.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { localMetersToLatLng } from "./projection";

describe("localMetersToLatLng", () => {
  const origin = { lat: 32.8791, lng: -117.2322 };
  it("returns origin for (0,0)", () => {
    const p = localMetersToLatLng(origin, 0, 0);
    expect(p.lat).toBeCloseTo(origin.lat, 9);
    expect(p.lng).toBeCloseTo(origin.lng, 9);
  });
  it("north offset increases lat by ~m/111320", () => {
    const p = localMetersToLatLng(origin, 0, 1113.2);
    expect(p.lat - origin.lat).toBeCloseTo(0.01, 4);
  });
  it("east offset widens by 1/cos(lat)", () => {
    const p = localMetersToLatLng(origin, 1000, 0);
    expect(p.lng).toBeGreaterThan(origin.lng);
  });
});
```

- [ ] **Step 2: Run → fail** (`cd frontend && pnpm test projection`).

- [ ] **Step 3: Implement** (append to `projection.ts`):
```ts
const M_PER_DEG_LAT = 111_320;

/** Convert local-frame metres (east, north; launch=origin) to lat/lng.
 * Equirectangular approximation, fine for a bounded operational area. */
export function localMetersToLatLng(
  origin: { lat: number; lng: number },
  east_m: number,
  north_m: number,
): { lat: number; lng: number } {
  const lat = origin.lat + north_m / M_PER_DEG_LAT;
  const lng =
    origin.lng + east_m / (M_PER_DEG_LAT * Math.max(Math.cos((origin.lat * Math.PI) / 180), 1e-6));
  return { lat, lng };
}
```

- [ ] **Step 4: Run → pass. Commit**
```bash
git add frontend/src/lib/projection.ts frontend/src/lib/projection.test.ts
git commit -m "feat(basemap): localMetersToLatLng projection"
```

### Task 7: `basemapStyle.ts` (monochrome MapLibre style, offline-guarded)

**Files:** Create `frontend/src/lib/basemapStyle.ts`; Create `frontend/src/lib/basemapStyle.test.ts`.

- [ ] **Step 1: Failing test** `basemapStyle.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { buildBasemapStyle } from "./basemapStyle";

describe("buildBasemapStyle", () => {
  const style = buildBasemapStyle("http://localhost:8000");
  it("has no remote URLs (offline guard)", () => {
    const json = JSON.stringify(style);
    const urls = json.match(/https?:\/\/[^"']+/g) ?? [];
    for (const u of urls) expect(u.startsWith("http://localhost:8000")).toBe(true);
  });
  it("uses local glyphs + pmtiles source, no sprite", () => {
    expect(style.glyphs).toContain("http://localhost:8000/map/fonts/");
    expect(JSON.stringify(style.sources)).toContain("pmtiles://");
    expect((style as Record<string, unknown>).sprite).toBeUndefined();
  });
  it("is monochrome (no saturated hex)", () => {
    const json = JSON.stringify(style);
    // allow greys (#rrggbb where r==g==b) + paper; assert no obvious hue tokens
    expect(json).not.toMatch(/#(?:00[0-9a-f]{2}ff|ff0000|1d4ed8|00ff00)/i);
  });
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `basemapStyle.ts` — a Protomaps-schema monochrome style. Source layers from the Protomaps build: `earth, water, landuse, roads, buildings, boundaries, places, transit`. Use neutral greys + paper; labels via local glyphs. (Full style below; keep colors greyscale only.)
```ts
import type { StyleSpecification } from "maplibre-gl";

const PAPER = "#f1f1f0";
const INK = "#202020";
const INK_2 = "#5a5a5a";
const LINE = "#cfcfcf";
const WATER = "#e3e3e1";
const BUILDING = "#dcdcda";

/** Monochrome Protomaps-schema basemap. All URLs are local (offline). */
export function buildBasemapStyle(apiBase: string): StyleSpecification {
  return {
    version: 8,
    glyphs: `${apiBase}/map/fonts/{fontstack}/{range}.pbf`,
    sources: {
      basemap: {
        type: "vector",
        url: `pmtiles://${apiBase}/map/basemap.pmtiles`,
        attribution: "© OpenStreetMap",
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": PAPER } },
      { id: "earth", type: "fill", source: "basemap", "source-layer": "earth", paint: { "fill-color": PAPER } },
      { id: "landuse", type: "fill", source: "basemap", "source-layer": "landuse", paint: { "fill-color": "#ececeb", "fill-opacity": 0.6 } },
      { id: "water", type: "fill", source: "basemap", "source-layer": "water", paint: { "fill-color": WATER } },
      { id: "buildings", type: "fill", source: "basemap", "source-layer": "buildings", paint: { "fill-color": BUILDING, "fill-outline-color": LINE } },
      { id: "roads-casing", type: "line", source: "basemap", "source-layer": "roads", paint: { "line-color": LINE, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 6] } },
      { id: "roads", type: "line", source: "basemap", "source-layer": "roads", paint: { "line-color": INK_2, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.4, 16, 3] } },
      { id: "boundaries", type: "line", source: "basemap", "source-layer": "boundaries", paint: { "line-color": INK_2, "line-dasharray": [2, 2], "line-width": 0.7 } },
      {
        id: "places", type: "symbol", source: "basemap", "source-layer": "places",
        layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 11, "text-letter-spacing": 0.08, "text-transform": "uppercase" },
        paint: { "text-color": INK, "text-halo-color": PAPER, "text-halo-width": 1.2 },
      },
      {
        id: "road-labels", type: "symbol", source: "basemap", "source-layer": "roads",
        layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 10 },
        paint: { "text-color": INK_2, "text-halo-color": PAPER, "text-halo-width": 1 },
      },
    ],
  };
}
```
(Note: exact Protomaps `source-layer` names — `earth/water/landuse/roads/buildings/boundaries/places` — match the Protomaps "basemap" schema. If a layer name differs for the pinned build, adjust during the visual check; tests only assert URL-locality/monochrome.)

- [ ] **Step 4: Run → pass. Commit**
```bash
git add frontend/src/lib/basemapStyle.ts frontend/src/lib/basemapStyle.test.ts
git commit -m "feat(basemap): monochrome MapLibre style (offline, local URLs)"
```

---

## PHASE 5 — Frontend: MapLibre map + SLAM overlay

### Task 8: Install deps + `basemapMeta` hook

**Files:** Modify `frontend/package.json`; Create `frontend/src/lib/basemapMeta.ts`.

- [ ] **Step 1: Add deps** — `cd frontend && pnpm add maplibre-gl pmtiles`. (Confirms versions in package.json.)

- [ ] **Step 2: `basemapMeta.ts`** — typed fetch of `/map/basemap/meta`:
```ts
export interface BasemapMeta {
  staged: boolean; bytes: number; minzoom: number; maxzoom: number;
  bbox: number[]; origin: { lat?: number; lng?: number }; build_url: string; created_at: number;
}
export async function fetchBasemapMeta(apiBase: string): Promise<BasemapMeta> {
  try {
    const r = await fetch(`${apiBase}/map/basemap/meta`, { cache: "no-store" });
    if (!r.ok) return emptyMeta();
    return (await r.json()) as BasemapMeta;
  } catch {
    return emptyMeta();
  }
}
function emptyMeta(): BasemapMeta {
  return { staged: false, bytes: 0, minzoom: 0, maxzoom: 0, bbox: [], origin: {}, build_url: "", created_at: 0 };
}
```

- [ ] **Step 3: tsc** (`pnpm exec tsc --noEmit`) clean. Commit:
```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/lib/basemapMeta.ts
git commit -m "feat(basemap): maplibre-gl + pmtiles deps, meta hook"
```

### Task 9: `LocalMapGL.tsx` — basemap + SLAM overlay

**Files:** Create `frontend/src/components/LocalMapGL.tsx`.

This is the largest task. The component is a **drop-in for `LocalMap2D`** (same Props). Implement in clear steps; verify with headed browse at the end.

- [ ] **Step 1: Read** `LocalMap2D.tsx` (entity rendering: glyphs, labels, threat=red, selection), `contracts.ts` (`Entity`, `Vec3`), and `basemapStyle.ts`.

- [ ] **Step 2: Scaffold the map** — props `{ entities, apiBase = "", buildingsVersion, environment, statusLine }`. On mount:
  - `import maplibregl from "maplibre-gl"; import { Protocol } from "pmtiles"; import "maplibre-gl/dist/maplibre-gl.css";`
  - Register once: `const proto = new Protocol(); maplibregl.addProtocol("pmtiles", proto.tile);`
  - Fetch meta (`fetchBasemapMeta(apiBase)`) → center = `[origin.lng, origin.lat]` (fallback `[0,0]`).
  - Create `new maplibregl.Map({ container, style: buildBasemapStyle(apiBase), center, zoom: 15, dragRotate: false, pitchWithRotate: false, touchZoomRotate: { around: "center" }, attributionControl: true, transformRequest })`.
  - `transformRequest(url)`: return `{ url }` only if `url.startsWith(apiBase) || url.startsWith("pmtiles://" + apiBase) || url.startsWith(location.origin)`, else return `{ url: "" }` (deny) — the **offline guard**.
  - Disable rotation: `map.touchZoomRotate.disableRotation()`, `map.dragRotate.disable()`, `map.keyboard.disableRotation?.()`.
  - Add `maplibregl.ScaleControl({ unit: "metric" })`.

- [ ] **Step 3: SLAM overlay as a GeoJSON source + layers.** After `map.on("load")`:
  - Add source `"slam"` (empty FeatureCollection).
  - Layers (monochrome; threat=red): `slam-path` (line, ink), `slam-entities` (circle: ink fill, `--fail` red when `feature.properties.threat`), `slam-labels` (symbol: entity short label, mono, local font). Launch point as a distinct marker (use a `maplibregl.Marker` with a small reticle DOM element, or a feature with a ring layer).
  - A helper `entitiesToGeoJSON(entities, origin)` maps each `Entity` → a Point feature at `localMetersToLatLng(origin, e.position.x, e.position.y)` with properties `{ id, kind, label, threat: isThreatType(e) }`. Reuse the same threat/type predicates `LocalMap2D` uses (import or replicate minimally).

- [ ] **Step 4: Reactive updates** — a `useEffect` on `[entities]` calls `map.getSource("slam")?.setData(entitiesToGeoJSON(entities, origin))`. No full re-render of the map.

- [ ] **Step 5: Selection** — `map.on("click", "slam-entities", e => onSelect?.(e.features[0].properties.id))` if the Props include selection; the operator usage doesn't pass `onSelect`, so this is optional — gate on an optional `onSelect?` prop added to the Props type (keep drop-in compatible by making it optional).

- [ ] **Step 6: Statusline + attribution + cleanup** — render `statusLine` in a mono overlay chip (match `LocalMap2D`’s placement/classes). On unmount: `map.remove()` and `maplibregl.removeProtocol("pmtiles")` (guard against double-remove).

- [ ] **Step 7: tsc clean** (`pnpm exec tsc --noEmit`). Commit:
```bash
git add frontend/src/components/LocalMapGL.tsx
git commit -m "feat(basemap): LocalMapGL — MapLibre basemap + SLAM overlay"
```

---

## PHASE 6 — Frontend: wire the toggle + status

### Task 10: BASEMAP/GRID toggle on the MAP tab

**Files:** Modify `frontend/src/app/operator/page.tsx`.

- [ ] **Step 1: Add persisted `basemap` state** (mirror `mapView`):
```tsx
const [basemap, setBasemap] = useState<"grid" | "map">("grid");
useEffect(() => { const s = window.localStorage.getItem("sg.basemap"); if (s === "grid" || s === "map") setBasemap(s); }, []);
useEffect(() => { window.localStorage.setItem("sg.basemap", basemap); }, [basemap]);
const [bmMeta, setBmMeta] = useState<{ staged: boolean }>({ staged: false });
useEffect(() => { void fetchBasemapMeta(apiBase).then((m) => setBmMeta({ staged: m.staged })); }, [apiBase, wsLive.buildingsVersion]);
```
Imports: `import { LocalMapGL } from "@/components/LocalMapGL"; import { fetchBasemapMeta } from "@/lib/basemapMeta";`

- [ ] **Step 2: Add the segmented toggle** next to the 2D/3D + outdoor/indoor toggles (inverted active style, matching them). When `!bmMeta.staged`, render the `map` option disabled with `title="Set Area while online to cache a basemap"`.

- [ ] **Step 3: Conditional render** in the MAP/2D branch:
```tsx
{mapView === "2d" ? (
  basemap === "map" && bmMeta.staged ? (
    <LocalMapGL entities={effectiveOpEntities} apiBase={apiBase} buildingsVersion={wsLive.buildingsVersion} environment={environment} statusLine={/* same expression as LocalMap2D */} />
  ) : (
    <LocalMap2D entities={effectiveOpEntities} apiBase={apiBase} buildingsVersion={wsLive.buildingsVersion} environment={environment} statusLine={/* unchanged */} />
  )
) : (
  <LocalMap3D ... />  /* unchanged */
)}
```
(Keep the exact existing `statusLine` expression; factor it into a `const mapStatus = ...` to avoid duplication.)

- [ ] **Step 4: tsc clean.** Commit:
```bash
git add frontend/src/app/operator/page.tsx
git commit -m "feat(operator): BASEMAP/GRID toggle with cached-basemap gating"
```

### Task 11: OperationalArea basemap status

**Files:** Modify `frontend/src/components/OperationalArea.tsx`.

- [ ] **Step 1:** Extend the `success` status to read the `/map/area` response `basemap` field. Change the POST result handling to capture `data.basemap`/`data.basemap_error` and show, on success: `✓ {count} buildings · basemap {staged?`z0–${maxzoom}`:"unavailable"}`. Keep monochrome (`text-text-dim`). Type the response inline (no `any`).

- [ ] **Step 2: tsc clean.** Commit:
```bash
git add frontend/src/components/OperationalArea.tsx
git commit -m "feat(operator): show basemap staging status after Set Area"
```

---

## PHASE 7 — Verification

### Task 12: Deterministic test sweep

- [ ] **Step 1:** `cd frontend && pnpm test` → all pass (incl. new projection + style tests). `pnpm exec tsc --noEmit` clean.
- [ ] **Step 2:** `cd backend && .venv/bin/python -m pytest -q` → all pass (incl. basemap + routes).
- [ ] **Step 3:** Commit any test fixups.

### Task 13: Live end-to-end + offline check (headed, WebGL)

- [ ] **Step 1: Ensure tooling + servers.** `which pmtiles` (install via brew if missing). Backend running on `:8000`. Run THIS branch's frontend on `:3000` (CORS-allowed): `cd frontend && pnpm dev -p 3000` (stop any other :3000 first; coordinate so we don't clobber the user's instance — use the running one if it's this branch, else start ours).
- [ ] **Step 2: Stage a basemap.** With internet: `python scripts/fetch_basemap.py --lat 32.8791 --lng -117.2322 --radius 800` (San Diego AOI matching the cached buildings) → confirm `.context/basemap.pmtiles` exists and `/map/basemap/meta` returns `staged:true`.
- [ ] **Step 3: Headed visual check** (WebGL works headed):
```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
$B --headed goto http://localhost:3000/operator
# switch to MAP tab, set BASEMAP toggle, screenshot
$B screenshot /tmp/basemap.png
```
Read `/tmp/basemap.png`: confirm a monochrome OSM map (roads/buildings/water + labels) renders under the SLAM launch/entity markers, north-up, aligned with where buildings were. `$B console --errors` → no errors (esp. no blocked-URL/CORS).
- [ ] **Step 4: Offline guard check** — in the headed page, verify no network calls leave localhost: `$B network | grep -v "localhost:8000\|localhost:3000"` should be empty for map tiles/glyphs. Toggle BASEMAP→GRID and back; confirm fallback + return work.
- [ ] **Step 5:** If the Protomaps `source-layer` names differ (empty map but tiles load), adjust `basemapStyle.ts` layer `source-layer` values to the build's actual schema, re-verify.
- [ ] **Step 6: Final commit** of any style/layer adjustments:
```bash
git add -A frontend/src/lib/basemapStyle.ts
git commit -m "fix(basemap): align style source-layers with pinned build"
```

---

## Self-review (coverage vs spec)

- §1 acquisition → Tasks 1,3,4. §2 serving (pmtiles range/meta/glyphs) → Tasks 2,5. §3 rendering (style+map) → Tasks 7,9. §4 overlay/projection → Tasks 6,9. §5 toggle/fallback → Task 10. §6 offline guard → Task 7 (style test) + Task 9 (transformRequest) + Task 13 step 4. §7 testing → Tasks 12,13. OperationalArea status (spec §3) → Task 11.
- Deviation from spec: extraction uses the **`pmtiles` Go CLI via subprocess** (robust remote range-extract) rather than the Python lib; reflected throughout. Glyphs sourced from a **prebuilt PBF set** (openmaptiles/Noto) rather than generated locally — same offline outcome, less toolchain.
- WebGL/headless limitation handled via **headed browse** (Task 13).
