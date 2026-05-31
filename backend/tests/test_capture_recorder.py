import json
from pathlib import Path

import numpy as np

from app.capture.recorder import CaptureRecorder
from app.capture.schema import Event
from app.contracts import DetectionBox, Vec3


def _frame():
    return np.full((48, 64, 3), 127, dtype=np.uint8)  # H=48 W=64


def _box(label="vehicle", conf=0.9):
    return DetectionBox(label=label, confidence=conf, cx=0.5, cy=0.5, w=0.2, h=0.2)


def _rec(tmp_path, **kw):
    opts = dict(root=tmp_path, mission_id="m1", max_mb=100.0, cadence_s=1000.0,
                low_conf=0.4, enabled=True)
    opts.update(kw)
    return CaptureRecorder(**opts)


def test_low_confidence_detection_is_saved(tmp_path: Path):
    rec = _rec(tmp_path)
    saved = rec.observe(_frame(), [_box(conf=0.2)], None, 1.0,
                        source="leader", image_w=64, image_h=48)
    assert saved is True
    obs_file = tmp_path / "m1" / "observations.jsonl"
    line = json.loads(obs_file.read_text().splitlines()[0])
    assert line["sampled_reason"] == "low_conf"
    assert line["detections"][0]["box"] == [0.5, 0.5, 0.2, 0.2]
    assert (tmp_path / "m1" / line["frame_path"]).exists()


def test_novel_class_is_saved_then_redundant_skipped(tmp_path: Path):
    rec = _rec(tmp_path)
    assert rec.observe(_frame(), [_box("person")], None, 1.0,
                       source="leader", image_w=64, image_h=48) is True
    assert rec.observe(_frame(), [_box("person")], None, 1.5,
                       source="leader", image_w=64, image_h=48) is False


def test_cadence_saves_after_interval(tmp_path: Path):
    rec = _rec(tmp_path, cadence_s=2.0)
    assert rec.observe(_frame(), [_box("car")], None, 1.0,
                       source="leader", image_w=64, image_h=48) is True   # novel
    assert rec.observe(_frame(), [_box("car")], None, 2.0,
                       source="leader", image_w=64, image_h=48) is False  # <2s, known
    assert rec.observe(_frame(), [_box("car")], None, 3.5,
                       source="leader", image_w=64, image_h=48) is True   # cadence


def test_disabled_recorder_is_noop(tmp_path: Path):
    rec = _rec(tmp_path, enabled=False)
    assert rec.observe(_frame(), [_box(conf=0.1)], None, 1.0,
                       source="leader", image_w=64, image_h=48) is False
    assert not (tmp_path / "m1").exists()


def test_max_mb_stops_saving(tmp_path: Path):
    rec = _rec(tmp_path, max_mb=0.0)
    assert rec.observe(_frame(), [_box(conf=0.1)], None, 1.0,
                       source="leader", image_w=64, image_h=48) is False


def test_record_event_appends(tmp_path: Path):
    rec = _rec(tmp_path)
    rec.record_event(Event(t=1.0, mission_id="m1", kind="confirm", source="follower",
                           label="person"))
    ev_file = tmp_path / "m1" / "events.jsonl"
    assert json.loads(ev_file.read_text().splitlines()[0])["kind"] == "confirm"


def test_observe_never_raises_on_bad_frame(tmp_path: Path):
    rec = _rec(tmp_path)
    saved = rec.observe(None, [_box(conf=0.1)], None, 1.0,
                        source="leader", image_w=0, image_h=0)
    assert saved is False
