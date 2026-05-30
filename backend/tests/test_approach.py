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
    assert det.detect(jpeg=None, now=2.0) is None


from app.clock import FakeClock
from app.follow.arming import ArmingLock
from app.follow.approach import ApproachController, ApproachPhase
from app.world_model import WorldModel


class _RecTello:
    def __init__(self):
        from app.tello.client import TelloState
        self.rc_calls = []
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
    r = TargetReading("person", distance_m=5.0, bearing_x_norm=0.0, bearing_y_norm=0.0, confidence=0.9, timestamp=0.0)
    c.step(r, now=0.0)
    assert c.phase is ApproachPhase.APPROACHING
    assert c.tello.rc_calls[-1][1] > 0


def test_at_standoff_holds():
    c = _ctrl(standoff=1.5)
    r = TargetReading("person", distance_m=1.5, bearing_x_norm=0.0, bearing_y_norm=0.0, confidence=0.9, timestamp=0.0)
    c.step(r, now=0.0)
    assert c.phase is ApproachPhase.STANDOFF
    assert c.tello.rc_calls[-1] == (0, 0, 0, 0)


def test_target_right_of_centre_yaws_right():
    c = _ctrl()
    r = TargetReading("person", distance_m=3.0, bearing_x_norm=0.5, bearing_y_norm=0.0, confidence=0.9, timestamp=0.0)
    c.step(r, now=0.0)
    assert c.tello.rc_calls[-1][3] > 0


def test_lost_target_hovers_then_aborts_on_timeout():
    c = _ctrl()
    r = TargetReading("person", 3.0, 0.0, 0.0, 0.9, 0.0)
    c.step(r, now=0.0)
    c.step(None, now=1.0)
    assert c.tello.rc_calls[-1] == (0, 0, 0, 0)
    c.step(None, now=10.0)
    assert c.phase is ApproachPhase.ABORT


def test_never_commands_without_the_lock():
    lock = ArmingLock()
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
