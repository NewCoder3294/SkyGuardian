"""One-time OSM-buildings downloader for the offline map layer.

Pulls real building polygons from the OpenStreetMap Overpass API for a
configurable lat/lng centre + radius, projects each polygon into the
SkyGuardian local frame (metres, x=east, y=north, z=up), and writes a single
JSON file the backend serves to the dashboard. No GPS at runtime — the
projection is precomputed against the operator-supplied launch origin.

Usage:
  python3 scripts/fetch_buildings.py \
      --lat 37.7749 --lng -122.4194 --radius 400 \
      --out .context/buildings.json

This script REQUIRES internet (talks to overpass-api.de). It is intended to
run once before a demo, leaving a self-contained .context/buildings.json that
the dashboard reads with no network access.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable
from urllib import request


# Standard Overpass endpoint. We accept multiple, fall back on failure.
_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
)


def _overpass_query(lat: float, lng: float, radius_m: int) -> str:
    """Build a query that returns building polygons + their heights within
    `radius_m` metres of the supplied centre."""
    # `building` is the canonical OSM tag for any structure footprint.
    return (
        f"[out:json][timeout:60];"
        f'(way["building"](around:{radius_m},{lat},{lng});'
        f'relation["building"](around:{radius_m},{lat},{lng}););'
        "out geom tags;"
    )


def _fetch_overpass(query: str) -> dict:
    """POST to Overpass; try each mirror until one returns 200."""
    last_err: Exception | None = None
    body = query.encode("utf-8")
    for url in _OVERPASS_ENDPOINTS:
        try:
            req = request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    # Overpass rejects requests with no User-Agent (406).
                    "User-Agent": (
                        "SkyGuardian/1.0 buildings-fetcher (one-time, local cache)"
                    ),
                },
            )
            with request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"All Overpass endpoints failed; last: {last_err}")


def _project_enu(lat: float, lng: float, origin_lat: float, origin_lng: float) -> tuple[float, float]:
    """Convert (lat, lng) → (east_m, north_m) relative to (origin_lat, origin_lng).

    Equirectangular approximation — accurate to <1 m for the few-hundred-metre
    radii relevant to a tactical demo, and zero external deps."""
    earth_r = 6_378_137.0  # metres
    olat = math.radians(origin_lat)
    east = math.radians(lng - origin_lng) * earth_r * math.cos(olat)
    north = math.radians(lat - origin_lat) * earth_r
    return (east, north)


def _height_metres(tags: dict) -> float:
    """Pull a building height (metres) from OSM tags. Falls back to a 3m × levels
    estimate, then to a sensible 6m default for tagged-but-unsized buildings."""
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
    """Yield closed rings of [lat, lng] vertices from an Overpass `way`."""
    geom = way.get("geometry") or []
    if len(geom) < 3:
        return
    ring = [[p["lat"], p["lon"]] for p in geom]
    # Drop trailing duplicate if present.
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) >= 3:
        yield ring


def _polygons_from_relation(rel: dict) -> Iterable[list[list[float]]]:
    """Multipolygon relations: yield each outer ring."""
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
    """Walk the Overpass response, emit one dict per building polygon in the
    local frame: { 'polygon': [[east_m, north_m], ...], 'height_m': float,
    'name': str | None, 'id': int }."""
    out: list[dict] = []
    for el in overpass_json.get("elements", []):
        tags = el.get("tags") or {}
        if "building" not in tags:
            continue
        height = _height_metres(tags)
        name = tags.get("name") or tags.get("addr:housename")
        rings: Iterable[list[list[float]]]
        if el.get("type") == "way":
            rings = list(_polygons_from_way(el))
        elif el.get("type") == "relation":
            rings = list(_polygons_from_relation(el))
        else:
            continue
        for ring in rings:
            projected = [list(_project_enu(p[0], p[1], origin_lat, origin_lng)) for p in ring]
            out.append({
                "id": el.get("id"),
                "name": name,
                "height_m": round(height, 1),
                "polygon": [[round(x, 2), round(y, 2)] for x, y in projected],
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="One-time OSM building cache for offline map.")
    ap.add_argument("--lat", type=float, required=True, help="origin latitude (degrees)")
    ap.add_argument("--lng", type=float, required=True, help="origin longitude (degrees)")
    ap.add_argument("--radius", type=int, default=400, help="metres around origin (default 400)")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(".context") / "buildings.json",
        help="output JSON path",
    )
    args = ap.parse_args()

    print(f"[buildings] querying overpass for buildings within {args.radius}m "
          f"of ({args.lat:.5f}, {args.lng:.5f})…")
    raw = _fetch_overpass(_overpass_query(args.lat, args.lng, args.radius))
    buildings = collect_buildings(raw, args.lat, args.lng)
    print(f"[buildings] collected {len(buildings)} building polygons")

    payload = {
        "origin": {"lat": args.lat, "lng": args.lng},
        "radius_m": args.radius,
        "count": len(buildings),
        "buildings": buildings,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload))
    print(f"[buildings] wrote {args.out} ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
