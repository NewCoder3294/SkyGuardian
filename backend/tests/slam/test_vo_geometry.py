import numpy as np
import pytest

from app.perception.slam.types import CameraModel
from app.perception.slam.vo import (
    estimate_relative_pose,
    integrate_step,
    relative_scale,
    triangulate,
)
from tests.slam.synth import in_front, point_cloud, project


def _cam():
    return CameraModel.from_resolution(1280, 720)


def test_relative_pose_recovers_translation_direction():
    rng = np.random.default_rng(0)
    K = _cam().K
    Xw = point_cloud(rng)
    R0, C0 = np.eye(3), np.zeros(3)
    C1 = np.array([0.4, 0.0, 0.0])  # pure sideways translation, known
    R1 = np.eye(3)

    pts0 = project(K, R0, C0, Xw)
    pts1 = project(K, R1, C1, Xw)

    R_rel, t_unit, inliers = estimate_relative_pose(K, pts0, pts1)

    # Rotation is identity; integrating with the true baseline recovers C1.
    R_wc, C = integrate_step(R0, C0, R_rel, t_unit, scale=np.linalg.norm(C1))
    assert np.allclose(R_wc, np.eye(3), atol=1e-6)
    assert np.allclose(C, C1, atol=1e-6)
    assert inliers.sum() >= 30


def test_relative_pose_recovers_rotation():
    rng = np.random.default_rng(1)
    K = _cam().K
    Xw = point_cloud(rng)
    # camera 1 yawed ~8 degrees
    a = np.deg2rad(8.0)
    R1 = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    C1 = np.array([0.3, 0.05, 0.0])

    pts0 = project(K, np.eye(3), np.zeros(3), Xw)
    pts1 = project(K, R1, C1, Xw)
    assert np.all(in_front(R1, C1, Xw) > 0)

    R_rel, t_unit, _ = estimate_relative_pose(K, pts0, pts1)
    R_wc, _ = integrate_step(np.eye(3), np.zeros(3), R_rel, t_unit, scale=np.linalg.norm(C1))
    assert np.allclose(R_wc, R1, atol=1e-3)


def test_relative_scale_recovers_baseline_ratio():
    rng = np.random.default_rng(2)
    K = _cam().K
    Xw = point_cloud(rng)
    # three colinear camera centres; second step twice the first.
    C0 = np.zeros(3)
    C1 = np.array([0.3, 0.0, 0.0])
    C2 = np.array([0.9, 0.0, 0.0])  # step1 baseline 0.3, step2 baseline 0.6 -> ratio 2.0
    R = np.eye(3)

    p0 = project(K, R, C0, Xw)
    p1 = project(K, R, C1, Xw)
    p2 = project(K, R, C2, Xw)

    R01, t01, in01 = estimate_relative_pose(K, p0, p1)
    pts3_a = triangulate(K, R01, t01, p0[in01], p1[in01])
    R12, t12, in12 = estimate_relative_pose(K, p1, p2)
    pts3_b = triangulate(K, R12, t12, p1[in12], p2[in12])

    n = min(len(pts3_a), len(pts3_b))
    ratio = relative_scale(pts3_a[:n], pts3_b[:n])
    # relative_scale returns b_curr / b_prev = 0.6 / 0.3 = 2.0
    assert ratio == pytest.approx(2.0, rel=0.05)


def test_degenerate_input_raises():
    K = _cam().K
    with pytest.raises(ValueError):
        estimate_relative_pose(K, np.zeros((3, 2)), np.zeros((3, 2)))
