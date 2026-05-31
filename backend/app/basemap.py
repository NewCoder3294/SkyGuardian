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

# Protomaps prunes old daily builds, so this date drifts out of existence over
# time. Override with PROTOMAPS_BUILD_URL, or bump to a current build listed at
# https://build.protomaps.com/ (probe `<date>.pmtiles` for HTTP 206).
PROTOMAPS_BUILD_URL = os.environ.get(
    "PROTOMAPS_BUILD_URL", "https://build.protomaps.com/20260526.pmtiles"
)
DEFAULT_MAXZOOM = int(os.environ.get("BASEMAP_MAXZOOM", "15"))
_EARTH_M_PER_DEG_LAT = 111_320.0


@dataclass
class BasemapMeta:
    staged: bool
    bytes: int
    minzoom: int
    maxzoom: int
    bbox: list[float]
    origin: dict
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
    tmp = out_path.parent / (out_path.name + ".tmp")
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
