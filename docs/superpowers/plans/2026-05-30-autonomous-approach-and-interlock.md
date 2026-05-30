# Autonomous Approach + Arming Interlock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a software arming interlock (one laptop controller may command the Tello at a time) and an autonomous "approach-and-standoff to a detected target" flight behavior that reuses the existing FollowController visual-servo path and plots on the dashboard map.

**Architecture:** A shared `ArmingLock` gates every laptop-side flight command. A new `ApproachController` mirrors `FollowController` — same PD gains, same `send_rc` drive path, same world-model entity emission — but its target is a YOLO-detected object in the Tello's own camera frame (via a `TargetDetector` protocol so tests inject synthetic readings) instead of an AprilTag. A new `APPROACH` mission stage and `Command.APPROACH` route it over the existing WS/mission machinery. AprilTag follow-me stays untouched; the two are mutually-exclusive laptop modes arbitrated by the lock.

**Tech Stack:** Python 3.13, FastAPI, asyncio, numpy, pydantic; pytest with `FakeClock`. Tests run from `backend/` via `.venv/bin/python -m pytest`.

---

## File Structure

- Create `backend/app/follow/arming.py` — `ArmingLock` (exclusive owner token).
- Create `backend/app/follow/target.py` — `TargetReading` dataclass + `TargetDetector` protocol + `SyntheticTargetDetector` (test double) + a thin real detector adapter.
- Create `backend/app/follow/approach.py` — `ApproachController` (state machine + PD + entity emission).
- Modify `backend/app/follow/controller.py` — make `FollowController` consult the `ArmingLock` before driving.
- Modify `backend/app/contracts.py` — add `Command.APPROACH`.
- Modify `backend/app/state_machine.py` — add `Stage.APPROACH` + transitions.
- Modify `backend/app/server.py` — construct the lock + approach controller, route the new command.
- Create `backend/tests/test_arming.py`, `backend/tests/test_approach.py`.

---

### Task 1: ArmingLock — exclusive command token

**Files:**
- Create: `backend/app/follow/arming.py`
- Test: `backend/tests/test_arming.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_arming.py
from app.follow.arming import ArmingLock


def test_unowned_lock_denies_all():
    lock = ArmingLock()
    assert lock.holder is None
    assert lock.can_command("follow") is False
    assert lock.can_command("approach") is False


def test_acquire_grants_exclusive_command_rights():
    lock = ArmingLock()
    assert lock.acquire("follow") is True
    assert lock.holder == "follow"
    assert lock.can_command("follow") is True
    assert lock.can_command("approach") is False


def test_acquire_is_rejected_while_held_by_another():
    lock = ArmingLock()
    assert lock.acquire("follow") is True
    assert lock.acquire("approach") is False
    assert lock.holder == "follow"


def test_reacquire_by_same_owner_is_idempotent():
    lock = ArmingLock()
    assert lock.acquire("follow") is True
    assert lock.acquire("follow") is True
    assert lock.holder == "follow"


def test_release_clears_only_for_holder():
    lock = ArmingLock()
    lock.acquire("follow")
    assert lock.release("approach") is False   # not the holder
    assert lock.holder == "follow"
    assert lock.release("follow") is True
    assert lock.holder is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_arming.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.follow.arming'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/follow/arming.py
"""Software arming interlock for the Tello.

Only one laptop-side controller (follow OR approach) may command the drone at a
time. Every controller must hold the lock before it drives the Tello; the lock
is exclusive. This is the code interlock that was previously only an operating
rule. (The phone commands the Tello directly over its own AP and is represented
here as the owner "phone" — arming "phone" disarms every laptop controller.)
"""
from __future__ import annotations

import threading
from typing import Optional


class ArmingLock:
    def __init__(self) -> None:
        self._holder: Optional[str] = None
        self._mu = threading.Lock()

    @property
    def holder(self) -> Optional[str]:
        return self._holder

    def acquire(self, owner: str) -> bool:
        """Grant the lock to `owner`. Idempotent for the current holder;
        rejected when another owner holds it. Returns True on success."""
        with self._mu:
            if self._holder is None or self._holder == owner:
                self._holder = owner
                return True
            return False

    def release(self, owner: str) -> bool:
        """Release the lock if `owner` holds it. Returns True if released."""
        with self._mu:
            if self._holder == owner:
                self._holder = None
                return True
            return False

    def can_command(self, owner: str) -> bool:
        """True only when `owner` currently holds the lock."""
        return self._holder == owner
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_arming.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow/arming.py backend/tests/test_arming.py
git commit -m "feat(follow): add ArmingLock exclusive command interlock"
```

---

### Task 2: Gate FollowController on the ArmingLock

**Files:**
- Modify: `backend/app/follow/controller.py` (`__init__`, `_drive_tello`)
- Test: `backend/tests/test_arming.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_arming.py
import asyncio

from app.clock import FakeClock
from app.contracts import EntityType
from app.follow.controller import FollowController
from app.state_machine import MissionStateMachine, Stage
from app.world_model import WorldModel


class _RecordingTello:
    """Minimal TelloClient stand-in that records RC commands."""
    def __init__(self):
        self.rc_calls = []
        self.hover_calls = 0
        from app.tello.client import TelloState
        self.state = TelloState.CONNECTED
        self.is_connected = True
    def send_rc(self, lr, fb, ud, yaw):
        self.rc_calls.append((lr, fb, ud, yaw)); return True
    def hover(self):
        self.hover_calls += 1
    def land(self):
        pass


class _DummyVideo:
    def read_jpeg(self):
        return None


def test_follow_controller_will_not_drive_without_the_lock():
    lock = ArmingLock()  # unheld
    tello = _RecordingTello()
    mission = MissionStateMachine()
    mission.apply_stage(Stage.FOLLOWING) if hasattr(mission, "apply_stage") else None
    ctrl = FollowController(
        tello=tello, video=_DummyVideo(), world=WorldModel(clock=FakeClock()),
        mission=mission, clock=FakeClock(), arming=lock,
    )
    # Force FOLLOWING and a synthetic reading, then drive once.
    from app.follow.apriltag import TagReading
    reading = TagReading(tag_id=1, distance_m=3.0, bearing_x_norm=0.0,
                         bearing_y_norm=0.0, centre_px=(0, 0), timestamp=0.0)
    mission.apply(__import__("app.contracts", fromlist=["Command"]).Command.FOLLOW_ME)
    asyncio.run(ctrl._drive_tello(reading, now=0.0))
    assert tello.rc_calls == []   # never commanded without the lock


def test_follow_controller_drives_when_it_holds_the_lock():
    lock = ArmingLock(); lock.acquire("follow")
    tello = _RecordingTello()
    mission = MissionStateMachine()
    from app.contracts import Command
    mission.apply(Command.FOLLOW_ME)
    ctrl = FollowController(
        tello=tello, video=_DummyVideo(), world=WorldModel(clock=FakeClock()),
        mission=mission, clock=FakeClock(), arming=lock,
    )
    from app.follow.apriltag import TagReading
    reading = TagReading(tag_id=1, distance_m=3.0, bearing_x_norm=0.2,
                         bearing_y_norm=0.0, centre_px=(0, 0), timestamp=0.0)
    asyncio.run(ctrl._drive_tello(reading, now=0.0))
    assert len(tello.rc_calls) == 1
```

> NOTE: if `MissionStateMachine` has no `FOLLOWING` transition from the initial stage via `FOLLOW_ME`, set the stage directly in the test using the machine's real API discovered in Task 6; adjust the two `mission.apply(...)` lines to whatever drives it to `Stage.FOLLOWING`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_arming.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'arming'`

- [ ] **Step 3: Implement — add the lock to FollowController**

In `backend/app/follow/controller.py`, add to `__init__` signature (after `clock`):

```python
        clock: Clock | None = None,
        arming: "ArmingLock | None" = None,
        owner: str = "follow",
```

Add imports at top of file:

```python
from .arming import ArmingLock
```

In `__init__` body, store them:

```python
        self._clock = clock or RealClock()
        self._arming = arming
        self._owner = owner
```

At the very top of `_drive_tello`, before any command, add the gate:

```python
    async def _drive_tello(self, reading: Optional[TagReading], now: float) -> None:
        # Arming interlock: never command the drone unless we hold the lock.
        if self._arming is not None and not self._arming.can_command(self._owner):
            return
        stage = self._mission.stage
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_arming.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow/controller.py backend/tests/test_arming.py
git commit -m "feat(follow): gate FollowController commands on the ArmingLock"
```

---

### Task 3: TargetReading + TargetDetector protocol + test double

**Files:**
- Create: `backend/app/follow/target.py`
- Test: covered by Task 4's tests (this task adds no behavior of its own beyond the dataclass; a trivial test below locks the shape).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_approach.py
from app.follow.target import TargetReading, SyntheticTargetDetector


def test_target_reading_fields():
    r = TargetReading(label="person", distance_m=4.0, bearing_x_norm=-0.3,
                      bearing_y_norm=0.1, confidence=0.8, timestamp=1.0)
    assert r.label == "person"
    assert r.distance_m == 4.0
    assert r.bearing_x_norm == -0.3


def test_synthetic_detector_replays_scripted_readings():
    a = TargetReading("person", 4.0, 0.0, 0.0, 0.9, 0.0)
    b = TargetReading("person", 3.0, 0.0, 0.0, 0.9, 1.0)
    det = SyntheticTargetDetector([a, None, b])
    assert det.detect(jpeg=None, now=0.0) is a
    assert det.detect(jpeg=None, now=0.5) is None
    assert det.detect(jpeg=None, now=1.0) is b
    assert det.detect(jpeg=None, now=2.0) is None   # exhausted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.follow.target'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/follow/target.py
"""Target sensing for the autonomous approach behavior.

Mirrors apriltag.TagReading, but the target is a YOLO-detected object in the
Tello's OWN camera frame (not the Mavic world frame): bearing from the box
centre, range estimated from apparent box size. A Protocol lets tests inject
scripted readings without any model or hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class TargetReading:
    """One frame's observation of the approach target, normalised for control."""
    label: str
    distance_m: float          # estimated metres to the target
    bearing_x_norm: float      # [-1, 1], +ve = target right of centre
    bearing_y_norm: float      # [-1, 1], +ve = target above centre
    confidence: float
    timestamp: float


class TargetDetector(Protocol):
    def detect(self, jpeg: Optional[bytes], now: float) -> Optional[TargetReading]:
        """Return the current target reading, or None if not seen this frame."""
        ...


class SyntheticTargetDetector:
    """Deterministic detector that replays a scripted list of readings, one per
    detect() call. Used by the approach tests; no model, no hardware."""
    def __init__(self, script: List[Optional[TargetReading]]) -> None:
        self._script = list(script)
        self._i = 0

    def detect(self, jpeg: Optional[bytes], now: float) -> Optional[TargetReading]:
        if self._i >= len(self._script):
            return None
        r = self._script[self._i]
        self._i += 1
        return r
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow/target.py backend/tests/test_approach.py
git commit -m "feat(follow): add TargetReading + TargetDetector protocol"
```

---

### Task 4: ApproachController — state machine + PD + standoff

**Files:**
- Create: `backend/app/follow/approach.py`
- Test: `backend/tests/test_approach.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_approach.py
from app.clock import FakeClock
from app.follow.arming import ArmingLock
from app.follow.approach import ApproachController, ApproachPhase
from app.world_model import WorldModel
from app.contracts import EntityType


class _RecTello:
    def __init__(self):
        self.rc_calls = []
        from app.tello.client import TelloState
        self.state = TelloState.CONNECTED
        self.is_connected = True
    def send_rc(self, lr, fb, ud, yaw): self.rc_calls.append((lr, fb, ud, yaw)); return True
    def hover(self): self.rc_calls.append((0, 0, 0, 0))


def _ctrl(world=None, lock=None, standoff=1.5):
    lock = lock or ArmingLock(); lock.acquire("approach")
    return ApproachController(
        tello=_RecTello(), world=world or WorldModel(clock=FakeClock()),
        arming=lock, clock=FakeClock(), standoff_m=standoff, owner="approach",
    )


def test_far_target_commands_forward():
    c = _ctrl(standoff=1.5)
    r = TargetReading("person", distance_m=5.0, bearing_x_norm=0.0,
                      bearing_y_norm=0.0, confidence=0.9, timestamp=0.0)
    c.step(r, now=0.0)
    assert c.phase is ApproachPhase.APPROACHING
    fb = c.tello.rc_calls[-1][1]
    assert fb > 0   # too far → drive forward


def test_at_standoff_holds():
    c = _ctrl(standoff=1.5)
    r = TargetReading("person", distance_m=1.5, bearing_x_norm=0.0,
                      bearing_y_norm=0.0, confidence=0.9, timestamp=0.0)
    c.step(r, now=0.0)
    assert c.phase is ApproachPhase.STANDOFF
    assert c.tello.rc_calls[-1] == (0, 0, 0, 0)   # hover at standoff


def test_target_right_of_centre_yaws_right():
    c = _ctrl()
    r = TargetReading("person", distance_m=3.0, bearing_x_norm=0.5,
                      bearing_y_norm=0.0, confidence=0.9, timestamp=0.0)
    c.step(r, now=0.0)
    assert c.tello.rc_calls[-1][3] > 0   # yaw right


def test_lost_target_hovers_then_aborts_on_timeout():
    c = _ctrl()
    r = TargetReading("person", 3.0, 0.0, 0.0, 0.9, 0.0)
    c.step(r, now=0.0)
    c.step(None, now=1.0)   # lost
    assert c.tello.rc_calls[-1] == (0, 0, 0, 0)   # hover while lost
    c.step(None, now=10.0)  # past loss timeout
    assert c.phase is ApproachPhase.ABORT


def test_never_commands_without_the_lock():
    lock = ArmingLock()  # unheld
    c = ApproachController(tello=_RecTello(), world=WorldModel(clock=FakeClock()),
                          arming=lock, clock=FakeClock(), standoff_m=1.5, owner="approach")
    r = TargetReading("person", 5.0, 0.0, 0.0, 0.9, 0.0)
    c.step(r, now=0.0)
    assert c.tello.rc_calls == []


def test_emits_target_and_drone_entities():
    world = WorldModel(clock=FakeClock())
    c = _ctrl(world=world)
    r = TargetReading("person", 3.0, 0.2, 0.0, 0.9, 0.0)
    c.step(r, now=0.0)
    ids = {e.id for e in world.snapshot()}
    assert "approach_target" in ids
    assert "tello" in ids
    target = next(e for e in world.snapshot() if e.id == "approach_target")
    assert target.label == "person"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.follow.approach'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/follow/approach.py
"""Autonomous approach-and-standoff to a detected target.

Reuses the FollowController control idiom (PD over distance/bearing, RC drive,
world-model entity emission) but the target is a YOLO-detected object in the
Tello's own camera rather than an AprilTag. Bounded by a fixed standoff radius,
RC saturation, and a loss timeout that aborts to a hover.

State: SEEKING (no target yet) -> APPROACHING (driving toward standoff) ->
STANDOFF (holding at radius) -> ABORT (target lost past timeout).
"""
from __future__ import annotations

import enum
from typing import Optional

import numpy as np

from ..clock import Clock, RealClock
from ..contracts import Entity, EntitySource, EntityType, Vec3
from .arming import ArmingLock
from .target import TargetReading

# Reuse the follow loop's tuning so behavior is consistent and pre-validated.
_KP_DIST = 35.0
_KD_DIST = 12.0
_KP_YAW = 60.0
_KD_YAW = 18.0
_KP_VERT = 40.0
_KD_VERT = 10.0
_RC_LIMIT = 35
_STANDOFF_TOL_M = 0.25       # within this of standoff = "at standoff"
_LOSS_TIMEOUT_S = 5.0        # target lost longer than this -> ABORT
_LOOP_HZ = 15.0


class ApproachPhase(str, enum.Enum):
    SEEKING = "seeking"
    APPROACHING = "approaching"
    STANDOFF = "standoff"
    ABORT = "abort"


class ApproachController:
    def __init__(
        self,
        tello,
        world,
        arming: ArmingLock,
        clock: Clock | None = None,
        standoff_m: float = 1.5,
        owner: str = "approach",
    ) -> None:
        self.tello = tello
        self._world = world
        self._arming = arming
        self._clock = clock or RealClock()
        self._standoff = float(standoff_m)
        self._owner = owner
        self.phase = ApproachPhase.SEEKING
        self._prev_err = np.zeros(3)
        self._prev_t: Optional[float] = None
        self._lost_since: Optional[float] = None

    def step(self, reading: Optional[TargetReading], now: float) -> None:
        """One control tick. Pure + synchronous so it is trivially testable."""
        if self._arming is None or not self._arming.can_command(self._owner):
            return  # interlock: not armed, never command

        if self.phase is ApproachPhase.ABORT:
            self.tello.hover()
            return

        if reading is None:
            if self._lost_since is None:
                self._lost_since = now
            self.tello.hover()
            if now - self._lost_since >= _LOSS_TIMEOUT_S:
                self.phase = ApproachPhase.ABORT
            return

        self._lost_since = None
        self._emit_entities(reading, now)

        dist_err = reading.distance_m - self._standoff
        if abs(dist_err) <= _STANDOFF_TOL_M and abs(reading.bearing_x_norm) < 0.1:
            self.phase = ApproachPhase.STANDOFF
            self.tello.hover()
            return

        self.phase = ApproachPhase.APPROACHING
        bearing_x = reading.bearing_x_norm
        bearing_y = reading.bearing_y_norm
        dt = 1.0 / _LOOP_HZ if self._prev_t is None else max(1e-3, now - self._prev_t)
        err = np.array([dist_err, bearing_x, bearing_y])
        derr = (err - self._prev_err) / dt
        self._prev_err = err
        self._prev_t = now

        fb = int(np.clip(_KP_DIST * dist_err + _KD_DIST * derr[0], -_RC_LIMIT, _RC_LIMIT))
        yaw = int(np.clip(_KP_YAW * bearing_x + _KD_YAW * derr[1], -_RC_LIMIT, _RC_LIMIT))
        ud = int(np.clip(_KP_VERT * bearing_y + _KD_VERT * derr[2], -_RC_LIMIT, _RC_LIMIT))
        self.tello.send_rc(0, fb, ud, yaw)

    def _emit_entities(self, reading: TargetReading, now: float) -> None:
        forward = reading.distance_m
        lateral = reading.distance_m * reading.bearing_x_norm
        vertical = reading.distance_m * reading.bearing_y_norm
        self._world.upsert(Entity(
            id="approach_target", type=EntityType.OBJECT,
            position=Vec3(x=lateral, y=forward, z=-vertical),
            confidence=reading.confidence, timestamp=now,
            source=EntitySource.FOLLOW, label=reading.label, ttl_s=2.0,
        ))
        self._world.upsert(Entity(
            id="tello", type=EntityType.DRONE, position=Vec3(x=0.0, y=0.0, z=1.0),
            confidence=1.0, timestamp=now, source=EntitySource.FOLLOW,
            label="companion", ttl_s=2.0,
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach.py -q`
Expected: PASS (all approach tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow/approach.py backend/tests/test_approach.py
git commit -m "feat(follow): autonomous approach-and-standoff controller"
```

---

### Task 5: Add Command.APPROACH and Stage.APPROACH

**Files:**
- Modify: `backend/app/contracts.py` (Command enum)
- Modify: `backend/app/state_machine.py` (Stage + transitions)
- Test: `backend/tests/test_state_machine.py` (add) — match the file's existing style first by reading it.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_state_machine.py
from app.contracts import Command
from app.state_machine import MissionStateMachine, Stage


def test_approach_command_enters_approach_stage():
    m = MissionStateMachine()
    m.apply(Command.FOLLOW_ME)        # IDLE -> FOLLOWING (or whatever the entry is)
    m.apply(Command.APPROACH)
    assert m.stage is Stage.APPROACH


def test_stop_aborts_approach():
    m = MissionStateMachine()
    m.apply(Command.FOLLOW_ME)
    m.apply(Command.APPROACH)
    m.apply(Command.STOP)
    assert m.stage is Stage.STOPPED
```

> NOTE: Read `backend/app/state_machine.py` first to learn the real transition table (`_NORMAL_TRANSITIONS`) and the entry stage for `FOLLOW_ME`. Adjust the first `apply` so the test reaches a stage from which `APPROACH` is allowed. Keep `STOP` always-honored (it already is).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_state_machine.py -q`
Expected: FAIL — `AttributeError: APPROACH` on `Command` or `Stage`.

- [ ] **Step 3: Implement**

In `backend/app/contracts.py`, add to `Command`:

```python
class Command(str, Enum):
    FOLLOW_ME = "follow_me"
    HOLD = "hold"
    RECALL = "recall"
    STOP = "stop"
    APPROACH = "approach"
```

In `backend/app/state_machine.py`, add `APPROACH = "approach"` to the `Stage` enum, and add a transition into it from the following/holding stages in the normal-transition table (use the exact table structure found in Step 1's read). For example, if the table is keyed `command -> {from_stage: to_stage}`:

```python
    Command.APPROACH: {Stage.FOLLOWING: Stage.APPROACH, Stage.HOLDING: Stage.APPROACH},
    # allow returning to following from approach
    Command.FOLLOW_ME: {Stage.IDLE: Stage.FOLLOWING, Stage.APPROACH: Stage.FOLLOWING, ...},
```

(`STOP`/`RECALL` already short-circuit to `STOPPED`/`RECALL` from any stage.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_state_machine.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts.py backend/app/state_machine.py backend/tests/test_state_machine.py
git commit -m "feat(mission): add APPROACH command and stage"
```

---

### Task 6: Wire the lock + approach controller into the server

**Files:**
- Modify: `backend/app/server.py` (construction + startup + WS command routing + driving the approach loop)
- Test: manual smoke (the loop is async + hardware-facing); behavior is covered by Tasks 1–5 unit tests. Add one wiring test below.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_approach_wiring.py
from app.contracts import Command
from app.follow.arming import ArmingLock


def test_approach_command_arms_approach_owner():
    """The server's command handler should, on Command.APPROACH, transfer the
    arming lock from 'follow' to 'approach'. We test the helper in isolation."""
    from app.server import _route_arming_for_command  # pure helper added in Step 3
    lock = ArmingLock(); lock.acquire("follow")
    _route_arming_for_command(Command.APPROACH, lock)
    assert lock.holder == "approach"
    _route_arming_for_command(Command.FOLLOW_ME, lock)
    assert lock.holder == "follow"
    _route_arming_for_command(Command.STOP, lock)
    assert lock.holder is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name '_route_arming_for_command'`

- [ ] **Step 3: Implement the wiring**

In `backend/app/server.py`:

1. Construct the shared lock near the Tello construction (~line 250):

```python
from .follow.arming import ArmingLock
from .follow.approach import ApproachController

arming = ArmingLock()
```

2. Pass it to `FollowController(...)` (add `arming=arming, owner="follow"`), and construct the approach controller:

```python
approach = ApproachController(
    tello=tello_client, world=world, arming=arming, clock=clock,
    standoff_m=float(os.environ.get("APPROACH_STANDOFF_M", "1.5")),
    owner="approach",
)
```

3. Add the pure arming-routing helper (module level):

```python
def _route_arming_for_command(command: Command, lock: ArmingLock) -> None:
    """Transfer the Tello arming lock to match the commanded mode."""
    if command is Command.APPROACH:
        lock.release("follow"); lock.acquire("approach")
    elif command is Command.FOLLOW_ME:
        lock.release("approach"); lock.acquire("follow")
    elif command in (Command.STOP, Command.RECALL):
        lock.release("follow"); lock.release("approach")
```

4. In the WS handler where `IntentMessage` is applied (~line 846), call it after `mission.apply`:

```python
            if isinstance(msg, IntentMessage):
                mission.apply(msg.command)
                _route_arming_for_command(msg.command, arming)
```

5. Drive the approach controller from a loop that feeds it the Tello frame + a target reading when `mission.stage is Stage.APPROACH`. Add the detector wiring (real detector adapter or, until the Tello-frame detector lands, a no-op that returns None so it safely hovers) and a 15 Hz task started in `_startup` alongside `follow.start()` when `not _TELLO_DISABLED`.

```python
async def _approach_loop() -> None:
    import asyncio as _a
    interval = 1.0 / 15.0
    while True:
        if mission.stage is Stage.APPROACH:
            jpeg = tello_camera.read_jpeg()
            reading = approach_detector.detect(jpeg, clock.now())  # see Task 7 / target.py adapter
            approach.step(reading, clock.now())
        await _a.sleep(interval)
```

(For the demo, `approach_detector` is the real Tello-frame YOLO adapter; in CI it is never started.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach_wiring.py -q`
Expected: PASS

- [ ] **Step 5: Run the full suite + commit**

```bash
cd backend && .venv/bin/python -m pytest -q
git add backend/app/server.py backend/tests/test_approach_wiring.py
git commit -m "feat(server): route APPROACH command, arm approach controller"
```

---

### Task 7: Deterministic sim/replay e2e for the approach behavior

**Files:**
- Test: `backend/tests/test_approach_sim.py`

- [ ] **Step 1: Write the test (this IS the deliverable — proves the loop converges)**

```python
# backend/tests/test_approach_sim.py
from app.clock import FakeClock
from app.follow.arming import ArmingLock
from app.follow.approach import ApproachController, ApproachPhase
from app.follow.target import TargetReading
from app.world_model import WorldModel


class _SimTello:
    """Integrates RC forward/back into a closing range, so we can prove the
    PD loop actually drives the target distance to standoff."""
    def __init__(self, start_dist=5.0):
        self.dist = start_dist
        from app.tello.client import TelloState
        self.state = TelloState.CONNECTED
        self.is_connected = True
    def send_rc(self, lr, fb, ud, yaw):
        # fb>0 means "go forward" -> reduce distance. Scale to metres/tick.
        self.dist = max(0.0, self.dist - fb * 0.01)
    def hover(self): pass


def test_approach_converges_to_standoff():
    lock = ArmingLock(); lock.acquire("approach")
    tello = _SimTello(start_dist=5.0)
    world = WorldModel(clock=FakeClock())
    c = ApproachController(tello=tello, world=world, arming=lock,
                          clock=FakeClock(), standoff_m=1.5, owner="approach")
    t = 0.0
    for _ in range(300):                       # 20 s at 15 Hz
        r = TargetReading("person", distance_m=tello.dist, bearing_x_norm=0.0,
                          bearing_y_norm=0.0, confidence=0.9, timestamp=t)
        c.step(r, now=t)
        t += 1.0 / 15.0
        if c.phase is ApproachPhase.STANDOFF:
            break
    assert c.phase is ApproachPhase.STANDOFF
    assert abs(tello.dist - 1.5) <= 0.3        # converged to standoff radius
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_approach_sim.py -q`
Expected: PASS (the controller from Task 4 already implements convergence). If it doesn't converge, the PD gains in `approach.py` need the `_KP_DIST` adjustment — tune until this deterministic test passes.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_approach_sim.py
git commit -m "test(follow): deterministic approach-to-standoff convergence sim"
```

---

## Self-Review

- **Spec coverage:** #4 interlock → Tasks 1, 2, 6. #5 autonomous behavior → Tasks 3, 4, 7. Map plotting → Task 4 `_emit_entities` (+ Task 6 loop). Coexistence with follow-me → Task 2 (follow gated) + Task 6 (lock transfer). Sim de-risk → Task 7.
- **Type consistency:** `ArmingLock.can_command/acquire/release/holder`, `TargetReading` fields, `ApproachController.step/phase`, `ApproachPhase`, `Command.APPROACH`, `Stage.APPROACH` are used consistently across tasks.
- **Open verification points flagged inline:** the exact `MissionStateMachine` transition API (Task 5/6) and the real Tello-frame `TargetDetector` adapter (Task 6/7) must be confirmed against `state_machine.py` and the perception detector before wiring; tests use the synthetic detector and pure `step()` so they don't depend on those.
