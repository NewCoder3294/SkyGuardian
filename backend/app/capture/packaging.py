"""Package phase: cleaned observations (+ events) -> YOLO dataset + Gemma example
set + a Foundry-ready manifest. Pure local I/O. Train/val split is a deterministic
hash of the frame path (reproducible, no RNG)."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional

from .schema import Event


def _is_val(frame_path: str, val_frac: float) -> bool:
    digest = hashlib.md5(frame_path.encode()).hexdigest()
    return (int(digest, 16) % 1000) < int(val_frac * 1000)


def _load_events(ev_path: Path) -> list[dict]:
    """Load events.jsonl, skipping malformed/partial lines (the recorder is
    append-only and an unclean shutdown can truncate the last line). Mirrors the
    schema-gate cleaning applies to observations, so packaging never KeyErrors."""
    out: list[dict] = []
    if not ev_path.exists():
        return out
    for line in ev_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            Event.model_validate(rec)
        except Exception:  # noqa: BLE001 - skip bad/partial event lines
            continue
        out.append(rec)
    return out


def _correction_for(events: list[dict], label: str) -> Optional[str]:
    """Resolve an operator decision for a detection CLASS (matching is class-wide,
    not per-box): the corrected label if a 'correct' event exists for this label,
    '' if a 'reject' event exists (drop boxes of this class), else None. Events are
    scanned latest-first so the most recent decision for a class wins."""
    for ev in reversed(events):
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
    events = _load_events(mission_dir / "events.jsonl")

    resolved: list[tuple[dict, list[tuple[str, list[float]]]]] = []
    classes: set[str] = set()
    for rec in obs:
        kept = []
        for d in rec.get("detections", []):
            corr = _correction_for(events, d["label"])
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
    class_counts: dict[str, dict[str, int]] = {}
    gemma_lines = []
    labeled_count = 0
    for rec, kept in resolved:
        split = "val" if _is_val(rec["frame_path"], val_frac) else "train"
        counts[split] += 1
        for label, _ in kept:
            cc = class_counts.setdefault(label, {"count": 0, "train": 0, "val": 0})
            cc["count"] += 1
            cc[split] += 1
        # Derive a collision-proof stem from the full relative path (frames may
        # later live in per-source subdirs; a bare filename stem could clash).
        stem = rec["frame_path"].replace("/", "_").replace("\\", "_").rsplit(".", 1)[0]
        src = mission_dir / rec["frame_path"]
        try:
            shutil.copyfile(src, out_dir / "yolo" / "images" / split / f"{stem}.jpg")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Frame not found: {src} (observation t={rec.get('t')!r})")
        label_txt = "\n".join(
            f"{class_id[label]} {b[0]:.6f} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f}"
            for label, b in kept)
        (out_dir / "yolo" / "labels" / split / f"{stem}.txt").write_text(
            label_txt + ("\n" if label_txt else ""))

        # Gemma gold: a frame gets a gold answer only when an operator confirm/
        # correct event vouches for a label visible in THIS frame. The answer then
        # describes ALL entities present (the prompt asks for a description,
        # plural) rather than a single class. Unvouched frames stay unlabeled.
        kept_labels = sorted({lbl for lbl, _ in kept})
        has_operator_signal = any(
            ev["kind"] in ("correct", "confirm")
            and ((ev.get("corrected_label") or ev.get("label")) in kept_labels
                 or ev.get("label") in kept_labels)
            for ev in events
        )
        gold = None
        if has_operator_signal and kept_labels:
            gold = "Entities present: " + ", ".join(kept_labels) + "."
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
                 "val": counts["val"], "format": "ultralytics",
                 "class_counts": class_counts},
        "gemma": {"path": "gemma/examples.jsonl", "count": len(gemma_lines),
                  "labeled_count": labeled_count},
        "cleaning_report": cleaning_report,
        "label_events": label_event_counts,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
