"""Follow controller — station-keep on the soldier-worn AprilTag.

Async loop:
  1. Read a Tello frame.
  2. Detect the soldier tag → bearing + distance.
  3. PD-regulate to a target stand-off (default 1.2 m, behind + below).
  4. Send RC commands to the Tello (only when mission stage == FOLLOWING).
  5. Publish the drone and soldier as world-model entities (source = follow).

Mission stage handling:
  - IDLE / HOLDING / RECALL / STOPPED → the loop keeps detecting so the
    dashboard still sees the soldier on the map.
  - HOLDING → send a zero-RC hover to keep the Tello in place.
  - RECALL → fly back toward the soldier along the last measured tag bearing.
    Bounded: hover (no blind thrust) whenever the tag is not in view, and fail
    closed to STOPPED after `_RECALL_MAX_S` so recall can never drive forever.
  - STOPPED → land if airborne, no further commands.

The controller does *not* assume a Tello is connected. If the link is down it
idles, publishes no drone entity, and lets the state machine reflect the fault.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import numpy as np

from ..clock import Clock, RealClock
from ..contracts import Entity, EntitySource, EntityType, Vec3
from ..perception.slam.types import CameraModel
from ..state_machine import MissionStateMachine, Stage
from ..tello.client import TelloClient, TelloState
from ..tello.video import TelloVideoSource
from ..world_model import WorldModel
from .apriltag import TagReading, detect_soldier_tag
from .arming import ArmingLock


# Target stand-off distance from the soldier (metres). PD pushes us here.
_TARGET_DISTANCE_M = 1.2

# PD gains. Conservative; the Tello tolerates jerky inputs poorly. Tune on hardware.
_KP_DIST = 35.0     # fore/aft response per metre of error
_KD_DIST = 12.0
_KP_YAW = 60.0      # yaw response per unit normalised bearing
_KD_YAW = 18.0
_KP_VERT = 40.0
_KD_VERT = 10.0

# RC saturation. Tello accepts -100..100; keep well under to avoid overshoot.
_RC_LIMIT = 35

# Frame loop pacing (Hz). Tello video is ~30 fps; controller runs at 15.
_LOOP_HZ = 15.0

# Maximum time the controller will drive in RECALL before failing closed to a
# safe stop. Open-loop recall must never run unbounded: once this elapses we
# trip the mission state machine's named failure (-> STOPPED), which lands the
# drone on the next tick instead of flying backward indefinitely.
_RECALL_MAX_S = 8.0


class FollowController:
    """Owns the follow loop. Construct once at startup, call `start()` from the
    server's _startup hook."""

    def __init__(
        self,
        tello: TelloClient,
        video: TelloVideoSource,
        world: WorldModel,
        mission: MissionStateMachine,
        arming: ArmingLock,
        clock: Clock | None = None,
        owner: str = "follow",
        img_width: int = 960,
        img_height: int = 720,
        tag_size_m: float = 0.18,
        soldier_tag_id: Optional[int] = None,
    ) -> None:
        self._tello = tello
        self._video = video
        self._world = world
        self._mission = mission
        self._clock = clock or RealClock()
        self._arming = arming
        self._owner = owner
        self._camera = CameraModel.from_resolution(img_width, img_height)
        self._tag_size = float(tag_size_m)
        self._soldier_tag_id = soldier_tag_id

        self._task: asyncio.Task | None = None
        self._last_reading: Optional[TagReading] = None
        self._prev_err = np.zeros(3)  # [dist_err, bearing_x, bearing_y]
        self._prev_t: Optional[float] = None
        self._frames_seen = 0
        self._tag_loss_started_at: Optional[float] = None
        # Wall-clock the controller first entered RECALL, so we can bound how
        # long open-loop recall is allowed to drive before failing closed.
        self._recall_started_at: Optional[float] = None

    @property
    def has_recent_tag(self) -> bool:
        return self._last_reading is not None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        # Late import to avoid pulling cv2 at module load.
        try:
            import cv2  # noqa: PLC0415
            import numpy as _np  # noqa: PLC0415, F401
        except ImportError:
            return

        interval = 1.0 / _LOOP_HZ
        while True:
            t_start = time.monotonic()
            now = self._clock.now()

            jpeg = self._video.read_jpeg()
            reading: Optional[TagReading] = None

            if jpeg is not None:
                arr = np.frombuffer(jpeg, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    self._frames_seen += 1
                    reading = detect_soldier_tag(
                        frame, self._camera, self._tag_size,
                        self._soldier_tag_id, now,
                    )

            if reading is not None:
                self._last_reading = reading
                self._tag_loss_started_at = None
                self._emit_entities(reading, now)
            else:
                if self._tag_loss_started_at is None and self._last_reading is not None:
                    self._tag_loss_started_at = now

            await self._drive_tello(reading, now)

            elapsed = time.monotonic() - t_start
            await asyncio.sleep(max(0.0, interval - elapsed))

    # --- control surface ---------------------------------------------------

    async def _drive_tello(self, reading: Optional[TagReading], now: float) -> None:
        # Arming interlock: never command the drone unless we hold the lock.
        # FAIL-CLOSED — no None-guard. A missing/unheld lock means no driving.
        if not self._arming.can_command(self._owner):
            return

        stage = self._mission.stage
        # RECALL is the only stage that arms the recall timer; clear it the
        # moment we leave RECALL so a later recall starts a fresh budget.
        if stage is not Stage.RECALL:
            self._recall_started_at = None

        if stage is Stage.STOPPED:
            # Emergency: land if airborne, no further commands.
            if self._tello.is_connected:
                self._tello.land()
            return

        if stage is Stage.HOLDING:
            # Zero RC = hover in place.
            self._tello.hover()
            return

        if stage is Stage.RECALL:
            # Bounded recall. Open-loop thrust must never run forever, so:
            #   1. With no valid tag reading we hover (mirrors the FOLLOWING
            #      "tag lost" path) — never blind-thrust on no sensing.
            #   2. We cap total recall time; once _RECALL_MAX_S elapses we trip
            #      the mission's named failure (-> STOPPED) so the next tick
            #      lands the drone instead of flying it backward indefinitely.
            if self._recall_started_at is None:
                self._recall_started_at = now
            elif now - self._recall_started_at > _RECALL_MAX_S:
                self._mission.fail("recall_timeout")
                self._tello.hover()
                return

            if reading is None:
                # No bearing to fly toward — hold position and wait for the tag.
                self._tello.hover()
                return

            # Fly back toward the soldier along the measured bearing: yaw to
            # re-centre the tag and close distance (fb < 0 = backward toward the
            # operator-initiated recall point). Lateral hold via yaw, as in FOLLOW.
            yaw = int(np.clip(_KP_YAW * reading.bearing_x_norm, -_RC_LIMIT, _RC_LIMIT))
            self._tello.send_rc(0, -_RC_LIMIT // 2, 0, yaw)
            return

        if stage is not Stage.FOLLOWING:
            # IDLE — no commands.
            return

        if reading is None:
            # Tag lost while following: hover and coast. State machine should
            # trip a fault if loss exceeds a configured window.
            self._tello.hover()
            return

        # PD regulator. Errors:
        #   dist_err  : positive when too far, negative when too close.
        #   bearing_x : positive when tag is right of centre → yaw right.
        #   bearing_y : positive when tag is above centre   → climb.
        dist_err = reading.distance_m - _TARGET_DISTANCE_M
        bearing_x = reading.bearing_x_norm
        bearing_y = reading.bearing_y_norm

        if self._prev_t is None:
            dt = 1.0 / _LOOP_HZ
        else:
            dt = max(1e-3, now - self._prev_t)

        err = np.array([dist_err, bearing_x, bearing_y])
        derr = (err - self._prev_err) / dt
        self._prev_err = err
        self._prev_t = now

        fb = int(np.clip(_KP_DIST * dist_err + _KD_DIST * derr[0], -_RC_LIMIT, _RC_LIMIT))
        yaw = int(np.clip(_KP_YAW * bearing_x + _KD_YAW * derr[1], -_RC_LIMIT, _RC_LIMIT))
        ud = int(np.clip(_KP_VERT * bearing_y + _KD_VERT * derr[2], -_RC_LIMIT, _RC_LIMIT))

        # Lateral hold (lr=0): the soldier should stay centred via yaw. A future
        # iteration can add a small lateral term for crosswind compensation.
        self._tello.send_rc(0, fb, ud, yaw)

    # --- entity emission ---------------------------------------------------

    def _emit_entities(self, reading: TagReading, now: float) -> None:
        """Upsert the soldier and the drone into the world model.

        Coordinate convention: local frame is anchored at the launch point.
        With only tag-relative sensing we place the soldier in the *Tello's*
        body frame projected forward by the measured distance and bearing,
        and the Tello itself at the origin (best we can do without SLAM on the
        Tello video). When Tello video gets fed into the main SLAM stack, this
        becomes globally consistent.
        """
        # Soldier in front of Tello: x = lateral (bearing), y = forward distance.
        # Use a small-angle approximation: bearing_x_norm ~ tan(yaw_offset).
        forward = reading.distance_m
        lateral = reading.distance_m * reading.bearing_x_norm
        vertical = reading.distance_m * reading.bearing_y_norm
        soldier_pos = Vec3(x=lateral, y=forward, z=-vertical)

        self._world.upsert(Entity(
            id="soldier",
            type=EntityType.SOLDIER,
            position=soldier_pos,
            confidence=0.9,
            timestamp=now,
            source=EntitySource.FOLLOW,
            label="operator",
            ttl_s=2.0,
        ))

        if self._tello.state is TelloState.CONNECTED:
            self._world.upsert(Entity(
                id="tello",
                type=EntityType.DRONE,
                position=Vec3(x=0.0, y=0.0, z=1.0),
                confidence=1.0,
                timestamp=now,
                source=EntitySource.FOLLOW,
                label="companion",
                ttl_s=2.0,
            ))
