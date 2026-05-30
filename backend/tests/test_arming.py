import asyncio

from app.clock import FakeClock
from app.contracts import Command
from app.follow.apriltag import TagReading
from app.follow.arming import ArmingLock
from app.follow.controller import FollowController
from app.state_machine import MissionStateMachine, Stage
from app.world_model import WorldModel


class _RecordingTello:
    def __init__(self):
        from app.tello.client import TelloState
        self.rc_calls: list[tuple[int, int, int, int]] = []
        self.hover_calls = 0
        self.state = TelloState.CONNECTED
        self.is_connected = True

    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> bool:
        self.rc_calls.append((lr, fb, ud, yaw))
        return True

    def hover(self) -> None:
        self.hover_calls += 1

    def land(self) -> None:
        pass


class _DummyVideo:
    def read_jpeg(self) -> None:
        return None


def _make_reading() -> TagReading:
    """A non-trivial tag reading that should produce a non-zero RC command."""
    return TagReading(
        tag_id=0,
        distance_m=2.4,        # too far → positive fb
        bearing_x_norm=0.3,    # right of centre → non-zero yaw
        bearing_y_norm=0.0,
        centre_px=(480.0, 360.0),
        timestamp=0.0,
    )


def _make_controller(tello: _RecordingTello, lock: ArmingLock) -> FollowController:
    clock = FakeClock(start=0.0)
    world = WorldModel(clock=clock)
    mission = MissionStateMachine(clock=clock)
    # IDLE → FOLLOWING via Command.FOLLOW_ME (confirmed from state_machine.py)
    mission.apply(Command.FOLLOW_ME)
    assert mission.stage is Stage.FOLLOWING
    return FollowController(
        tello=tello,
        video=_DummyVideo(),
        world=world,
        mission=mission,
        clock=clock,
        arming=lock,
        owner="follow",
    )


def test_follow_controller_will_not_drive_without_the_lock():
    """FollowController must refuse to send RC when the ArmingLock is not held."""
    tello = _RecordingTello()
    lock = ArmingLock()  # unheld
    ctrl = _make_controller(tello, lock)
    reading = _make_reading()
    asyncio.run(ctrl._drive_tello(reading, now=0.0))
    assert tello.rc_calls == [], "Expected no RC commands when lock is not held"


def test_follow_controller_drives_when_it_holds_the_lock():
    """FollowController must send RC commands when it holds the ArmingLock."""
    tello = _RecordingTello()
    lock = ArmingLock()
    lock.acquire("follow")
    ctrl = _make_controller(tello, lock)
    reading = _make_reading()
    asyncio.run(ctrl._drive_tello(reading, now=0.0))
    assert len(tello.rc_calls) == 1, "Expected exactly one RC command when lock is held"


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
    assert lock.release("approach") is False
    assert lock.holder == "follow"
    assert lock.release("follow") is True
    assert lock.holder is None
