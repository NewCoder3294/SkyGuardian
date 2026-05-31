"""Tests pinning the audit fixes (2026-05-31 deep audit).

Covers: bounded RECALL drive + mission.fail() wiring, TelloVideoSource freshness
window, EntityReport reserved-id rejection + ttl clamp + receipt restamp, and the
Designator ACTIVE-only candidate filter.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.clock import FakeClock
from app.contracts import (
    Command,
    Entity,
    EntityReport,
    EntitySource,
    EntityStatus,
    EntityType,
    Vec3,
)
from app.designation import Designator
from app.follow.apriltag import TagReading
from app.follow.arming import ArmingLock
from app.follow.controller import FollowController, _RECALL_MAX_S
from app.state_machine import MissionStateMachine, Stage
from app.world_model import WorldModel


class _RecordingTello:
    def __init__(self):
        from app.tello.client import TelloState
        self.rc_calls: list[tuple[int, int, int, int]] = []
        self.hover_calls = 0
        self.land_calls = 0
        self.state = TelloState.CONNECTED
        self.is_connected = True

    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> bool:
        self.rc_calls.append((lr, fb, ud, yaw))
        return True

    def hover(self) -> None:
        self.hover_calls += 1

    def land(self) -> None:
        self.land_calls += 1


class _DummyVideo:
    def read_jpeg(self):
        return None


def _recall_controller(clock: FakeClock):
    tello = _RecordingTello()
    lock = ArmingLock(); lock.acquire("follow")
    world = WorldModel(clock=clock)
    mission = MissionStateMachine(clock=clock)
    mission.apply(Command.RECALL)
    assert mission.stage is Stage.RECALL
    ctrl = FollowController(
        tello=tello, video=_DummyVideo(), world=world, mission=mission,
        clock=clock, arming=lock, owner="follow",
    )
    return ctrl, tello, mission


def _reading() -> TagReading:
    return TagReading(
        tag_id=0, distance_m=2.0, bearing_x_norm=0.3, bearing_y_norm=0.0,
        centre_px=(0.0, 0.0), timestamp=0.0,
    )


# --- RECALL: bounded, sensing-gated ----------------------------------------

def test_recall_hovers_when_no_tag_reading():
    """No blind thrust: with no valid reading RECALL must hover, not send_rc."""
    clock = FakeClock(0.0)
    ctrl, tello, _ = _recall_controller(clock)
    asyncio.run(ctrl._drive_tello(reading=None, now=clock.now()))
    assert tello.rc_calls == []
    assert tello.hover_calls == 1


def test_recall_drives_along_bearing_with_a_reading():
    """With a reading, RECALL flies backward and yaws to re-centre the tag."""
    clock = FakeClock(0.0)
    ctrl, tello, _ = _recall_controller(clock)
    asyncio.run(ctrl._drive_tello(reading=_reading(), now=clock.now()))
    assert len(tello.rc_calls) == 1
    lr, fb, ud, yaw = tello.rc_calls[0]
    assert lr == 0 and ud == 0
    assert fb < 0          # backward, toward the recall point
    assert yaw > 0         # bearing_x > 0 -> yaw right to re-centre


def test_recall_times_out_to_stopped_via_mission_fail():
    """Open-loop recall must never run forever: after _RECALL_MAX_S the
    controller trips mission.fail() (-> STOPPED) instead of driving on."""
    clock = FakeClock(0.0)
    ctrl, tello, mission = _recall_controller(clock)
    # First tick arms the recall timer.
    asyncio.run(ctrl._drive_tello(reading=_reading(), now=clock.now()))
    assert mission.stage is Stage.RECALL
    # Advance past the budget; next tick fails closed.
    clock.advance(_RECALL_MAX_S + 0.5)
    asyncio.run(ctrl._drive_tello(reading=_reading(), now=clock.now()))
    assert mission.stage is Stage.STOPPED
    assert mission.last_error == "recall_timeout"


def test_leaving_recall_resets_the_timer():
    """The recall budget is per-RECALL: leaving and re-entering starts fresh."""
    clock = FakeClock(0.0)
    ctrl, tello, mission = _recall_controller(clock)
    asyncio.run(ctrl._drive_tello(reading=_reading(), now=clock.now()))
    # Switch to FOLLOWING (clears the timer), then back to RECALL.
    mission.apply(Command.FOLLOW_ME)
    asyncio.run(ctrl._drive_tello(reading=_reading(), now=clock.now()))
    assert ctrl._recall_started_at is None
    mission.apply(Command.RECALL)
    clock.advance(_RECALL_MAX_S + 0.5)
    # Re-entering RECALL: this tick only ARMS the timer (no immediate timeout).
    asyncio.run(ctrl._drive_tello(reading=_reading(), now=clock.now()))
    assert mission.stage is Stage.RECALL


# --- TelloVideoSource freshness window -------------------------------------

def _bare_tello_video():
    from app.tello.video import TelloVideoSource
    src = TelloVideoSource.__new__(TelloVideoSource)
    import threading
    src._lock = threading.Lock()
    src._latest_jpeg = None
    src._latest_t = 0.0
    return src


def test_tello_video_returns_fresh_jpeg():
    src = _bare_tello_video()
    src._latest_jpeg = b"\xff\xd8\xff"
    src._latest_t = time.monotonic()
    assert src.read_jpeg() == b"\xff\xd8\xff"


def test_tello_video_returns_none_when_stale():
    src = _bare_tello_video()
    src._latest_jpeg = b"\xff\xd8\xff"
    src._latest_t = time.monotonic() - (src._FRESH_WINDOW_S + 0.5)
    assert src.read_jpeg() is None


def test_tello_video_returns_none_when_no_frame():
    src = _bare_tello_video()
    assert src.read_jpeg() is None


# --- EntityReport hardening -------------------------------------------------

def _phone_entity(id: str, ttl_s: float = 5.0, timestamp: float = 0.0) -> Entity:
    return Entity(
        id=id, type=EntityType.DRONE, position=Vec3(x=1.0, y=2.0, z=0.0),
        confidence=0.9, timestamp=timestamp, source=EntitySource.MANUAL,
        label="phone", ttl_s=ttl_s,
    )


def test_entity_report_rejects_reserved_ids():
    from app import server
    server.world.remove("tello")
    server.world.remove("designated_target")
    msg = EntityReport(
        entities=[_phone_entity("tello"), _phone_entity("designated_target")],
        t=server.clock.now(),
    )
    server._apply_entity_report(msg)
    ids = {e.id for e in server.world.snapshot()}
    assert "tello" not in ids
    assert "designated_target" not in ids


def test_entity_report_allows_soldier_and_drone():
    from app import server
    server.world.remove("soldier")
    server.world.remove("drone")
    msg = EntityReport(
        entities=[_phone_entity("soldier"), _phone_entity("drone")],
        t=server.clock.now(),
    )
    server._apply_entity_report(msg)
    ids = {e.id for e in server.world.snapshot()}
    assert "soldier" in ids and "drone" in ids
    server.world.remove("soldier")
    server.world.remove("drone")


def test_entity_report_clamps_ttl_and_restamps_timestamp():
    from app import server
    server.world.remove("drone")
    # ttl above the server clamp + a stale client timestamp.
    msg = EntityReport(
        entities=[_phone_entity("drone", ttl_s=60.0, timestamp=1.0)],
        t=server.clock.now(),
    )
    server._apply_entity_report(msg)
    drone = {e.id: e for e in server.world.snapshot()}["drone"]
    assert drone.ttl_s <= server._MAX_REPORTED_TTL_S
    assert drone.timestamp == pytest.approx(server.clock.now(), abs=1.0)
    server.world.remove("drone")


def test_entity_ttl_field_bound_rejects_unbounded_values():
    """The contract now bounds ttl_s so a malformed payload can't pin a marker
    ACTIVE forever even before the server clamp runs."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _phone_entity("drone", ttl_s=10_000.0)
    with pytest.raises(ValidationError):
        _phone_entity("drone", ttl_s=0.0)


# --- Designator ACTIVE-only filter -----------------------------------------

def _yolo(id: str, status: EntityStatus) -> Entity:
    return Entity(
        id=id, type=EntityType.OBJECT, position=Vec3(x=1.0, y=0.0, z=0.0),
        confidence=0.9, timestamp=0.0, source=EntitySource.YOLO,
        label="person", ttl_s=5.0, status=status,
    )


def test_designator_ignores_stale_and_lost_candidates():
    d = Designator()
    assert d.select([_yolo("s", EntityStatus.STALE)], "low") is None
    assert d.select([_yolo("l", EntityStatus.LOST)], "low") is None


def test_designator_picks_active_candidate():
    d = Designator()
    chosen = d.select([_yolo("a", EntityStatus.ACTIVE)], "low")
    assert chosen is not None and chosen.entity_id == "a"
