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

_KP_DIST = 35.0
_KD_DIST = 12.0
_KP_YAW = 60.0
_KD_YAW = 18.0
_KP_VERT = 40.0
_KD_VERT = 10.0
_RC_LIMIT = 35
_STANDOFF_TOL_M = 0.25
_LOSS_TIMEOUT_S = 5.0
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
        if not self._arming.can_command(self._owner):
            return

        # ABORT is terminal by design: once the target is lost past the timeout
        # we do not auto-resume autonomous flight — the operator must re-command
        # (FOLLOW_ME/APPROACH/STOP). Fail-safe: hold a hover until then.
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
