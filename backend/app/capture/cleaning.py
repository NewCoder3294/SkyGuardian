"""Clean phase: filter a mission's raw capture into a curated observation set.

Rules: drop corrupt/blank frames, drop near-duplicate frames (perceptual hash),
drop degenerate/low-confidence boxes, quarantine unparseable records. Emits a
cleaned observations.jsonl + an auditable cleaning_report.json. Pure local I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .schema import Observation


def ahash(image_bgr) -> int:
    """64-bit average hash: 8x8 grayscale, bit set where pixel >= mean."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = small.mean()
    bits = 0
    for i, px in enumerate(small.flatten()):
        if px >= mean:
            bits |= (1 << i)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _is_blank(image_bgr, blank_std: float) -> bool:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.std()) < blank_std


def _clean_boxes(dets: list[dict], conf_floor: float) -> list[dict]:
    out = []
    for d in dets:
        box = d.get("box") or [0, 0, 0, 0]
        cx, cy, w, h = (list(box) + [0, 0, 0, 0])[:4]
        if w <= 0 or h <= 0:
            continue
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
            continue
        if float(d.get("conf", 0.0)) < conf_floor:
            continue
        out.append(d)
    return out


def clean_mission(mission_dir: Path, *, dup_threshold: int = 5,
                  conf_floor: float = 0.1, blank_std: float = 12.0) -> dict:
    mission_dir = Path(mission_dir)
    obs_path = mission_dir / "observations.jsonl"
    report = {"frames_in": 0, "dropped_corrupt": 0, "dropped_duplicate": 0,
              "frames_out": 0, "boxes_in": 0, "boxes_dropped": 0, "records_invalid": 0}
    kept: list[dict] = []
    last_hash: Optional[int] = None

    lines = obs_path.read_text().splitlines() if obs_path.exists() else []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            Observation.model_validate(rec)   # schema gate
        except Exception:  # noqa: BLE001 - quarantine, never crash
            report["records_invalid"] += 1
            continue

        report["frames_in"] += 1
        img = cv2.imread(str(mission_dir / rec["frame_path"]))
        if img is None or _is_blank(img, blank_std):
            report["dropped_corrupt"] += 1
            continue

        h = ahash(img)
        if last_hash is not None and hamming(h, last_hash) <= dup_threshold:
            report["dropped_duplicate"] += 1
            continue
        last_hash = h

        report["boxes_in"] += len(rec.get("detections", []))
        cleaned_boxes = _clean_boxes(rec.get("detections", []), conf_floor)
        report["boxes_dropped"] += len(rec.get("detections", [])) - len(cleaned_boxes)
        rec["detections"] = cleaned_boxes
        kept.append(rec)
        report["frames_out"] += 1

    out_dir = mission_dir / "cleaned"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "observations.jsonl").open("w") as fh:
        for rec in kept:
            fh.write(json.dumps(rec) + "\n")
    (out_dir / "cleaning_report.json").write_text(json.dumps(report, indent=2))
    return report
