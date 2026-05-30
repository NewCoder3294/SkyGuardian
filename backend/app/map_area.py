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
