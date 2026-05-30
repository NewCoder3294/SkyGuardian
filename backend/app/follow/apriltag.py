"""Soldier-worn AprilTag detection + bearing/distance estimate.

Given a frame from the Tello forward camera and the tag's known physical size,
compute the tag's pose in the camera frame using PnP. The controller uses:

  - `distance_m`: range from the camera to the tag, used for fore/aft regulation.
  - `bearing_x_norm`: horizontal offset of the tag centre from the image centre,
    normalised to [-1, 1], used for yaw regulation.
  - `bearing_y_norm`: vertical offset, used for up/down regulation.

The detector is built on top of the existing slam/anchor.py primitives so the
geometry is shared with the metric-scale anchor used for Mavic SLAM. Honest
about uncertainty: returns None when no tag is in frame; never fabricates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..perception.slam.anchor import detect_tags, tag_camera_pose
from ..perception.slam.types import CameraModel


@dataclass(frozen=True)
class TagReading:
    """One frame's worth of tag observation, normalised for control use."""

    tag_id: int
    distance_m: float        # metres from camera to tag centre
    bearing_x_norm: float    # [-1, 1], +ve = tag right of centre
    bearing_y_norm: float    # [-1, 1], +ve = tag above centre (image-space inverted)
    centre_px: tuple[float, float]
    timestamp: float


def detect_soldier_tag(
    frame_bgr: np.ndarray,
    camera: CameraModel,
    tag_size_m: float,
    expected_tag_id: Optional[int],
    timestamp: float,
) -> Optional[TagReading]:
    """Detect the soldier tag in `frame_bgr`. Returns None if absent.

    `expected_tag_id` filters to a specific tag id (the soldier's badge). Pass
    None to accept any detected tag — useful during bring-up.
    """
    try:
        tags = detect_tags(frame_bgr)
    except RuntimeError:
        # pupil_apriltags not installed at runtime — no detection possible.
        return None
    if not tags:
        return None

    pick = None
    if expected_tag_id is None:
        pick = tags[0]
    else:
        for t in tags:
            if t.tag_id == expected_tag_id:
                pick = t
                break
        if pick is None:
            return None

    try:
        _, camera_centre_in_tag = tag_camera_pose(camera.K, tag_size_m, pick)
    except ValueError:
        return None

    # `tag_camera_pose` returns the camera centre in the tag frame; the tag's
    # position in the camera frame is the negation rotated back — but we only
    # need the *distance*, which is the same in either direction.
    distance_m = float(np.linalg.norm(camera_centre_in_tag))

    cx_px = float(pick.corners.mean(axis=0)[0])
    cy_px = float(pick.corners.mean(axis=0)[1])
    bearing_x = (cx_px - camera.cx) / camera.cx if camera.cx > 0 else 0.0
    bearing_y = (camera.cy - cy_px) / camera.cy if camera.cy > 0 else 0.0

    return TagReading(
        tag_id=pick.tag_id,
        distance_m=distance_m,
        bearing_x_norm=float(np.clip(bearing_x, -1.0, 1.0)),
        bearing_y_norm=float(np.clip(bearing_y, -1.0, 1.0)),
        centre_px=(cx_px, cy_px),
        timestamp=timestamp,
    )
