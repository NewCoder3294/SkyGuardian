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
