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

import hashlib
from dataclasses import dataclass
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
# Cap correspondences fed to the essential-matrix solver. Matches are sorted
# best-first, so the top-N are the most reliable; feeding hundreds of weak
# matches just makes RANSAC slower without improving the fit.
_MAX_CORRESP = 200
# Hard ceiling on findEssentialMat RANSAC iterations in the live VO path. On
# low-inlier frames OpenCV's adaptive RANSAC can run for seconds; this bounds
# worst-case per-pair latency. The pure geometry unit tests keep the default
# (0 = unbounded) so their behaviour is unchanged.
_RANSAC_MAX_ITERS = 500


# ---------------------------------------------------------------------------
# Geometry core (testable without images)
# ---------------------------------------------------------------------------

def estimate_relative_pose(
    K: np.ndarray, pts1: np.ndarray, pts2: np.ndarray, max_iters: int = 0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Recover the relative pose between two views from point correspondences.

    Returns (R, t_unit, inlier_mask) where a point in camera-1 coords maps to
    camera-2 coords as ``Xc2 = R @ Xc1 + t_unit * s`` for unknown scale s. t_unit
    has unit norm. Raises ValueError on degenerate input.

    ``max_iters`` bounds the RANSAC iteration count passed to
    ``cv2.findEssentialMat``. The default (0) leaves OpenCV's adaptive default in
    place, so existing callers (and the geometry unit tests) are unaffected; the
    live VO path passes a finite bound to cap worst-case latency.
    """
    if len(pts1) < 5 or len(pts2) < 5:
        raise ValueError("need >= 5 correspondences for the essential matrix")
    pts1 = np.asarray(pts1, dtype=np.float64)
    pts2 = np.asarray(pts2, dtype=np.float64)
    if max_iters > 0:
        E, mask = cv2.findEssentialMat(
            pts1, pts2, K, method=cv2.RANSAC, prob=0.999, threshold=1.0, maxIters=max_iters
        )
    else:
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
    n = min(len(points_prev), len(points_curr))
    pp = np.asarray(points_prev[:n], dtype=np.float64)
    pc = np.asarray(points_curr[:n], dtype=np.float64)
    # Upper-triangle (i < j) pairwise distances — identical set of pairs as the
    # old double loop, computed in one vectorised pass.
    iu, ju = np.triu_indices(n, k=1)
    d_prev = np.linalg.norm(pp[iu] - pp[ju], axis=1)
    d_curr = np.linalg.norm(pc[iu] - pc[ju], axis=1)
    valid = d_curr > 1e-9
    if not np.any(valid):
        return 1.0
    return float(np.median(d_prev[valid] / d_curr[valid]))


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

@dataclass(frozen=True)
class _PairResult:
    """Cached geometry for one ordered frame pair (a pure function of the two
    frames and the camera). ``kind`` selects how the assembly loop advances:

    - ``"step"``  : real motion — apply (R_rel, t_unit, pts3) and keep overlap.
    - ``"hold"``  : zero-motion hover — hold pose, KEEP the previous overlap so
                    the next real step still scales against the prior 3D points.
    - ``"reset"`` : tracking loss / degenerate — hold pose, DROP the overlap.
    """

    kind: str
    R_rel: np.ndarray | None = None
    t_unit: np.ndarray | None = None
    pts3: np.ndarray | None = None


class MonocularVO(SlamBackend):
    name = "python-vo"

    def __init__(self, n_features: int = 1500) -> None:
        self._orb = cv2.ORB_create(nfeatures=n_features)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        # Per-frame ORB features and per-pair geometry, keyed by a CONTENT
        # fingerprint of the frame image (see _frame_key) — NOT frame.t. Keying
        # on the timestamp is unsafe: two genuinely different frames that happen
        # to share a timestamp (e.g. a non-advancing test clock) would collide
        # into one entry and silently corrupt the trajectory. Content keying
        # means identical frames may share an entry (correct) while distinct
        # frames never collide. The pipeline reuses one VO instance and re-runs
        # process_sequence over an overlapping sliding window every tick, so
        # without memoisation the same frame is re-detected and the same pair
        # re-solved on every call (cost grows with window size). Both caches are
        # bounded to the current window by eviction at the top of each call.
        self._feat_cache: dict[tuple, tuple] = {}
        self._pair_cache: dict[tuple[tuple, tuple], _PairResult] = {}

    def _gray(self, img: np.ndarray) -> np.ndarray:
        if img.ndim == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    def _detect(self, img: np.ndarray):
        return self._orb.detectAndCompute(self._gray(img), None)

    @staticmethod
    def _frame_key(frame: Frame) -> tuple:
        """A content fingerprint that uniquely identifies a frame by its pixels,
        independent of its timestamp. blake2b over the raw bytes is collision-
        free for any realistic frame count; the shape is folded in as a cheap
        guard. Identical images map to the same key (safe to share); distinct
        images never collide."""
        img = frame.image
        digest = hashlib.blake2b(img.tobytes(), digest_size=16).digest()
        return (img.shape, digest)

    def _features(self, frame: Frame, key: tuple):
        """ORB (keypoints, descriptors) for a frame, detected at most once per
        unique frame CONTENT for the lifetime of the current window."""
        cached = self._feat_cache.get(key)
        if cached is None:
            cached = self._detect(frame.image)
            self._feat_cache[key] = cached
        return cached

    def _match(self, des1, des2):
        if des1 is None or des2 is None:
            return []
        matches = self._matcher.match(des1, des2)
        return sorted(matches, key=lambda m: m.distance)

    def _compute_pair(
        self, frame_prev: Frame, key_prev: tuple, frame_curr: Frame, key_curr: tuple, K: np.ndarray
    ) -> _PairResult:
        """The per-pair work: match -> zero-motion gate -> tracking-loss gate ->
        relative pose -> triangulate. A pure function of the two frames (and the
        fixed camera K), so its result is safe to memoise by frame content."""
        kp1, des1 = self._features(frame_prev, key_prev)
        kp2, des2 = self._features(frame_curr, key_curr)
        matches = self._match(des1, des2)
        if len(matches) < _MIN_MATCHES:
            # Tracking loss: hold pose, keep the map coherent (no fabrication).
            return _PairResult("reset")

        # Matches are sorted best-first; cap the worst-case solver workload.
        matches = matches[:_MAX_CORRESP]
        pts1 = np.float64([kp1[m.queryIdx].pt for m in matches])
        pts2 = np.float64([kp2[m.trainIdx].pt for m in matches])

        # Zero-motion gate: if matched features barely moved, hold pose. Prevents
        # a stationary hovering drone from appearing to drift on the map due to
        # ORB feature jitter / triangulation noise.
        median_disp = float(np.median(np.linalg.norm(pts2 - pts1, axis=1)))
        if median_disp < _ZERO_MOTION_PX:
            return _PairResult("hold")

        try:
            R_rel, t_unit, inliers = estimate_relative_pose(
                K, pts1, pts2, max_iters=_RANSAC_MAX_ITERS
            )
        except ValueError:
            return _PairResult("reset")

        pts1i, pts2i = pts1[inliers], pts2[inliers]
        pts3 = triangulate(K, R_rel, t_unit, pts1i, pts2i)
        return _PairResult("step", R_rel=R_rel, t_unit=t_unit, pts3=pts3)

    def _pair_geometry(
        self, frame_prev: Frame, key_prev: tuple, frame_curr: Frame, key_curr: tuple, K: np.ndarray
    ) -> _PairResult:
        pair_key = (key_prev, key_curr)
        cached = self._pair_cache.get(pair_key)
        if cached is None:
            cached = self._compute_pair(frame_prev, key_prev, frame_curr, key_curr, K)
            self._pair_cache[pair_key] = cached
        return cached

    def _evict_outside_window(self, keys: Sequence[tuple]) -> None:
        """Bound both caches to the current window: drop any entry whose content
        key(s) are not present in the frames passed this call. Keeps the caches
        O(window) rather than O(mission)."""
        current = set(keys)
        self._feat_cache = {k: v for k, v in self._feat_cache.items() if k in current}
        self._pair_cache = {
            pk: v
            for pk, v in self._pair_cache.items()
            if pk[0] in current and pk[1] in current
        }

    def process_sequence(self, frames: Sequence[Frame], camera: CameraModel) -> Trajectory:
        K = camera.K
        traj = Trajectory()
        if len(frames) < 2:
            return traj

        # Content fingerprints for this window; cache keys derive from these, so
        # frames are identified by pixels, never by (possibly colliding) timestamp.
        keys = [self._frame_key(f) for f in frames]
        self._evict_outside_window(keys)

        # Frame 0 anchors the VO world frame.
        R_wc = np.eye(3)
        C = np.zeros(3)
        traj.poses.append(Pose(t=frames[0].t, R_wc=R_wc.copy(), position=C.copy()))

        prev_common_pts3: np.ndarray | None = None
        step_scale = 1.0

        for i in range(1, len(frames)):
            result = self._pair_geometry(frames[i - 1], keys[i - 1], frames[i], keys[i], K)

            if result.kind == "reset":
                # Tracking loss / degenerate: hold pose, drop the overlap.
                traj.poses.append(Pose(t=frames[i].t, R_wc=R_wc.copy(), position=C.copy()))
                prev_common_pts3 = None
                continue

            if result.kind == "hold":
                # Zero-motion hover: hold pose. Do NOT reset prev_common_pts3 —
                # the next real step should scale against the prior reconstruction.
                traj.poses.append(Pose(t=frames[i].t, R_wc=R_wc.copy(), position=C.copy()))
                continue

            R_rel, t_unit, curr_pts3 = result.R_rel, result.t_unit, result.pts3

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
