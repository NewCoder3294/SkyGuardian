"""Clean a mission's raw capture into captures/<id>/cleaned/ (clean phase CLI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.capture.cleaning import clean_mission  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Clean a captured mission.")
    ap.add_argument("--mission", required=True, help="mission_id under --root")
    ap.add_argument("--root", type=Path, default=Path("captures"))
    ap.add_argument("--dup-threshold", type=int, default=5)
    ap.add_argument("--conf-floor", type=float, default=0.1)
    ap.add_argument("--blank-std", type=float, default=5.0,
                    help="grayscale std below which a frame is treated as blank")
    args = ap.parse_args()

    report = clean_mission(args.root / args.mission,
                           dup_threshold=args.dup_threshold, conf_floor=args.conf_floor,
                           blank_std=args.blank_std)
    print(f"[clean] {json.dumps(report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
