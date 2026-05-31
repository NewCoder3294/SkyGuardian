import numpy as np

from app.contracts import DetectionBox, Vec3


class _SpyRecorder:
    def __init__(self):
        self.calls = []

    def observe(self, frame, boxes, pose, t, *, source, image_w, image_h):
        self.calls.append((boxes, pose, t, source, image_w, image_h))
        return True


def test_pipeline_emit_capture_calls_recorder():
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
