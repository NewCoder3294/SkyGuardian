"""Package phase: cleaned observations (+ events) -> YOLO dataset + Gemma example
set + a Foundry-ready manifest. Pure local I/O. Train/val split is a deterministic
hash of the frame path (reproducible, no RNG)."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional


def _is_val(frame_path: str, val_frac: float) -> bool:
    digest = hashlib.md5(frame_path.encode()).hexdigest()
    return (int(digest, 16) % 1000) < int(val_frac * 1000)


def _correction_for(events: list[dict], label: str, box) -> Optional[str]:
    """Return a corrected label for a (label, box) if a matching 'correct' event
    exists; '' if a matching 'reject' (drop this box); None if no event."""
    for ev in events:
        if ev.get("label") != label:
            continue
        if ev["kind"] == "correct" and ev.get("corrected_label"):
            return ev["corrected_label"]
        if ev["kind"] == "reject":
            return ""
    return None


def package_dataset(mission_dir: Path, out_dir: Path, *, val_frac: float = 0.2,
                    created_t: float = 0.0) -> dict:
    mission_dir = Path(mission_dir)
    out_dir = Path(out_dir)
    cleaned = mission_dir / "cleaned" / "observations.jsonl"
    if not cleaned.exists():
        raise FileNotFoundError(
            f"No cleaned data at {cleaned}. Run scripts/clean_captures.py first.")

    obs = [json.loads(l) for l in cleaned.read_text().splitlines() if l.strip()]
    events = []
    ev_path = mission_dir / "events.jsonl"
    if ev_path.exists():
        events = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]

    resolved: list[tuple[dict, list[tuple[str, list[float]]]]] = []
    classes: set[str] = set()
    for rec in obs:
        kept = []
        for d in rec.get("detections", []):
            corr = _correction_for(events, d["label"], d.get("box"))
            if corr == "":
                continue
            label = corr or d["label"]
            classes.add(label)
            kept.append((label, d["box"]))
        resolved.append((rec, kept))

    names = sorted(classes)
    class_id = {n: i for i, n in enumerate(names)}

    for split in ("train", "val"):
        (out_dir / "yolo" / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_dir / "yolo" / "labels" / split).mkdir(parents=True, exist_ok=True)
    (out_dir / "gemma").mkdir(parents=True, exist_ok=True)

    counts = {"train": 0, "val": 0}
    gemma_lines = []
    labeled_count = 0
    for rec, kept in resolved:
        split = "val" if _is_val(rec["frame_path"], val_frac) else "train"
        counts[split] += 1
        stem = Path(rec["frame_path"]).stem
        shutil.copyfile(mission_dir / rec["frame_path"],
                        out_dir / "yolo" / "images" / split / f"{stem}.jpg")
        label_txt = "\n".join(
            f"{class_id[label]} {b[0]} {b[1]} {b[2]} {b[3]}" for label, b in kept)
        (out_dir / "yolo" / "labels" / split / f"{stem}.txt").write_text(
            label_txt + ("\n" if label_txt else ""))

        gold = None
        for ev in events:
            if ev["kind"] in ("correct", "confirm"):
                gold = ev.get("corrected_label") or ev.get("label")
                break
        labeled = gold is not None
        labeled_count += int(labeled)
        gemma_lines.append(json.dumps({
            "frame_path": rec["frame_path"],
            "context": {"labels_seen": [k[0] for k in kept],
                        "pose": rec.get("pose"), "t": rec["t"]},
            "prompt": "Describe the tactically relevant entities in this frame.",
            "gold_answer": gold,
            "labeled": labeled,
        }))

    (out_dir / "gemma" / "examples.jsonl").write_text("\n".join(gemma_lines) +
                                                       ("\n" if gemma_lines else ""))
    (out_dir / "yolo" / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/val\n"
        f"nc: {len(names)}\nnames: {names}\n")

    cleaning_report = {}
    cr_path = mission_dir / "cleaned" / "cleaning_report.json"
    if cr_path.exists():
        cleaning_report = json.loads(cr_path.read_text())
        (out_dir / "cleaning_report.json").write_text(json.dumps(cleaning_report, indent=2))

    label_event_counts = {"confirm": 0, "reject": 0, "correct": 0}
    for ev in events:
        if ev["kind"] in label_event_counts:
            label_event_counts[ev["kind"]] += 1

    manifest = {
        "v": 1,
        "created_t": created_t,
        "mission_ids": [mission_dir.name],
        "source_counts": {"leader": sum(1 for r, _ in resolved if r["source"] == "leader"),
                          "follower": sum(1 for r, _ in resolved if r["source"] == "follower")},
        "yolo": {"path": "yolo/", "classes": names, "train": counts["train"],
                 "val": counts["val"], "format": "ultralytics"},
        "gemma": {"path": "gemma/examples.jsonl", "count": len(gemma_lines),
                  "labeled_count": labeled_count},
        "cleaning_report": cleaning_report,
        "label_events": label_event_counts,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
