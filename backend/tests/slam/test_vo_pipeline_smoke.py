"""Smoke test for the full MonocularVO image pipeline (ORB matching on real
frames). Correctness of the geometry is covered by test_vo_geometry; here we just
assert the end-to-end path runs, holds the gauge at the origin, and degrades
gracefully on a textureless frame instead of crashing.
"""
import numpy as np

from app.perception.slam.types import CameraModel, Frame
from app.perception.slam.vo import MonocularVO


def _textured(rng, w=640, h=480):
    return rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)


def test_pipeline_runs_and_anchors_origin():
    rng = np.random.default_rng(7)
    base = _textured(rng)
    # second frame: shift the content so ORB has matchable, displaced features.
    shifted = np.roll(base, shift=8, axis=1)
    frames = [Frame(image=base, t=0.0), Frame(image=shifted, t=1.0)]

    traj = MonocularVO().process_sequence(frames, CameraModel.from_resolution(640, 480))

    assert len(traj.poses) == 2
    # Frame 0 anchors the VO world frame at the origin with identity rotation.
    assert np.allclose(traj.poses[0].position, np.zeros(3))
    assert np.allclose(traj.poses[0].R_wc, np.eye(3))


def test_tracking_loss_holds_pose():
    rng = np.random.default_rng(8)
    blank = np.zeros((480, 640, 3), dtype=np.uint8)  # no features
    frames = [Frame(image=blank, t=0.0), Frame(image=blank, t=1.0)]
    traj = MonocularVO().process_sequence(frames, CameraModel.from_resolution(640, 480))
    # No fabrication: pose held at origin rather than crashing.
    assert len(traj.poses) == 2
    assert np.allclose(traj.poses[1].position, np.zeros(3))
