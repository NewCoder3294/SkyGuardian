import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import LabelEvent, parse_client_message


def test_label_event_parses():
    raw = {"type": "label_event", "kind": "confirm", "source": "follower",
           "label": "person", "t": 1.0}
    msg = parse_client_message(raw)
    assert isinstance(msg, LabelEvent)
    assert msg.kind == "confirm"


def test_label_event_rejects_bad_kind():
    with pytest.raises(ValidationError):
        LabelEvent(kind="maybe", source="x", t=1.0)


def test_ws_records_label_event(tmp_path: Path, monkeypatch):
    from app import server
    from app.capture.recorder import CaptureRecorder

    rec = CaptureRecorder(root=tmp_path, mission_id="m1", enabled=True)
    monkeypatch.setattr(server, "_capture_recorder", rec)
    server._record_label_event(LabelEvent(kind="reject", source="follower",
                                          label="debris", t=2.0))
    ev = (tmp_path / "m1" / "events.jsonl").read_text().splitlines()[0]
    assert json.loads(ev)["kind"] == "reject"


def test_ws_records_correct_with_corrected_label(tmp_path: Path, monkeypatch):
    from app import server
    from app.capture.recorder import CaptureRecorder

    rec = CaptureRecorder(root=tmp_path, mission_id="m2", enabled=True)
    monkeypatch.setattr(server, "_capture_recorder", rec)
    server._record_label_event(LabelEvent(kind="correct", source="leader",
                                          label="person", corrected_label="soldier",
                                          box=[0.1, 0.1, 0.2, 0.2], t=3.0))
    rec_line = json.loads((tmp_path / "m2" / "events.jsonl").read_text().splitlines()[0])
    assert rec_line["kind"] == "correct"
    assert rec_line["corrected_label"] == "soldier"
    assert rec_line["mission_id"] == "m2"


def test_record_label_event_noop_without_recorder(monkeypatch):
    from app import server

    monkeypatch.setattr(server, "_capture_recorder", None)
    # Must not raise when capture is disabled.
    server._record_label_event(LabelEvent(kind="confirm", source="follower", t=1.0))
