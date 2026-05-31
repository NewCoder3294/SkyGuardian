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
