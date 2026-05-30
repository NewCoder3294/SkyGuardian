"""AprilTag metric anchor — how a GPS-less map gets honest metres and an origin.

Monocular VO recovers structure only up to an unknown scale. A tag of KNOWN
physical size, observed at the launch area, supplies the missing metric reference:

  - `tag_camera_pose` solves the tag's pose in a camera frame (metres) via PnP.
  - `metric_scale_from_tag` observes the tag from two frames whose VO positions are
    known, and returns the VO-unit -> metre scale factor: the tag gives a metric
    baseline between the two cameras, VO gives the same baseline in its own units.

The detector adapter (pupil-apriltags) is imported lazily so the geometry is
testable and importable without the native library present.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class TagObservation:
    """A single tag detection: the four image corners (px) in a fixed order and
    the tag id. Corner order matches the 3D model in `tag_object_points`."""

    tag_id: int
    corners: np.ndarray  # (4, 2) image points, order: TL, TR, BR, BL


def tag_object_points(size_m: float) -> np.ndarray:
    """3D model of a square tag of edge `size_m`, centred at the origin, z=0.
    Order matches TagObservation.corners (TL, TR, BR, BL)."""
    h = size_m / 2.0
    return np.array(
        [[-h, h, 0.0], [h, h, 0.0], [h, -h, 0.0], [-h, -h, 0.0]],
        dtype=np.float64,
    )


def tag_camera_pose(
    K: np.ndarray, size_m: float, obs: TagObservation
) -> tuple[np.ndarray, np.ndarray]:
    """Solve the camera centre and orientation relative to the tag (metres).

    Returns (R_tc, C_in_tag) where R_tc is tag->camera rotation and C_in_tag is the
    camera centre expressed in the tag frame. Raises ValueError if PnP fails.
    """
    obj = tag_object_points(size_m)
    img = np.asarray(obs.corners, dtype=np.float64).reshape(4, 2)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        raise ValueError("tag PnP failed")
    R_ct, _ = cv2.Rodrigues(rvec)  # tag-frame point -> camera-frame
    C_in_tag = (-R_ct.T @ tvec).reshape(3)  # camera centre in the tag frame
    return R_ct.T, C_in_tag


def metric_scale_from_tag(
    K: np.ndarray,
    size_m: float,
    obs_a: TagObservation,
    vo_C_a: np.ndarray,
    obs_b: TagObservation,
    vo_C_b: np.ndarray,
) -> float:
    """VO-unit -> metre scale from the same tag seen in two frames.

    metric baseline = distance between the two camera centres in the tag frame.
    vo baseline     = distance between the two camera centres in VO units.
    scale = metric / vo. Raises ValueError if the VO baseline is ~0 (no motion).
    """
    _, C_a_metric = tag_camera_pose(K, size_m, obs_a)
    _, C_b_metric = tag_camera_pose(K, size_m, obs_b)
    metric_baseline = float(np.linalg.norm(C_b_metric - C_a_metric))
    vo_baseline = float(np.linalg.norm(np.asarray(vo_C_b) - np.asarray(vo_C_a)))
    if vo_baseline < 1e-9:
        raise ValueError("VO baseline ~0; move the camera between tag observations")
    return metric_baseline / vo_baseline


# ---------------------------------------------------------------------------
# Detector adapter (lazy import — native lib only needed at runtime on real frames)
# ---------------------------------------------------------------------------

def detect_tags(image: np.ndarray) -> list[TagObservation]:
    """Detect AprilTags in an image. Imports pupil_apriltags lazily so this module
    stays importable/testable without the native library installed."""
    try:
        from pupil_apriltags import Detector
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "pupil-apriltags not installed; needed only for live tag detection"
        ) from exc
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    det = Detector(families="tag36h11")
    out: list[TagObservation] = []
    for r in det.detect(gray):
        # pupil order is (lb, rb, rt, lt); reorder to TL, TR, BR, BL.
        c = np.asarray(r.corners, dtype=np.float64)
        reordered = np.array([c[3], c[2], c[1], c[0]])
        out.append(TagObservation(tag_id=int(r.tag_id), corners=reordered))
    return out
