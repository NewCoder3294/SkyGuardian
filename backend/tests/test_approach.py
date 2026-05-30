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


# ---------------------------------------------------------------------------
# BoxTargetDetector — pure geometry tests (TDD: written before implementation)
# ---------------------------------------------------------------------------

from types import SimpleNamespace
from app.follow.target import BoxTargetDetector
from app.perception.slam.types import CameraModel


def _box(label, confidence, cx_px, cy_px, w_px=60.0, h_px=80.0):
    """Stand-in for YoloDetection; same field names, no hardware dependency."""
    return SimpleNamespace(
        label=label,
        confidence=confidence,
        cx_px=cx_px,
        cy_px=cy_px,
        w_px=w_px,
        h_px=h_px,
    )


# Use explicit intrinsics so expected values are exact.
_CAM = CameraModel(fx=748.0, fy=748.0, cx=480.0, cy=360.0)  # 960×720 frame
_NOMINAL_H = 1.7  # metres (standing person)


def _detector(label="person", nominal_height_m=_NOMINAL_H):
    return BoxTargetDetector(camera=_CAM, target_label=label, nominal_height_m=nominal_height_m)


def test_box_centred_box_bearing_near_zero():
    """A box at the exact principal point produces bearing ≈ 0, 0."""
    det = _detector()
    box = _box("person", 0.9, cx_px=_CAM.cx, cy_px=_CAM.cy)
    reading = det.select([box], now=1.0)
    assert reading is not None
    assert abs(reading.bearing_x_norm) < 1e-9
    assert abs(reading.bearing_y_norm) < 1e-9


def test_box_right_of_centre_bearing_x_positive():
    """A box to the right of centre → bearing_x_norm > 0."""
    det = _detector()
    box = _box("person", 0.9, cx_px=_CAM.cx + 100.0, cy_px=_CAM.cy)
    reading = det.select([box], now=1.0)
    assert reading is not None
    assert reading.bearing_x_norm > 0.0


def test_box_below_centre_bearing_y_negative():
    """A box below the image centre (higher cy) → bearing_y_norm < 0
    (image y is inverted: down in pixels = below horizon)."""
    det = _detector()
    box = _box("person", 0.9, cx_px=_CAM.cx, cy_px=_CAM.cy + 80.0)
    reading = det.select([box], now=1.0)
    assert reading is not None
    assert reading.bearing_y_norm < 0.0


def test_box_distance_formula():
    """distance = fy * nominal_height_m / h_px  (pinhole range from apparent height)."""
    det = _detector()
    h_px = 100.0
    expected_dist = _CAM.fy * _NOMINAL_H / h_px  # 748 * 1.7 / 100 = 12.716
    box = _box("person", 0.9, cx_px=_CAM.cx, cy_px=_CAM.cy, h_px=h_px)
    reading = det.select([box], now=1.0)
    assert reading is not None
    assert abs(reading.distance_m - expected_dist) < 1e-6


def test_box_no_matching_label_returns_none():
    """No boxes with matching label → None."""
    det = _detector(label="person")
    boxes = [_box("car", 0.9, cx_px=_CAM.cx, cy_px=_CAM.cy)]
    assert det.select(boxes, now=1.0) is None


def test_box_empty_list_returns_none():
    """Empty detection list → None."""
    det = _detector()
    assert det.select([], now=1.0) is None


def test_box_higher_confidence_chosen():
    """When two matching boxes exist, the higher-confidence one is selected."""
    det = _detector()
    low = _box("person", 0.5, cx_px=_CAM.cx, cy_px=_CAM.cy, h_px=60.0)
    high = _box("person", 0.95, cx_px=_CAM.cx + 50.0, cy_px=_CAM.cy, h_px=120.0)
    reading = det.select([low, high], now=2.0)
    assert reading is not None
    assert reading.confidence == 0.95
    # distance should match the high-confidence box (h_px=120)
    expected_dist = _CAM.fy * _NOMINAL_H / 120.0
    assert abs(reading.distance_m - expected_dist) < 1e-6


def test_box_label_case_insensitive():
    """Label matching is case-insensitive (YOLO may return 'Person' or 'PERSON')."""
    det = _detector(label="person")
    box = _box("Person", 0.8, cx_px=_CAM.cx, cy_px=_CAM.cy)
    assert det.select([box], now=1.0) is not None


def test_box_zero_height_returns_none():
    """h_px <= 0 is degenerate — should return None rather than divide by zero."""
    det = _detector()
    box = _box("person", 0.9, cx_px=_CAM.cx, cy_px=_CAM.cy, h_px=0.0)
    assert det.select([box], now=1.0) is None


def test_box_bearing_clipped_to_unit():
    """Extreme off-axis box: bearing values must be clipped to [-1, 1]."""
    det = _detector()
    # cx_px far beyond image edge
    box = _box("person", 0.9, cx_px=_CAM.cx + 9999.0, cy_px=_CAM.cy - 9999.0)
    reading = det.select([box], now=1.0)
    assert reading is not None
    assert -1.0 <= reading.bearing_x_norm <= 1.0
    assert -1.0 <= reading.bearing_y_norm <= 1.0


def test_box_timestamp_forwarded():
    """The `now` argument must appear verbatim in the returned TargetReading."""
    det = _detector()
    box = _box("person", 0.9, cx_px=_CAM.cx, cy_px=_CAM.cy)
    reading = det.select([box], now=42.5)
    assert reading is not None
    assert reading.timestamp == 42.5


def test_box_label_forwarded():
    """The label in the returned TargetReading matches the detection's label."""
    det = _detector(label="car")
    box = _box("car", 0.7, cx_px=_CAM.cx, cy_px=_CAM.cy)
    reading = det.select([box], now=1.0)
    assert reading is not None
    assert reading.label == "car"
