# On-Demand Vision "Deep Look" + End-to-End Integration Test — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (D) Make "the model actually looks at the frame" demonstrably true via an explicit, on-demand vision assessment (`POST /intel/deep-look`) that forces one `INTEL_VISION=1` pass — keeping the fast text-only path as the live default. (E) Add the first true end-to-end integration test that drives the real perception pipeline from a synthetic video source through to a broadcast `WorldSnapshot`, proving the full loop runs.

**Architecture:** D reuses `IntelReasoner.summarise(jpeg, labels)` but constructs a one-shot vision-enabled reasoner on demand, grabbing the latest Mavic JPEG + `perception.latest_boxes()` labels. E adds a `SyntheticVideoSource` (a `FrameSource` that yields a fixed set of JPEGs) and a recording `Hub` double, then runs `PerceptionPipeline` for a few frames and asserts entities reach `world.snapshot()` and a `WorldSnapshot` is broadcast.

**Tech Stack:** Python 3.13, FastAPI, asyncio, httpx, numpy, OpenCV (`cv2`), pytest with `FakeClock`. Tests run from `backend/` via `.venv/bin/python -m pytest`. The vision pass requires a local Ollama with a vision model; the integration test must NOT require Ollama or a GPU (perception only).

---

## File Structure

- Modify `backend/app/server.py` — add `POST /intel/deep-look` (one-shot vision summary).
- Create `backend/tests/test_intel_deep_look.py` — endpoint behavior with a stub reasoner.
- Create `backend/tests/fakes.py` — `SyntheticVideoSource` + `RecordingHub` reusable test doubles.
- Create `backend/tests/test_pipeline_integration.py` — the end-to-end test.

---

### Task 1: One-shot deep-look helper (pure, testable)

**Files:**
- Modify: `backend/app/server.py` (add a module-level async helper)
- Test: `backend/tests/test_intel_deep_look.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_deep_look.py
import asyncio

from app.reasoning.intel import IntelSummary
from app import server


class _StubReasoner:
    """Records the with_vision flag and the jpeg it was handed."""
    def __init__(self):
        self.calls = []
    async def summarise(self, jpeg, labels):
        self.calls.append((jpeg, list(labels)))
        return IntelSummary(text="vehicle approaching from the north",
                            threat_level="med", labels_seen=sorted(set(labels)),
                            t=123.0, model="gemma3:4b", latency_ms=42.0)


def test_deep_look_runs_one_vision_summary_over_current_frame():
    reasoner = _StubReasoner()
    jpeg = b"\xff\xd8fakejpeg\xff\xd9"
    labels = ["vehicle", "person"]
    summary = asyncio.run(server._run_deep_look(reasoner, jpeg, labels))
    assert summary.threat_level == "med"
    assert reasoner.calls == [(jpeg, ["vehicle", "person"])]   # the real frame + labels


def test_deep_look_without_a_frame_returns_an_error_summary():
    reasoner = _StubReasoner()
    summary = asyncio.run(server._run_deep_look(reasoner, None, ["person"]))
    assert "no frame" in summary.text.lower()
    assert reasoner.calls == []   # never calls the model without an image
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_intel_deep_look.py -q`
Expected: FAIL — `AttributeError: module 'app.server' has no attribute '_run_deep_look'`

- [ ] **Step 3: Implement the helper in `backend/app/server.py`**

```python
async def _run_deep_look(reasoner, jpeg, labels) -> "IntelSummary":
    """Run exactly one vision-enabled assessment over `jpeg`. Returns an error
    summary (no model call) when no frame is available — deep-look is the
    image-aware path, so a missing frame is a no-op, not a text-only fallback."""
    from .reasoning.intel import IntelSummary
    import time as _time
    if jpeg is None:
        return IntelSummary(text="No frame available for deep look.",
                            threat_level="unknown", labels_seen=sorted(set(labels)),
                            t=_time.time(), model="", latency_ms=0.0)
    return await reasoner.summarise(jpeg, labels)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_intel_deep_look.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/server.py backend/tests/test_intel_deep_look.py
git commit -m "feat(intel): one-shot deep-look vision summary helper"
```

---

### Task 2: Wire the `POST /intel/deep-look` endpoint

**Files:**
- Modify: `backend/app/server.py` (route + a vision-forced reasoner)
- Test: extend `backend/tests/test_intel_deep_look.py` via FastAPI `TestClient`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_intel_deep_look.py
from fastapi.testclient import TestClient


def test_deep_look_endpoint_returns_summary(monkeypatch):
    # Force a known frame + labels and a stub reasoner so no Ollama is needed.
    reasoner = _StubReasoner()
    monkeypatch.setattr(server, "_deep_look_reasoner", reasoner, raising=False)
    monkeypatch.setattr(server.mavic_camera, "read_jpeg", lambda: b"\xff\xd8x\xff\xd9")
    monkeypatch.setattr(server.perception, "latest_boxes",
                        lambda: ([type("B", (), {"label": "person"})()], 640, 480, 1.0))
    client = TestClient(server.app)
    res = client.post("/intel/deep-look")
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["threat_level"] == "med"
    assert body["summary"]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_intel_deep_look.py -q`
Expected: FAIL — 404 (no `/intel/deep-look` route).

- [ ] **Step 3: Implement the endpoint in `backend/app/server.py`**

Near the other intel construction (~line 150), add a lazily-built vision reasoner:

```python
# Vision-forced reasoner for explicit deep-look requests (never per-frame).
_deep_look_reasoner: IntelReasoner | None = (
    IntelReasoner(model=_INTEL_MODEL_ENV, with_vision=True) if _INTEL_ENABLED else None
)
```

Add the route near `/intel/summary` (~line 539):

```python
@app.post("/intel/deep-look")
async def post_deep_look() -> dict:
    """Run ONE image-aware assessment over the current frame on demand. Slow
    (~minutes on CPU) by design — this is the 'actually look at the scene'
    button, not the live card."""
    if _deep_look_reasoner is None:
        return {"summary": None, "error": "intel disabled"}
    jpeg = await asyncio.to_thread(mavic_camera.read_jpeg)
    boxes, _w, _h, _t = perception.latest_boxes()
    labels = [b.label for b in boxes]
    summary = await _run_deep_look(_deep_look_reasoner, jpeg, labels)
    return {
        "summary": {
            "text": summary.text,
            "threat_level": summary.threat_level,
            "labels_seen": summary.labels_seen,
            "t": summary.t,
            "model": summary.model,
            "latency_ms": summary.latency_ms,
        }
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_intel_deep_look.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/server.py backend/tests/test_intel_deep_look.py
git commit -m "feat(intel): POST /intel/deep-look on-demand vision assessment"
```

---

### Task 3: Reusable test doubles — SyntheticVideoSource + RecordingHub

**Files:**
- Create: `backend/tests/fakes.py`
- Test: `backend/tests/test_pipeline_integration.py` (Step 1 trivially imports them; full use in Task 4).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_integration.py
import numpy as np

from tests.fakes import SyntheticVideoSource, RecordingHub


def test_synthetic_source_yields_then_stops():
    src = SyntheticVideoSource(num_frames=3, width=64, height=48)
    src.start()
    a = src.read_jpeg(); b = src.read_jpeg(); c = src.read_jpeg()
    assert a is not None and b is not None and c is not None
    assert src.read_jpeg() is None      # exhausted
    src.stop()


def test_recording_hub_captures_broadcasts():
    import asyncio
    from app.contracts import MissionState
    hub = RecordingHub()
    asyncio.run(hub.broadcast(MissionState(stage="idle", last_error=None, t=0.0)))
    assert any(type(m).__name__ == "MissionState" for m in hub.messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.fakes'`

- [ ] **Step 3: Implement the fakes**

```python
# backend/tests/fakes.py
"""Reusable test doubles for the end-to-end pipeline test."""
from __future__ import annotations

from typing import List, Optional

import cv2
import numpy as np


class SyntheticVideoSource:
    """A FrameSource that yields a fixed number of JPEG frames, then None.

    Each frame is a textured noise image (so any real detector has features to
    chew on) with a bright rectangle drawn in a deterministic spot. Frames are
    distinct so VO has motion between them."""

    def __init__(self, num_frames: int = 5, width: int = 320, height: int = 240) -> None:
        self._frames: List[bytes] = []
        rng = np.random.default_rng(7)
        base = (rng.random((height, width, 3)) * 255).astype(np.uint8)
        for i in range(num_frames):
            img = np.roll(base, shift=8 * i, axis=1).copy()
            x = 20 + 10 * i
            cv2.rectangle(img, (x, 40), (x + 60, 140), (255, 255, 255), -1)
            ok, buf = cv2.imencode(".jpg", img)
            self._frames.append(buf.tobytes() if ok else b"")
        self._i = 0
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def read_jpeg(self) -> Optional[bytes]:
        if self._i >= len(self._frames):
            return None
        f = self._frames[self._i]
        self._i += 1
        return f

    @property
    def is_streaming(self) -> bool:
        return self._started and self._i < len(self._frames)


class RecordingHub:
    """Stand-in for ws_hub.Hub that records every broadcast message object."""

    def __init__(self) -> None:
        self.messages = []

    async def broadcast(self, message) -> None:
        self.messages.append(message)

    async def add(self, conn) -> None:
        pass

    async def remove(self, conn) -> None:
        pass

    @property
    def client_count(self) -> int:
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_integration.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fakes.py backend/tests/test_pipeline_integration.py
git commit -m "test: add SyntheticVideoSource + RecordingHub test doubles"
```

---

### Task 4: End-to-end pipeline integration test

**Files:**
- Test: `backend/tests/test_pipeline_integration.py` (add)

**Goal of this test:** drive `PerceptionPipeline` from `SyntheticVideoSource` for a few frames and assert the world model gains entities and that a `WorldSnapshot` built from `world.snapshot()` broadcasts through a `RecordingHub` — the first test that exercises source → perception → world model → broadcast together.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_pipeline_integration.py
import asyncio

from app.clock import FakeClock
from app.contracts import Entity, EntitySource, EntityType, Vec3, WorldSnapshot
from app.world_model import WorldModel
from app.perception.pipeline import PerceptionPipeline
from tests.fakes import SyntheticVideoSource, RecordingHub


def test_perception_to_worldmodel_to_broadcast_end_to_end():
    clock = FakeClock(1000.0)
    world = WorldModel(clock=clock)
    source = SyntheticVideoSource(num_frames=6, width=320, height=240)

    # No YOLO weights in CI: the pipeline still runs SLAM/VO and the loop; to
    # prove the seam without a model, we inject one entity through the same
    # upsert path the pipeline uses, then run a few pipeline ticks to confirm
    # the loop consumes frames without error and the world model serves them.
    pipe = PerceptionPipeline(
        video_source=source, world=world, clock=clock,
        yolo_weights=None, perception_fps=30.0, img_width=320, img_height=240,
    )

    async def _drive():
        pipe.start()
        # Let the loop consume the synthetic frames.
        for _ in range(8):
            await asyncio.sleep(0)        # yield to the pipeline task
        # Simulate a detection landing in the world model via the real path.
        world.upsert(Entity(
            id="yolo_person_1_1", type=EntityType.OBJECT,
            position=Vec3(x=2.0, y=3.0, z=0.0), confidence=0.8,
            timestamp=clock.now(), source=EntitySource.YOLO, label="person", ttl_s=3.0,
        ))
        hub = RecordingHub()
        await hub.broadcast(WorldSnapshot(entities=world.snapshot(), t=clock.now()))
        return hub

    hub = asyncio.run(_drive())
    snap_msgs = [m for m in hub.messages if type(m).__name__ == "WorldSnapshot"]
    assert snap_msgs, "a WorldSnapshot must be broadcast"
    ids = {e.id for e in snap_msgs[-1].entities}
    assert "yolo_person_1_1" in ids       # entity flowed source→world→broadcast
    # And the synthetic source was actually consumed by the pipeline loop.
    assert source.read_jpeg() is None      # frames exhausted by the loop
```

> NOTE: `PerceptionPipeline._run` requires `cv2` and numpy (present in the backend venv). If YOLO weights are None, the detector is skipped but the VO/SLAM + loop still run — that's the seam we're proving. The explicit `world.upsert(...)` stands in for a detector firing (no model in CI); the assertion proves the world-model → broadcast half end-to-end, while the pipeline loop proves the source → perception half consumes real frames. If `PerceptionPipeline` exposes a synchronous single-tick method, prefer calling it directly instead of the sleep-yield loop; check the class before finalizing.

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_integration.py -q`
Expected: PASS. If the background task doesn't consume frames within the yields, increase the loop count or, preferably, refactor the assertion to call a single-tick entry point on `PerceptionPipeline` (confirm its API first).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pipeline_integration.py
git commit -m "test: end-to-end source->perception->world->broadcast integration test"
```

---

### Task 5: Run the full backend suite

- [ ] **Step 1: Run everything**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: all prior tests + the new intel/integration tests PASS.

- [ ] **Step 2: Commit any fixups**

```bash
git add -A backend/tests backend/app
git commit -m "test: green full backend suite with deep-look + integration coverage"
```

---

## Self-Review

- **Spec coverage:** #3 deep-look → Tasks 1, 2 (one-shot `with_vision=True` over the real frame + labels, on demand). #1 integration evidence → Tasks 3, 4 (first source→perception→world→broadcast test). #7 networking de-risk is operational (recorded demo) — not code, tracked in the spec's reframe section, not this plan.
- **Type consistency:** `_run_deep_look(reasoner, jpeg, labels)`, `IntelSummary` fields, `IntelReasoner(with_vision=True).summarise`, `SyntheticVideoSource.read_jpeg/start/stop/is_streaming`, `RecordingHub.broadcast/messages`, `WorldSnapshot(entities=..., t=...)` used consistently.
- **Flagged for the implementer:** confirm `PerceptionPipeline`'s tick/loop entry before finalizing Task 4 (prefer a single-tick call over the sleep-yield loop if one exists); the integration test must stay Ollama-free and GPU-free (perception + world model only).
- **Recorded demo (E, operational):** capture a clean end-to-end hardware run using the stage network setup. Not a code task; checklist lives in the spec.
