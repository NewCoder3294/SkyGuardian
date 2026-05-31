# Offline OSM Vector Basemap (MapLibre + PMTiles) — Design

**Date:** 2026-05-31
**Surface:** Operator console `/operator`, MAP tab, 2D view (`LocalMap2D` → new `LocalMapGL`).
**Branch:** `feat/offline-basemap` (off `feat/operator-bw-military`).

## Goal

Render a real OSM street/building/water basemap **with labels**, styled **strict monochrome**, as a backdrop **under** the SLAM layer on the 2D MAP tab — and keep it **100% offline at mission time**. A basemap is cached per operational area through the existing SET AREA action (online once, at staging).

Out of scope: the 3D map (`LocalMap3D`), the landing page, mobile. 2D only for this iteration.

## Constraints (from project CLAUDE.md — do not violate)

- **Offline-first.** Zero network at runtime. Staging (SET AREA / script) is the only online step.
- **No GPS.** Positioning stays relative to the launch anchor + SLAM. The basemap is a **situational backdrop placed via the operator-entered AOI anchor**, never a positioning source.
- **Strict monochrome** operator theme; **red reserved strictly for threats** (basemap carries no red; only the SLAM overlay does).
- **License:** OSM/Protomaps data is ODbL — show "© OpenStreetMap" attribution on the map.

## Direction (locked with user)

- Approach **B**: PMTiles + MapLibre GL (full vector basemap, labels, zoom LODs).
- **Backdrop under SLAM** with a BASEMAP/GRID toggle (grid = current `LocalMap2D`, unchanged fallback).
- **2D only** first.
- **Vector, monochrome.**
- **Labels: yes**, via **locally bundled glyph PBFs** (no remote font URLs).
- **Staging wired into SET AREA** (server-side `pmtiles` extract) + a standalone `scripts/fetch_basemap.py`.

## Existing pattern this builds on

`scripts/fetch_buildings.py` → Overpass (online once) → polygons **projected into the local meter frame** → `.context/buildings.json` (`{origin:{lat,lng}, radius_m, buildings:[{polygon:[[x,y],…]}]}`) → served at `/map/buildings` → drawn on the `LocalMap2D` canvas. `src/lib/projection.ts` holds frame math. The basemap reuses the **same origin anchor** so basemap + buildings + entities align.

---

## Architecture

### 1. Acquisition (online, staging only)

**`backend/app/basemap.py`** (new, isolated, unit-testable):
- `bbox_from_radius(lat, lng, radius_m) -> (w, s, e, n)` — equirectangular bbox at the AOI center.
- `extract_basemap(lat, lng, radius_m, *, out_path, build_url, maxzoom=15) -> BasemapMeta` — range-extract the bbox region from the pinned Protomaps cloud build into `out_path` (`.context/basemap.pmtiles`) using the `pmtiles` Python library's extract/range reader. Returns `BasemapMeta {bytes, minzoom, maxzoom, bbox:[w,s,e,n], origin:{lat,lng}, build_url, created_at}`.
- Writes a sidecar `.context/basemap.meta.json` with `BasemapMeta` (so serving/UI can report status without opening the pmtiles).
- Pinned build constant `PROTOMAPS_BUILD_URL` (a dated build, e.g. `https://build.protomaps.com/<YYYYMMDD>.pmtiles`); overridable via env `PROTOMAPS_BUILD_URL`.
- Network failure raises a typed error → caller maps to HTTP 503 with "No internet: pre-mission only" (mirrors buildings).

**`server.py` — extend `POST /map/area`:**
- After the existing buildings fetch, also call `extract_basemap(...)` for the same `{lat,lng,radius_m}`.
- Response shape extended: `{count, basemap: BasemapMeta | null}` — `null` (with a non-fatal warning field) if the basemap extract failed but buildings succeeded, so one failing half doesn't fail the other.
- Bound: reject `radius_m` above an existing/added cap; cap `maxzoom` so file size stays sane.

**`scripts/fetch_basemap.py`** (new) — CLI wrapper over `extract_basemap` (`--lat --lng --radius --out --maxzoom`), mirroring `fetch_buildings.py`.

### 2. Serving (offline, runtime)

**`server.py` — new routes:**
- `GET /map/basemap.pmtiles` — **range-capable** static serve of `.context/basemap.pmtiles` (Starlette `StaticFiles` or a 206-aware handler; MapLibre's pmtiles protocol issues HTTP Range requests). 404 when not staged.
- `GET /map/basemap/meta` — returns `.context/basemap.meta.json` or `{staged:false}`.
- `GET /map/fonts/{fontstack}/{range}.pbf` — serve glyph PBFs from `backend/assets/glyphs/{fontstack}/{range}.pbf`. 404 on miss.

**`backend/assets/glyphs/`** — one font stack's PBF ranges (0-255 … 65280-65535), generated once with a fontnik-based tool (e.g. `font-maker`) from an open font (e.g. a sans for labels), committed to the repo. Generation steps documented in the plan; output is static, no runtime toolchain.

### 3. Rendering (frontend)

**Deps:** `maplibre-gl`, `pmtiles`.

**`src/lib/basemapStyle.ts`** (new): `buildBasemapStyle(apiBase: string): StyleSpecification` — a MapLibre style:
- `glyphs: ${apiBase}/map/fonts/{fontstack}/{range}.pbf`.
- One vector source from the pmtiles archive (Protomaps schema layers: `water`, `landuse`, `roads`, `buildings`, `boundaries`, `places`, …).
- Monochrome layers: paper `background`; light-grey water/landuse; hairline-ink building fills; ink road lines weighted by `pmap:kind`/class; dashed boundaries; mono-ink symbol layers for road/place labels (local glyphs).
- **No `sprite`. No remote URLs.** Pure function → unit-testable (assert every URL begins with `apiBase` or is relative).

**`src/components/LocalMapGL.tsx`** (new): MapLibre map for the 2D basemap view.
- Registers the `pmtiles` protocol; source URL `pmtiles://${apiBase}/map/basemap.pmtiles`.
- `transformRequest` guard: allow only same-origin/`apiBase` URLs; reject anything else (offline safety net).
- Camera: center = AOI `origin` (from `/map/basemap/meta`); `dragRotate`/`pitchWithRotate`/touch-rotate **disabled** (north-up); default zoom from radius.
- **SLAM overlay** (re-homed from the canvas): world-model entities rendered as GeoJSON sources + layers / `maplibre.Marker`s, updated reactively from the world client:
  - launch point, drone, soldier, detections (type glyph + mono label), **designated/threat reticles (red)**, SLAM path polyline, selection highlight.
  - Positions via `localMetersToLatLng(origin, east_m, north_m)`.
  - Click → `onSelect(entityId)`, shared with map/intel selection (same prop contract `LocalMap2D` uses).
- MapLibre `ScaleControl` (mono-styled) + an attribution control ("© OpenStreetMap").

**`src/lib/projection.ts`** — add `localMetersToLatLng(origin, east_m, north_m): {lat,lng}` (equirectangular: `lat = origin.lat + north_m/111320`, `lng = origin.lng + east_m/(111320·cos(origin.lat))`). Must match the existing local-frame axis convention used by `buildings.json` (verify x=east, y=north sign during implementation so basemap + buildings register identically). Add the inverse if the overlay needs screen→frame.

**`src/app/operator/page.tsx`** — MAP tab:
- New **BASEMAP / GRID** segmented toggle (inverted style; persisted `localStorage["sg.basemap"]`).
- Fetch `/map/basemap/meta` once (small hook/state). Render logic:
  - BASEMAP selected **and** `meta.staged` → `<LocalMapGL …/>`.
  - else → existing `<LocalMap2D …/>` (unchanged).
  - BASEMAP selected but not staged → toggle shown disabled with hint "Set Area while online to cache."
- 3D path (`LocalMap3D`) unchanged.

**`src/components/OperationalArea.tsx`** — on SET AREA success, surface basemap status (e.g. "✓ basemap z10–15 cached" or "basemap unavailable (offline)").

### 4. Offline guarantee

Runtime: local pmtiles + local glyphs + style with only local URLs + `transformRequest` deny-non-local. Verified by a vitest assertion on the generated style and a manual network-cut check. Staging is the sole online step.

---

## Components / responsibilities (isolation)

| Unit | Responsibility | Depends on |
|---|---|---|
| `backend/app/basemap.py` | bbox math + pmtiles extract + meta | `pmtiles` lib, Protomaps build |
| `server.py` routes | stage (via /map/area), serve pmtiles/meta/glyphs | basemap.py, StaticFiles |
| `scripts/fetch_basemap.py` | CLI staging | basemap.py |
| `backend/assets/glyphs/` | offline label fonts | (static) |
| `lib/basemapStyle.ts` | monochrome MapLibre style (pure) | apiBase |
| `lib/projection.ts` | local meters ↔ lat/lng | origin anchor |
| `components/LocalMapGL.tsx` | render basemap + SLAM overlay | maplibre-gl, pmtiles, basemapStyle, projection, world client |
| `operator/page.tsx` | toggle + conditional render + meta fetch | LocalMapGL / LocalMap2D |
| `OperationalArea.tsx` | staging status line | /map/area response |

## Testing

- **Backend (pytest):** `bbox_from_radius` correctness; `/map/area` response includes `basemap` (extract mocked — no live network); `/map/basemap/meta` staged/unstaged; range serve returns 206 for a `Range` header; glyph route 200/404.
- **Frontend (vitest):** `localMetersToLatLng` round-trip + known offsets; `buildBasemapStyle` asserts **every** `glyphs`/source/tiles URL is local (offline guard) and no `sprite`.
- **Manual (on `:3000`, CORS-allowed):** SET AREA stages a basemap; MAP→BASEMAP renders monochrome map with labels under SLAM entities; toggle + uncached-fallback work; network-cut → still renders from cache.
- **Known limitation:** MapLibre needs WebGL; the headless browser can't render it (same as the 3D map). Visual confirmation is a manual/user step; automated tests cover projection, style URLs, serving, and bbox.

## Risks / notes

- **WebGL headless** → no automated visual verification of the render; covered above.
- **Glyph generation** is a one-time build step; PBFs are committed (documented in the plan).
- **Protomaps build pinning** + size: cap maxzoom and radius; a dated build URL avoids drift.
- **Axis convention**: must match `buildings.json` exactly or basemap and buildings misalign — verified during implementation.
- **PMTiles range serving**: confirm 206 partial content works end-to-end with the pmtiles reader.

## Success criteria

- SET AREA (online) caches `.context/basemap.pmtiles` + meta for the AOI.
- MAP→BASEMAP shows a monochrome OSM map with labels, aligned with buildings, SLAM entities (and red threats) on top, north-up.
- Toggle to GRID restores the existing canvas; uncached BASEMAP degrades gracefully.
- Zero runtime network (verified); ODbL attribution present.
