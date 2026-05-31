# Data Flywheel (Collect / Clean / Package) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture frames + detections (+ operator labels) during a mission, clean them, and package them into a YOLO dataset + Gemma example set + a Foundry-ready manifest — local-first and offline.

**Architecture:** A best-effort, opt-in `CaptureRecorder` is called from the perception loop and writes `captures/<mission>/{frames,observations.jsonl,events.jsonl}`. Pure `cleaning` and `packaging` modules (with thin CLI wrappers) turn that into `captures/<mission>/cleaned/` and then `datasets/<name>/`. A new `LabelEvent` wire message lets clients record operator confirm/reject decisions. Training and Foundry upload are deferred.

**Tech Stack:** Python 3.13 / FastAPI / pydantic / numpy / opencv (cv2) / pytest (backend, run from `backend/` with `pythonpath=.`); TypeScript (shared contracts); Swift / XCTest (mobile contract parity).

**Spec:** `docs/superpowers/specs/2026-05-30-data-flywheel-capture-clean-package-design.md`

---

## File Structure

- **Create** `backend/app/capture/__init__.py` — package marker.
- **Create** `backend/app/capture/schema.py` — `Detection`, `Observation`, `Event` record models.
- **Create** `backend/app/capture/recorder.py` — `CaptureRecorder` (collect).
- **Create** `backend/app/capture/cleaning.py` — pure cleaning rules + report.
- **Create** `backend/app/capture/packaging.py` — pure packaging (YOLO + Gemma + manifest).
- **Create** `scripts/clean_captures.py`, `scripts/package_dataset.py` — thin CLIs.
- **Modify** `backend/app/contracts.py` — add `LabelEvent`; extend `ClientMessage` + `parse_client_message`.
- **Modify** `backend/app/perception/pipeline.py` — accept a recorder, call `observe(...)` per tick.
- **Modify** `backend/app/server.py` — construct recorder when `CAPTURE_ENABLED`; record `LabelEvent` in the WS handler.
- **Modify** `shared/contracts.ts` — mirror `LabelEvent`.
- **Modify** `mobile/Sources/Contracts.swift` (+ `WorldClient.swift`, `FollowCoordinator.swift`) — `LabelEventMessage` + `sendLabelEvent` + emit on confirm.
- **Create** backend tests under `backend/tests/`; mobile test in `mobile/Tests/ContractsTests.swift`.

All backend commands run from `backend/` via `.venv/bin/python -m pytest` (pytest `pythonpath=.`, import as `app.<module>`).

---

## Task 1: Capture record schema

**Files:**
- Create: `backend/app/capture/__init__.py` (empty)
- Create: `backend/app/capture/schema.py`
- Test: `backend/tests/test_capture_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_capture_schema.py
import pytest
from pydantic import ValidationError

from app.capture.schema import Detection, Event, Observation
from app.contracts import Vec3


def test_observation_round_trips():
    obs = Observation(
        t=1.5, mission_id="m1", frame_path="frames/000001.jpg", source="leader",
        image_w=1280, image_h=720, pose=Vec3(x=1.0, y=2.0, z=0.0),
        detections=[Detection(label="vehicle", conf=0.42, box=[0.5, 0.5, 0.1, 0.2])],
        sampled_reason="low_conf",
    )
    dumped = obs.model_dump(mode="json")
    again = Observation.model_validate(dumped)
    assert again.frame_path == "frames/000001.jpg"
    assert again.detections[0].label == "vehicle"
    assert again.pose.x == 1.0
    assert again.sampled_reason == "low_conf"


def test_observation_pose_optional():
    obs = Observation(
        t=0.0, mission_id="m1", frame_path="f.jpg", source="leader",
        image_w=10, image_h=10, detections=[], sampled_reason="cadence",
    )
    assert obs.pose is None


def test_detection_conf_bounds():
    with pytest.raises(ValidationError):
        Detection(label="x", conf=1.5, box=[0, 0, 0, 0])


def test_event_round_trips():
    ev = Event(t=2.0, mission_id="m1", kind="correct", source="follower",
               label="person", corrected_label="soldier", box=[0.1, 0.1, 0.2, 0.2])
    again = Event.model_validate(ev.model_dump(mode="json"))
    assert again.kind == "correct"
    assert again.corrected_label == "soldier"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_schema.py -v`
Expected: `ModuleNotFoundError: No module named 'app.capture'`.

- [ ] **Step 3: Create the package + schema**

Create empty `backend/app/capture/__init__.py`. Create `backend/app/capture/schema.py`:

```python
"""Versioned on-disk record schema for field-captured data (collect phase).

These are the JSONL line formats written under captures/<mission_id>/. Versioned
(`v`) so the clean/package steps stay stable as the schema evolves.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..contracts import Vec3


class Detection(BaseModel):
    """One detection on a saved frame. `box` is [cx, cy, w, h], normalized 0..1."""
    label: str
    conf: float = Field(ge=0.0, le=1.0)
    box: list[float]


class Observation(BaseModel):
    """One saved frame + its detections + context. One per observations.jsonl line."""
    v: int = 1
    t: float
    mission_id: str
    frame_path: str            # relative to the mission dir, e.g. "frames/000001.jpg"
    source: str                # "leader" (Mavic) | "follower" (Tello)
    image_w: int
    image_h: int
    pose: Optional[Vec3] = None
    detections: list[Detection]
    sampled_reason: Literal["low_conf", "novel_class", "cadence"]


class Event(BaseModel):
    """An operator label action. One per events.jsonl line."""
    v: int = 1
    t: float
    mission_id: str
    kind: Literal["confirm", "reject", "correct"]
    source: str
    label: Optional[str] = None
    corrected_label: Optional[str] = None
    box: Optional[list[float]] = None
    note: Optional[str] = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/capture/__init__.py backend/app/capture/schema.py backend/tests/test_capture_schema.py
git commit -m "feat(capture): versioned record schema for field data"
```

---

## Task 2: CaptureRecorder (collect)

**Files:**
- Create: `backend/app/capture/recorder.py`
- Test: `backend/tests/test_capture_recorder.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_capture_recorder.py
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
    # First high-conf "person" is a novel class -> saved.
    assert rec.observe(_frame(), [_box("person")], None, 1.0,
                       source="leader", image_w=64, image_h=48) is True
    # Same class, high conf, before cadence elapses -> skipped.
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
    rec = _rec(tmp_path, max_mb=0.0)  # zero budget -> never save a frame
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
    # A frame cv2 can't encode must not propagate an exception into the caller.
    saved = rec.observe(None, [_box(conf=0.1)], None, 1.0,
                        source="leader", image_w=0, image_h=0)
    assert saved is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.capture.recorder'`.

- [ ] **Step 3: Implement the recorder**

```python
# backend/app/capture/recorder.py
"""Best-effort, opt-in capture of field data (collect phase).

Called from the perception loop. Writes sampled frames + an observations JSONL
under captures/<mission_id>/. Pure local disk; no network. Every disk operation
is wrapped so a failure is logged and swallowed — capture must NEVER crash or
block the live perception loop.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2

from ..contracts import DetectionBox, Vec3
from .schema import Detection, Event, Observation


class CaptureRecorder:
    def __init__(
        self,
        *,
        root: Path,
        mission_id: str,
        max_mb: float = 2000.0,
        cadence_s: float = 2.0,
        low_conf: float = 0.4,
        enabled: bool = True,
    ) -> None:
        self._dir = Path(root) / mission_id
        self._mission_id = mission_id
        self._max_bytes = int(max_mb * 1_000_000)
        self._cadence_s = cadence_s
        self._low_conf = low_conf
        self._enabled = enabled
        self._seq = 0
        self._bytes = 0
        self._last_save_t: Optional[float] = None
        self._seen_classes: set[str] = set()
        self._budget_warned = False

    def _reason(self, boxes: list[DetectionBox], t: float) -> Optional[str]:
        """Sampling policy -> why we'd save this frame, or None to skip."""
        if any(b.confidence < self._low_conf for b in boxes):
            return "low_conf"
        if any(b.label not in self._seen_classes for b in boxes):
            return "novel_class"
        if self._last_save_t is None or (t - self._last_save_t) >= self._cadence_s:
            return "cadence"
        return None

    def observe(self, frame_bgr, boxes: list[DetectionBox], pose: Optional[Vec3],
                t: float, *, source: str, image_w: int, image_h: int) -> bool:
        if not self._enabled:
            return False
        try:
            reason = self._reason(boxes, t)
            if reason is None:
                return False
            if self._bytes >= self._max_bytes:
                if not self._budget_warned:
                    print(f"[capture] max_mb reached ({self._max_bytes} B); pausing frame writes")
                    self._budget_warned = True
                return False

            frames_dir = self._dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            rel = f"frames/{self._seq:06d}.jpg"
            ok, buf = cv2.imencode(".jpg", frame_bgr)
            if not ok:
                return False
            (self._dir / rel).write_bytes(buf.tobytes())
            self._bytes += len(buf)

            obs = Observation(
                t=t, mission_id=self._mission_id, frame_path=rel, source=source,
                image_w=image_w, image_h=image_h, pose=pose,
                detections=[
                    Detection(label=b.label, conf=b.confidence,
                              box=[b.cx, b.cy, b.w, b.h]) for b in boxes
                ],
                sampled_reason=reason,
            )
            with (self._dir / "observations.jsonl").open("a") as fh:
                fh.write(json.dumps(obs.model_dump(mode="json")) + "\n")

            self._seq += 1
            self._last_save_t = t
            for b in boxes:
                self._seen_classes.add(b.label)
            return True
        except Exception as exc:  # noqa: BLE001 - capture is best-effort, never fatal
            print(f"[capture] observe failed (ignored): {exc!r}")
            return False

    def record_event(self, event: Event) -> None:
        if not self._enabled:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with (self._dir / "events.jsonl").open("a") as fh:
                fh.write(json.dumps(event.model_dump(mode="json")) + "\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[capture] record_event failed (ignored): {exc!r}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_recorder.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/capture/recorder.py backend/tests/test_capture_recorder.py
git commit -m "feat(capture): best-effort opt-in CaptureRecorder with sampling"
```

---

## Task 3: Wire the recorder into the perception pipeline + server

**Files:**
- Modify: `backend/app/perception/pipeline.py` (constructor + `_run` tick)
- Modify: `backend/app/server.py` (construct recorder when `CAPTURE_ENABLED`)
- Test: `backend/tests/test_capture_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_capture_pipeline.py
import numpy as np

from app.contracts import DetectionBox, Vec3


class _SpyRecorder:
    def __init__(self):
        self.calls = []

    def observe(self, frame, boxes, pose, t, *, source, image_w, image_h):
        self.calls.append((boxes, pose, t, source, image_w, image_h))
        return True


def test_pipeline_emit_capture_calls_recorder():
    # The pipeline exposes a small helper that forwards the latest frame+boxes to
    # the recorder; verify it maps args correctly and is a no-op without a recorder.
    from app.perception.pipeline import PerceptionPipeline

    spy = _SpyRecorder()
    boxes = [DetectionBox(label="car", confidence=0.3, cx=0.5, cy=0.5, w=0.1, h=0.1)]
    frame = np.zeros((48, 64, 3), dtype=np.uint8)

    PerceptionPipeline._emit_capture(
        spy, frame, boxes, Vec3(x=1.0, y=2.0, z=3.0), 5.0, "leader",
    )
    assert len(spy.calls) == 1
    _boxes, pose, t, source, w, h = spy.calls[0]
    assert source == "leader" and t == 5.0 and w == 64 and h == 48
    assert pose.x == 1.0

    # No recorder -> no error, no call.
    PerceptionPipeline._emit_capture(None, frame, boxes, None, 5.0, "leader")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_pipeline.py -v`
Expected: FAIL — `PerceptionPipeline` has no attribute `_emit_capture`.

- [ ] **Step 3: Add the recorder seam to the pipeline**

In `backend/app/perception/pipeline.py`:

(a) Add `recorder=None` to `PerceptionPipeline.__init__` parameters and store it: `self._recorder = recorder`. (Place the param at the end of the signature so existing positional calls are unaffected.)

(b) Add this static helper to the class (it isolates the mapping so it's unit-testable without running the loop):

```python
    @staticmethod
    def _emit_capture(recorder, frame_bgr, boxes, pose, t, source):
        """Forward the latest frame + normalized boxes to the capture recorder
        (best-effort; no-op when capture is disabled / recorder is None)."""
        if recorder is None or frame_bgr is None:
            return
        h, w = frame_bgr.shape[:2]
        recorder.observe(frame_bgr, boxes, pose, t, source=source,
                         image_w=int(w), image_h=int(h))
```

(c) In `_run`, immediately AFTER `self._latest_boxes = [...]` is assigned (the block ending ~line 345), add:

```python
                            cap_pose = None
                            if current_pose is not None:
                                p = current_pose.position
                                cap_pose = Vec3(x=float(p[0]), y=float(p[1]), z=float(p[2]))
                            self._emit_capture(
                                self._recorder, frame_bgr, self._latest_boxes,
                                cap_pose, now, "leader",
                            )
```

Ensure `Vec3` is imported in `pipeline.py` (it is used via contracts; if not already imported, add `from ..contracts import Vec3` — check the existing imports first and only add if missing).

- [ ] **Step 4: Construct the recorder in `server.py`**

In `backend/app/server.py`, near where `PerceptionPipeline(...)` is constructed (~line 293), add above it:

```python
_capture_recorder = None
if os.environ.get("CAPTURE_ENABLED") == "1":
    from .capture.recorder import CaptureRecorder  # noqa: PLC0415
    _capture_recorder = CaptureRecorder(
        root=Path(__file__).resolve().parent.parent.parent / "captures",
        mission_id=os.environ.get("CAPTURE_MISSION_ID", "mission"),
        max_mb=float(os.environ.get("CAPTURE_MAX_MB", "2000")),
        cadence_s=float(os.environ.get("CAPTURE_CADENCE_S", "2.0")),
        low_conf=float(os.environ.get("CAPTURE_LOW_CONF", "0.4")),
        enabled=True,
    )
```

Then pass `recorder=_capture_recorder` into the `PerceptionPipeline(...)` constructor call. Confirm `Path` and `os` are already imported in `server.py` (they are).

- [ ] **Step 5: Run tests + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_pipeline.py -v && .venv/bin/python -m pytest -q`
Expected: new test passes; full suite green (no regressions — capture defaults off).

- [ ] **Step 6: Commit**

```bash
git add backend/app/perception/pipeline.py backend/app/server.py backend/tests/test_capture_pipeline.py
git commit -m "feat(capture): wire recorder into perception loop (opt-in)"
```

---

## Task 4: LabelEvent wire message + server recording

**Files:**
- Modify: `backend/app/contracts.py` (add `LabelEvent`, extend `ClientMessage` + `parse_client_message`)
- Modify: `backend/app/server.py` (record `LabelEvent` in `ws_endpoint`)
- Test: `backend/tests/test_label_event.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_label_event.py
import asyncio
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
    # Exercise the handler's recording branch directly.
    server._record_label_event(LabelEvent(kind="reject", source="follower",
                                          label="debris", t=2.0))
    ev = (tmp_path / "m1" / "events.jsonl").read_text().splitlines()[0]
    assert json.loads(ev)["kind"] == "reject"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_label_event.py -v`
Expected: FAIL — `ImportError: cannot import name 'LabelEvent'`.

- [ ] **Step 3: Add `LabelEvent` to contracts**

In `backend/app/contracts.py`, add after the `EntityReport` class:

```python
class LabelEvent(BaseModel):
    """Operator label decision on a detection / follow target, recorded for the
    data flywheel (confirm a true positive, reject a false positive, or correct
    the class). Box (if given) is [cx, cy, w, h] normalized 0..1."""
    type: Literal["label_event"] = "label_event"
    kind: Literal["confirm", "reject", "correct"]
    source: str
    label: Optional[str] = None
    corrected_label: Optional[str] = None
    box: Optional[list[float]] = None
    note: Optional[str] = None
    t: float
```

Extend the union (append `, LabelEvent`):

```python
ClientMessage = Union[IntentMessage, DeviceLocation, FollowState, EntityReport, LabelEvent]
```

Add a branch in `parse_client_message`, before the final `raise`:

```python
    if kind == "label_event":
        return LabelEvent.model_validate(raw)
```

(`Optional`, `Literal`, `Union`, `Field`, `BaseModel` are already imported.)

- [ ] **Step 4: Record it in the server**

In `backend/app/server.py`:

(a) Add `LabelEvent` to the `from .contracts import (...)` block.

(b) Add a module-level helper near `_apply_entity_report`:

```python
def _record_label_event(msg: LabelEvent) -> None:
    """Persist an operator label decision for the data flywheel (no-op when
    capture is disabled)."""
    if _capture_recorder is None:
        return
    from .capture.schema import Event  # noqa: PLC0415
    _capture_recorder.record_event(Event(
        t=msg.t, mission_id=getattr(_capture_recorder, "_mission_id", "mission"),
        kind=msg.kind, source=msg.source, label=msg.label,
        corrected_label=msg.corrected_label, box=msg.box, note=msg.note,
    ))
```

(c) In `ws_endpoint`, add a dispatch branch alongside the others:

```python
            elif isinstance(msg, LabelEvent):
                _record_label_event(msg)
```

- [ ] **Step 5: Run tests + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_label_event.py -v && .venv/bin/python -m pytest -q`
Expected: 3 passed; full suite green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts.py backend/app/server.py backend/tests/test_label_event.py
git commit -m "feat(capture): LabelEvent wire message recorded for the flywheel"
```

---

## Task 5: Cleaning module + CLI

**Files:**
- Create: `backend/app/capture/cleaning.py`
- Create: `scripts/clean_captures.py`
- Test: `backend/tests/test_capture_cleaning.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_capture_cleaning.py
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
    # f0: good, distinctive content, one valid + one degenerate box
    _write_frame(mdir / "frames/000000.jpg", 60, noise=True)
    # f1: near-duplicate of f0 (same content) -> dropped as duplicate
    _write_frame(mdir / "frames/000001.jpg", 60, noise=True)
    # f2: blank/near-uniform -> dropped as corrupt/blank
    _write_frame(mdir / "frames/000002.jpg", 10, noise=False)

    lines = [
        _obs_line("frames/000000.jpg",
                  [{"label": "car", "conf": 0.9, "box": [0.5, 0.5, 0.2, 0.2]},
                   {"label": "x", "conf": 0.9, "box": [0.5, 0.5, 0.0, 0.2]}], 1.0),
        _obs_line("frames/000001.jpg",
                  [{"label": "car", "conf": 0.9, "box": [0.4, 0.4, 0.2, 0.2]}], 1.2),
        _obs_line("frames/000002.jpg",
                  [{"label": "car", "conf": 0.9, "box": [0.5, 0.5, 0.2, 0.2]}], 1.4),
        "{ this is not valid json",  # unparseable -> records_invalid
    ]
    (mdir / "observations.jsonl").write_text("\n".join(lines) + "\n")

    report = clean_mission(mdir, dup_threshold=5, conf_floor=0.1, blank_std=12.0)

    kept = [json.loads(l) for l in
            (mdir / "cleaned/observations.jsonl").read_text().splitlines()]
    assert len(kept) == 1                       # f0 only
    assert kept[0]["frame_path"] == "frames/000000.jpg"
    assert len(kept[0]["detections"]) == 1      # degenerate box dropped
    assert report["frames_in"] == 3
    assert report["dropped_duplicate"] == 1
    assert report["dropped_corrupt"] == 1
    assert report["frames_out"] == 1
    assert report["boxes_dropped"] == 1
    assert report["records_invalid"] == 1
    assert json.loads((mdir / "cleaned/cleaning_report.json").read_text())["frames_out"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_cleaning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.capture.cleaning'`.

- [ ] **Step 3: Implement cleaning**

```python
# backend/app/capture/cleaning.py
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
        cx, cy, w, h = (box + [0, 0, 0, 0])[:4]
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_cleaning.py -v`
Expected: 2 passed.

- [ ] **Step 5: Add the CLI**

Create `scripts/clean_captures.py`:

```python
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
    args = ap.parse_args()

    report = clean_mission(args.root / args.mission,
                           dup_threshold=args.dup_threshold, conf_floor=args.conf_floor)
    print(f"[clean] {json.dumps(report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Verify it parses: `cd /Users/nicolasdossantos/recon-companion/.claude/worktrees/autonomous-approach && python3 scripts/clean_captures.py --help` prints usage.

- [ ] **Step 6: Commit**

```bash
git add backend/app/capture/cleaning.py scripts/clean_captures.py backend/tests/test_capture_cleaning.py
git commit -m "feat(capture): cleaning rules (blank/dup/degenerate) + CLI"
```

---

## Task 6: Packaging module + CLI

**Files:**
- Create: `backend/app/capture/packaging.py`
- Create: `scripts/package_dataset.py`
- Test: `backend/tests/test_capture_packaging.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_capture_packaging.py
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
    # one correct event reclassifies a 'person' box to 'soldier'
    (mdir / "events.jsonl").write_text(json.dumps({
        "v": 1, "t": 0.0, "mission_id": "m1", "kind": "correct", "source": "leader",
        "label": "person", "corrected_label": "soldier", "box": [0.5, 0.5, 0.2, 0.2],
    }) + "\n")
    return mdir


def test_package_builds_yolo_gemma_manifest(tmp_path: Path):
    mdir = _setup_cleaned(tmp_path)
    out = tmp_path / "datasets" / "d1"
    manifest = package_dataset(mdir, out, val_frac=0.25, created_t=123.0)

    # YOLO structure
    assert (out / "yolo" / "data.yaml").exists()
    train_lbls = list((out / "yolo" / "labels" / "train").glob("*.txt"))
    val_lbls = list((out / "yolo" / "labels" / "val").glob("*.txt"))
    assert len(train_lbls) + len(val_lbls) == 4
    # a label file: "class_id cx cy w h"
    sample = (train_lbls + val_lbls)[0].read_text().strip().split("\n")[0].split()
    assert len(sample) == 5 and all(_is_num(x) for x in sample)
    # 'soldier' must appear as a class because of the correct-event reclassification
    names = manifest["yolo"]["classes"]
    assert "soldier" in names

    # Gemma examples
    gemma = [json.loads(l) for l in
             (out / "gemma" / "examples.jsonl").read_text().splitlines()]
    assert len(gemma) == 4
    assert {"frame_path", "context", "prompt", "gold_answer", "labeled"} <= set(gemma[0])

    # Manifest
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


def _is_num(s):
    try:
        float(s); return True
    except ValueError:
        return False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_packaging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.capture.packaging'`.

- [ ] **Step 3: Implement packaging**

```python
# backend/app/capture/packaging.py
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
    exists; None if no correction. A matching 'reject' returns the sentinel ''."""
    for ev in events:
        if ev.get("label") != label:
            continue
        if ev["kind"] == "correct" and ev.get("corrected_label"):
            return ev["corrected_label"]
        if ev["kind"] == "reject":
            return ""   # sentinel: drop this box
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

    # First pass: resolve effective labels per detection + collect class set.
    resolved: list[tuple[dict, list[tuple[str, list[float]]]]] = []
    classes: set[str] = set()
    for rec in obs:
        kept = []
        for d in rec.get("detections", []):
            corr = _correction_for(events, d["label"], d.get("box"))
            if corr == "":          # rejected
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_packaging.py -v`
Expected: 2 passed.

- [ ] **Step 5: Add the CLI**

Create `scripts/package_dataset.py`:

```python
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
```

Verify: `cd /Users/nicolasdossantos/recon-companion/.claude/worktrees/autonomous-approach && python3 scripts/package_dataset.py --help` prints usage.

- [ ] **Step 6: Commit**

```bash
git add backend/app/capture/packaging.py scripts/package_dataset.py backend/tests/test_capture_packaging.py
git commit -m "feat(capture): package cleaned data into YOLO+Gemma dataset + manifest"
```

---

## Task 7: Mirror LabelEvent in shared TS contracts

**Files:**
- Modify: `shared/contracts.ts`

- [ ] **Step 1: Add the interface + extend the client union**

After the `EntityReport`/client-message section, add:

```ts
/**
 * Operator label decision recorded for the data flywheel: confirm a true
 * positive, reject a false positive, or correct the class. box (if present)
 * is [cx, cy, w, h] normalized 0..1.
 */
export interface LabelEvent {
  type: "label_event";
  kind: "confirm" | "reject" | "correct";
  source: string;
  label?: string;
  corrected_label?: string;
  box?: number[];
  note?: string;
  t: number;
}
```

Find the `ClientMessage` union and append `| LabelEvent` as a member.

- [ ] **Step 2: Verify the frontend type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors (additive change).

- [ ] **Step 3: Commit**

```bash
git add shared/contracts.ts
git commit -m "feat(contracts): mirror LabelEvent in shared TS contracts"
```

---

## Task 8: Mobile LabelEvent emit on operator confirm

**Files:**
- Modify: `mobile/Sources/Contracts.swift` (add `LabelEventMessage` encodable)
- Modify: `mobile/Sources/WorldClient.swift` (add `sendLabelEvent`)
- Modify: `mobile/Sources/FollowCoordinator.swift` (emit on `confirmTarget()`)
- Test: `mobile/Tests/ContractsTests.swift` (encode shape)

- [ ] **Step 1: Add the encode test**

Append inside the `ContractsTests` class in `mobile/Tests/ContractsTests.swift`:

```swift
func testLabelEventEncodesWithWireShape() throws {
    let msg = LabelEventMessage(kind: "confirm", source: "follower",
                               label: "person", correctedLabel: nil, box: nil,
                               note: nil, t: 9.0)
    let data = try JSONEncoder().encode(msg)
    let obj = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    XCTAssertEqual(obj["type"] as? String, "label_event")
    XCTAssertEqual(obj["kind"] as? String, "confirm")
    XCTAssertEqual(obj["source"] as? String, "follower")
    XCTAssertEqual(obj["label"] as? String, "person")
}
```

- [ ] **Step 2: Add the encodable struct**

In `mobile/Sources/Contracts.swift`, near `EntityReportMessage`, add:

```swift
struct LabelEventMessage: Encodable, Sendable {
    let type = "label_event"
    let kind: String
    let source: String
    let label: String?
    let correctedLabel: String?
    let box: [Double]?
    let note: String?
    let t: Double

    enum CodingKeys: String, CodingKey {
        case type, kind, source, label
        case correctedLabel = "corrected_label"
        case box, note, t
    }
}
```

- [ ] **Step 3: Add `sendLabelEvent` to WorldClient**

In `mobile/Sources/WorldClient.swift`, add this method next to `sendEntityReport(_:)`. It mirrors that method exactly (the file uses a `task`, an `encoder`, and `task.send(.string(json))`):

```swift
/// Record an operator label decision for the data flywheel. Best-effort,
/// fire-and-forget — drops silently if the socket isn't up.
func sendLabelEvent(kind: String, source: String, label: String? = nil,
                    correctedLabel: String? = nil, box: [Double]? = nil,
                    note: String? = nil) {
    guard let task else { return }
    let msg = LabelEventMessage(kind: kind, source: source, label: label,
                               correctedLabel: correctedLabel, box: box, note: note,
                               t: Date().timeIntervalSince1970)
    guard let data = try? encoder.encode(msg), let json = String(data: data, encoding: .utf8) else {
        return
    }
    task.send(.string(json)) { _ in }
}
```

- [ ] **Step 4: Emit on operator confirm**

In `mobile/Sources/FollowCoordinator.swift`, the coordinator does not hold a `WorldClient`. Add an optional closure so the owner wires emission without coupling:

```swift
/// Optional sink for operator label decisions (data flywheel). Wired by the app
/// to WorldClient.sendLabelEvent; nil in tests.
var onLabel: ((_ kind: String, _ label: String?) -> Void)?
```

In `confirmTarget()` (where `self.confirmed = true` is set), add:

```swift
onLabel?("confirm", nil)   // the follow target is a tracked tag/object; class is not known here
```

(Pass `nil` for the label — the follow target is an AprilTag/visually-tracked object without a class string. The confirm still records as a true-positive signal.) Then, where the app constructs the `FollowCoordinator` and has the `WorldClient`, wire:

```swift
coordinator.onLabel = { kind, label in
    worldClient.sendLabelEvent(kind: kind, source: "follower", label: label)
}
```

Read `FollowCoordinator.swift` + its construction site first; if a class label for the locked target genuinely isn't available, pass `nil` rather than inventing one.

- [ ] **Step 5: Build + run mobile tests**

Run from `mobile/`:
```bash
cd mobile && xcodegen generate && AP="$(pwd)/Vendor/apriltag" && \
xcodebuild test -scheme ReconCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  SWIFT_ENABLE_EXPLICIT_MODULES=NO \
  "OTHER_SWIFT_FLAGS=-Xcc -I$AP" "HEADER_SEARCH_PATHS=$AP" 2>&1 | tail -20
```
(If `iPhone 17` isn't available, `xcrun simctl list devices available | grep iPhone` and substitute.)
Expected: `** TEST SUCCEEDED **`, including `testLabelEventEncodesWithWireShape`.

- [ ] **Step 6: Commit**

```bash
git add mobile/Sources/Contracts.swift mobile/Sources/WorldClient.swift mobile/Sources/FollowCoordinator.swift mobile/Tests/ContractsTests.swift
git commit -m "feat(mobile): emit LabelEvent on operator target confirm"
```

---

## Final verification

- [ ] Backend full suite: `cd backend && .venv/bin/python -m pytest -q` — all pass.
- [ ] Frontend typecheck: `cd frontend && npx tsc --noEmit` — clean.
- [ ] Mobile: `** TEST SUCCEEDED **`.
- [ ] End-to-end smoke (no network): with `CAPTURE_ENABLED=1 CAPTURE_MISSION_ID=test` run a short clip through the perception pipeline (or unit-drive the recorder), then `python3 scripts/clean_captures.py --mission test` and `python3 scripts/package_dataset.py --mission test --out datasets/test`; confirm `datasets/test/{yolo/data.yaml, gemma/examples.jsonl, manifest.json}` exist and `manifest.json` reports sane counts.
- [ ] Final whole-feature code review before finishing the branch.
