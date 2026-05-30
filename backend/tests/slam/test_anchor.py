import numpy as np
import pytest

from app.perception.slam.anchor import (
    TagObservation,
    metric_scale_from_tag,
    tag_camera_pose,
    tag_object_points,
)
from app.perception.slam.types import CameraModel
from tests.slam.synth import project

K = CameraModel.from_resolution(1280, 720).K
TAG_SIZE = 0.20  # 20 cm tag


def _observe(C: np.ndarray, R_wc: np.ndarray = None) -> TagObservation:
    """Project a tag (at world origin, in the z=0 plane) into a camera at C."""
    R_wc = np.eye(3) if R_wc is None else R_wc
    corners3d = tag_object_points(TAG_SIZE)
    px = project(K, R_wc, C, corners3d)
    return TagObservation(tag_id=0, corners=px)


def test_tag_camera_pose_recovers_camera_centre():
    C = np.array([0.0, 0.0, -2.0])  # 2 m back from the tag, looking +z
    obs = _observe(C)
    _, C_in_tag = tag_camera_pose(K, TAG_SIZE, obs)
    assert np.allclose(C_in_tag, C, atol=1e-3)


def test_metric_scale_from_tag_recovers_known_scale():
    # Two camera centres in real metres; VO sees the same up to factor 1/k.
    C_a = np.array([-0.5, 0.0, -2.0])
    C_b = np.array([0.5, 0.0, -2.0])  # metric baseline = 1.0 m
    k = 3.0  # VO unit = metre / k
    vo_C_a = C_a / k
    vo_C_b = C_b / k

    scale = metric_scale_from_tag(K, TAG_SIZE, _observe(C_a), vo_C_a, _observe(C_b), vo_C_b)
    assert scale == pytest.approx(k, rel=1e-3)


def test_zero_vo_baseline_raises():
    C = np.array([0.0, 0.0, -2.0])
    with pytest.raises(ValueError):
        metric_scale_from_tag(K, TAG_SIZE, _observe(C), np.zeros(3), _observe(C), np.zeros(3))
