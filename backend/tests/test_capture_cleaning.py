import json
from pathlib import Path

import cv2
import numpy as np

from app.capture.cleaning import ahash, clean_mission, hamming


def _write_frame(path: Path, value, noise=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.full((48, 64, 3), value, dtype=np.uint8)
    if noise:
        img[0:24, 0:32] = (value + 80) % 255
    cv2.imwrite(str(path), img)


def _obs_line(frame_path, dets, t):
    return json.dumps({
        "v": 1, "t": t, "mission_id": "m1", "frame_path": frame_path,
        "source": "leader", "image_w": 64, "image_h": 48, "pose": None,
        "detections": dets, "sampled_reason": "cadence",
    })


def test_ahash_and_hamming_identical_is_zero():
    img = np.full((48, 64, 3), 100, dtype=np.uint8)
    assert hamming(ahash(img), ahash(img)) == 0


def test_clean_drops_blank_dup_and_degenerate(tmp_path: Path):
    mdir = tmp_path / "m1"
    _write_frame(mdir / "frames/000000.jpg", 60, noise=True)
    _write_frame(mdir / "frames/000001.jpg", 60, noise=True)   # near-dup of f0
    _write_frame(mdir / "frames/000002.jpg", 10, noise=False)  # blank/uniform

    lines = [
        _obs_line("frames/000000.jpg",
                  [{"label": "car", "conf": 0.9, "box": [0.5, 0.5, 0.2, 0.2]},
                   {"label": "x", "conf": 0.9, "box": [0.5, 0.5, 0.0, 0.2]}], 1.0),
        _obs_line("frames/000001.jpg",
                  [{"label": "car", "conf": 0.9, "box": [0.4, 0.4, 0.2, 0.2]}], 1.2),
        _obs_line("frames/000002.jpg",
                  [{"label": "car", "conf": 0.9, "box": [0.5, 0.5, 0.2, 0.2]}], 1.4),
        "{ this is not valid json",
    ]
    (mdir / "observations.jsonl").write_text("\n".join(lines) + "\n")

    report = clean_mission(mdir, dup_threshold=5, conf_floor=0.1, blank_std=12.0)

    kept = [json.loads(l) for l in
            (mdir / "cleaned/observations.jsonl").read_text().splitlines()]
    assert len(kept) == 1
    assert kept[0]["frame_path"] == "frames/000000.jpg"
    assert len(kept[0]["detections"]) == 1     # degenerate box dropped
    assert report["frames_in"] == 3
    assert report["dropped_duplicate"] == 1
    assert report["dropped_corrupt"] == 1
    assert report["frames_out"] == 1
    assert report["boxes_dropped"] == 1
    assert report["records_invalid"] == 1
    assert json.loads((mdir / "cleaned/cleaning_report.json").read_text())["frames_out"] == 1
