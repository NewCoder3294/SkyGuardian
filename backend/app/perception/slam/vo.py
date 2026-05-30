"""Pure-Python monocular visual odometry (default SLAM backend).

The geometry core (relative pose, triangulation, relative-scale recovery,
trajectory assembly) is plain numpy/OpenCV and is unit-tested with synthetic
3D->2D correspondences — no images required. The MonocularVO class adds ORB
feature matching on top of that core for real frames.

Known limitation (honest): two-view VO drifts and has no loop closure. Absolute
metric scale comes from the AprilTag anchor (see anchor.py); inter-frame scale is
propagated by triangulation. For bundle-adjusted accuracy, swap in the ORB-SLAM3
backend behind the same SlamBackend interface.
"""
from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from .backend import SlamBackend
from .types import CameraModel, Frame, Landmark, Pose, Trajectory

_MIN_MATCHES = 12
# Median feature displacement (pixels) below which we assume the camera was
# stationary between two frames. Monocular VO has no zero-motion detector by
# default, so feature noise on a hovering drone accumulates into fake drift.
_ZERO_MOTION_PX = 1.5


# ---------------------------------------------------------------------------
# Geometry core (testable without images)
# ---------------------------------------------------------------------------

def estimate_relative_pose(
    K: np.ndarray, pts1: np.ndarray, pts2: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Recover the relative pose between two views from point correspondences.

    Returns (R, t_unit, inlier_mask) where a point in camera-1 coords maps to
    camera-2 coords as ``Xc2 = R @ Xc1 + t_unit * s`` for unknown scale s. t_unit
    has unit norm. Raises ValueError on degenerate input.
    """
    if len(pts1) < 5 or len(pts2) < 5:
        raise ValueError("need >= 5 correspondences for the essential matrix")
    pts1 = np.asarray(pts1, dtype=np.float64)
    pts2 = np.asarray(pts2, dtype=np.float64)
    E, mask = cv2.findEssentialMat(pts1, pts2, K, method=cv2.RANSAC, prob=0.999, threshold=1.0)
    if E is None or E.shape != (3, 3):
        raise ValueError("essential matrix estimation failed")
    _, R, t, mask_pose = cv2.recoverPose(E, pts1, pts2, K, mask=mask)
    t_unit = t.reshape(3) / (np.linalg.norm(t) + 1e-12)
    return R, t_unit, (mask_pose.ravel() > 0)


def triangulate(
    K: np.ndarray, R: np.ndarray, t: np.ndarray, pts1: np.ndarray, pts2: np.ndarray
) -> np.ndarray:
    """Triangulate 3D points in camera-1 coordinates given the relative pose
    (R, t) of camera 2 w.r.t. camera 1. Returns (N, 3) array. Returns an empty
    (0, 3) array when there are too few correspondences."""
    pts1 = np.asarray(pts1, dtype=np.float64)
    pts2 = np.asarray(pts2, dtype=np.float64)
    if pts1.ndim != 2 or pts1.shape[0] < 1 or pts1.shape != pts2.shape:
        return np.empty((0, 3), dtype=np.float64)
    P1 = (K @ np.hstack([np.eye(3), np.zeros((3, 1))])).astype(np.float64)
    P2 = (K @ np.hstack([R, t.reshape(3, 1)])).astype(np.float64)
    # cv2.triangulatePoints requires contiguous 2xN float64 matrices; a
    # transposed view from numpy is non-contiguous and trips error -210.
    pts1_2xN = np.ascontiguousarray(pts1.T)
    pts2_2xN = np.ascontiguousarray(pts2.T)
    pts4 = cv2.triangulatePoints(P1, P2, pts1_2xN, pts2_2xN)
    pts3 = (pts4[:3] / pts4[3]).T
    return pts3


def relative_scale(points_prev: np.ndarray, points_curr: np.ndarray) -> float:
    """Estimate the scale of the current step relative to the previous one.

    points_prev / points_curr are the SAME tracked 3D landmarks triangulated in
    the previous pair and the current pair (each with a unit-norm translation).
    The ratio of inter-point distances is the relative translation scale. Uses a
    median over all point pairs for robustness. Returns 1.0 if undetermined.
    """
    if len(points_prev) < 2 or len(points_curr) < 2:
        return 1.0
    ratios: list[float] = []
    n = min(len(points_prev), len(points_curr))
    for i in range(n):
        for j in range(i + 1, n):
            d_prev = np.linalg.norm(points_prev[i] - points_prev[j])
            d_curr = np.linalg.norm(points_curr[i] - points_curr[j])
            if d_curr > 1e-9:
                ratios.append(d_prev / d_curr)
    if not ratios:
        return 1.0
    return float(np.median(ratios))


def integrate_step(
    R_wc_prev: np.ndarray, C_prev: np.ndarray, R_rel: np.ndarray, t_unit: np.ndarray, scale: float
) -> tuple[np.ndarray, np.ndarray]:
    """Advance a global camera pose by one relative step.

    (R_rel, t_unit) is camera_prev->camera_curr. Returns (R_wc_curr, C_curr) in the
    same (VO-unit) world frame, with the step translation magnitude = ``scale``.
    """
    R_wc_curr = R_wc_prev @ R_rel.T
    C_curr = C_prev - R_wc_curr @ (t_unit * scale)
    return R_wc_curr, C_curr


# ---------------------------------------------------------------------------
# Image-feature VO backend
# ---------------------------------------------------------------------------

class MonocularVO(SlamBackend):
    name = "python-vo"

    def __init__(self, n_features: int = 1500) -> None:
        self._orb = cv2.ORB_create(nfeatures=n_features)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    def _gray(self, img: np.ndarray) -> np.ndarray:
        if img.ndim == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    def _detect(self, img: np.ndarray):
        return self._orb.detectAndCompute(self._gray(img), None)

    def _match(self, des1, des2):
        if des1 is None or des2 is None:
            return []
        matches = self._matcher.match(des1, des2)
        return sorted(matches, key=lambda m: m.distance)

    def process_sequence(self, frames: Sequence[Frame], camera: CameraModel) -> Trajectory:
        K = camera.K
        traj = Trajectory()
        if len(frames) < 2:
            return traj

        feats = [self._detect(f.image) for f in frames]

        # Frame 0 anchors the VO world frame.
        R_wc = np.eye(3)
        C = np.zeros(3)
        traj.poses.append(Pose(t=frames[0].t, R_wc=R_wc.copy(), position=C.copy()))

        prev_common_pts3: np.ndarray | None = None
        step_scale = 1.0

        for i in range(1, len(frames)):
            kp1, des1 = feats[i - 1]
            kp2, des2 = feats[i]
            matches = self._match(des1, des2)
            if len(matches) < _MIN_MATCHES:
                # Tracking loss: hold pose, keep the map coherent (no fabrication).
                traj.poses.append(Pose(t=frames[i].t, R_wc=R_wc.copy(), position=C.copy()))
                prev_common_pts3 = None
                continue

            pts1 = np.float64([kp1[m.queryIdx].pt for m in matches])
            pts2 = np.float64([kp2[m.trainIdx].pt for m in matches])

            # Zero-motion gate: if matched features barely moved, hold pose.
            # Prevents a stationary hovering drone from appearing to drift on
            # the map due to ORB feature jitter / triangulation noise.
            median_disp = float(np.median(np.linalg.norm(pts2 - pts1, axis=1)))
            if median_disp < _ZERO_MOTION_PX:
                traj.poses.append(Pose(t=frames[i].t, R_wc=R_wc.copy(), position=C.copy()))
                # Do not reset prev_common_pts3 — we want the next real motion
                # step to scale relative to the prior reconstruction.
                continue

            try:
                R_rel, t_unit, inliers = estimate_relative_pose(K, pts1, pts2)
            except ValueError:
                traj.poses.append(Pose(t=frames[i].t, R_wc=R_wc.copy(), position=C.copy()))
                prev_common_pts3 = None
                continue

            pts1i, pts2i = pts1[inliers], pts2[inliers]
            curr_pts3 = triangulate(K, R_rel, t_unit, pts1i, pts2i)

            # Propagate scale from the overlap with the previous step.
            if prev_common_pts3 is not None and len(prev_common_pts3) >= 2:
                n = min(len(prev_common_pts3), len(curr_pts3))
                step_scale *= relative_scale(prev_common_pts3[:n], curr_pts3[:n])

            R_wc, C = integrate_step(R_wc, C, R_rel, t_unit, step_scale)
            traj.poses.append(Pose(t=frames[i].t, R_wc=R_wc.copy(), position=C.copy()))

            # Record a few landmarks in the world frame for the map view.
            for p in curr_pts3[:: max(1, len(curr_pts3) // 20)]:
                world_p = R_wc_prev_dot(traj.poses[i - 1], p)
                traj.landmarks.append(Landmark(position=world_p, confidence=0.4))
            prev_common_pts3 = curr_pts3

        return traj


def R_wc_prev_dot(prev_pose: Pose, point_cam: np.ndarray) -> np.ndarray:
    """Map a point given in the previous camera frame into the world frame."""
    return prev_pose.R_wc @ np.asarray(point_cam, dtype=np.float64) + prev_pose.position
