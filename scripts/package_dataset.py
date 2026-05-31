"""Package a cleaned mission into a YOLO + Gemma dataset (package phase CLI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.capture.packaging import package_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Package a cleaned mission into a dataset.")
    ap.add_argument("--mission", required=True)
    ap.add_argument("--root", type=Path, default=Path("captures"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--created-t", type=float, default=0.0,
                    help="timestamp to stamp into the manifest (injected; default 0)")
    args = ap.parse_args()

    manifest = package_dataset(args.root / args.mission, args.out,
                               val_frac=args.val_frac, created_t=args.created_t)
    print(f"[package] {json.dumps(manifest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
