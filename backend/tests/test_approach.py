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
