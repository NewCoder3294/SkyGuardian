import json
from pathlib import Path

import cv2
import numpy as np

from app.capture.packaging import package_dataset


def _setup_cleaned(tmp_path: Path):
    mdir = tmp_path / "m1"
    (mdir / "frames").mkdir(parents=True)
    for i in range(4):
        cv2.imwrite(str(mdir / f"frames/00000{i}.jpg"),
                    np.full((48, 64, 3), 50 + i * 40, dtype=np.uint8))
    cleaned = mdir / "cleaned"
    cleaned.mkdir(parents=True)
    lines = []
    for i in range(4):
        lines.append(json.dumps({
            "v": 1, "t": float(i), "mission_id": "m1",
            "frame_path": f"frames/00000{i}.jpg", "source": "leader",
            "image_w": 64, "image_h": 48, "pose": None,
            "detections": [{"label": "car" if i % 2 else "person",
                            "conf": 0.9, "box": [0.5, 0.5, 0.2, 0.2]}],
            "sampled_reason": "cadence",
        }))
    (cleaned / "observations.jsonl").write_text("\n".join(lines) + "\n")
    (cleaned / "cleaning_report.json").write_text(json.dumps({"frames_out": 4}))
    (mdir / "events.jsonl").write_text(json.dumps({
        "v": 1, "t": 0.0, "mission_id": "m1", "kind": "correct", "source": "leader",
        "label": "person", "corrected_label": "soldier", "box": [0.5, 0.5, 0.2, 0.2],
    }) + "\n")
    return mdir


def _is_num(s):
    try:
        float(s); return True
    except ValueError:
        return False


def test_package_builds_yolo_gemma_manifest(tmp_path: Path):
    mdir = _setup_cleaned(tmp_path)
    out = tmp_path / "datasets" / "d1"
    manifest = package_dataset(mdir, out, val_frac=0.25, created_t=123.0)

    assert (out / "yolo" / "data.yaml").exists()
    train_lbls = list((out / "yolo" / "labels" / "train").glob("*.txt"))
    val_lbls = list((out / "yolo" / "labels" / "val").glob("*.txt"))
    assert len(train_lbls) + len(val_lbls) == 4
    sample = (train_lbls + val_lbls)[0].read_text().strip().split("\n")[0].split()
    assert len(sample) == 5 and all(_is_num(x) for x in sample)
    names = manifest["yolo"]["classes"]
    assert "soldier" in names

    gemma = [json.loads(l) for l in
             (out / "gemma" / "examples.jsonl").read_text().splitlines()]
    assert len(gemma) == 4
    assert {"frame_path", "context", "prompt", "gold_answer", "labeled"} <= set(gemma[0])

    assert manifest["yolo"]["train"] + manifest["yolo"]["val"] == 4
    assert manifest["created_t"] == 123.0
    assert manifest["cleaning_report"]["frames_out"] == 4
    assert (out / "manifest.json").exists()
    assert (out / "cleaning_report.json").exists()


def test_package_split_is_deterministic(tmp_path: Path):
    mdir = _setup_cleaned(tmp_path)
    a = package_dataset(mdir, tmp_path / "da", val_frac=0.25, created_t=1.0)
    b = package_dataset(mdir, tmp_path / "db", val_frac=0.25, created_t=1.0)
    assert a["yolo"]["train"] == b["yolo"]["train"]
    assert a["yolo"]["val"] == b["yolo"]["val"]


def test_package_missing_cleaned_raises(tmp_path: Path):
    import pytest
    (tmp_path / "m2").mkdir()
    with pytest.raises(FileNotFoundError):
        package_dataset(tmp_path / "m2", tmp_path / "out", created_t=0.0)


def test_gemma_gold_describes_all_entities_when_vouched(tmp_path: Path):
    mdir = tmp_path / "mg"
    (mdir / "frames").mkdir(parents=True)
    cv2.imwrite(str(mdir / "frames/000000.jpg"),
                np.full((48, 64, 3), 90, dtype=np.uint8))
    cleaned = mdir / "cleaned"
    cleaned.mkdir(parents=True)
    (cleaned / "observations.jsonl").write_text(json.dumps({
        "v": 1, "t": 0.0, "mission_id": "mg", "frame_path": "frames/000000.jpg",
        "source": "leader", "image_w": 64, "image_h": 48, "pose": None,
        "detections": [{"label": "person", "conf": 0.9, "box": [0.3, 0.3, 0.1, 0.1]},
                       {"label": "vehicle", "conf": 0.9, "box": [0.6, 0.6, 0.2, 0.2]}],
        "sampled_reason": "cadence",
    }) + "\n")
    (cleaned / "cleaning_report.json").write_text(json.dumps({"frames_out": 1}))
    # Operator confirms a 'person' that is visible here -> frame is vouched.
    (mdir / "events.jsonl").write_text(json.dumps({
        "v": 1, "t": 0.0, "mission_id": "mg", "kind": "confirm", "source": "leader",
        "label": "person",
    }) + "\n")
    out = tmp_path / "datasets" / "dg"
    package_dataset(mdir, out, val_frac=0.0, created_t=1.0)
    g = json.loads((out / "gemma" / "examples.jsonl").read_text().splitlines()[0])
    assert g["labeled"] is True
    # The gold answer lists BOTH entities present, not just the confirmed one.
    assert "person" in g["gold_answer"] and "vehicle" in g["gold_answer"]


def test_reject_drops_boxes_and_unlabeled_gemma(tmp_path: Path):
    mdir = tmp_path / "m3"
    (mdir / "frames").mkdir(parents=True)
    cv2.imwrite(str(mdir / "frames/000000.jpg"),
                np.full((48, 64, 3), 80, dtype=np.uint8))
    cleaned = mdir / "cleaned"
    cleaned.mkdir(parents=True)
    (cleaned / "observations.jsonl").write_text(json.dumps({
        "v": 1, "t": 0.0, "mission_id": "m3", "frame_path": "frames/000000.jpg",
        "source": "leader", "image_w": 64, "image_h": 48, "pose": None,
        "detections": [{"label": "debris", "conf": 0.9, "box": [0.5, 0.5, 0.2, 0.2]}],
        "sampled_reason": "cadence",
    }) + "\n")
    (cleaned / "cleaning_report.json").write_text(json.dumps({"frames_out": 1}))
    # No events at all -> no labels, gold_answer None (background sample).
    out = tmp_path / "datasets" / "d3"
    manifest = package_dataset(mdir, out, val_frac=0.0, created_t=1.0)
    label = next((out / "yolo" / "labels" / "train").glob("*.txt"))
    assert label.read_text().strip() != ""          # the detection is kept
    gemma = json.loads((out / "gemma" / "examples.jsonl").read_text().splitlines()[0])
    assert gemma["gold_answer"] is None and gemma["labeled"] is False
    assert manifest["gemma"]["labeled_count"] == 0

    # Add a reject event for "debris" -> the box is dropped, no classes remain.
    (mdir / "events.jsonl").write_text(json.dumps({
        "v": 1, "t": 0.0, "mission_id": "m3", "kind": "reject", "source": "leader",
        "label": "debris", "box": [0.5, 0.5, 0.2, 0.2],
    }) + "\n")
    out2 = tmp_path / "datasets" / "d3b"
    manifest2 = package_dataset(mdir, out2, val_frac=0.0, created_t=1.0)
    label2 = next((out2 / "yolo" / "labels" / "train").glob("*.txt"))
    assert label2.read_text().strip() == ""          # rejected box gone
    assert manifest2["yolo"]["classes"] == []
    assert manifest2["label_events"]["reject"] == 1
