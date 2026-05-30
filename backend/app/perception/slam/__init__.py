"""GPS-less monocular mapping subsystem.

Default backend: MonocularVO (pure Python/OpenCV, always runs).
Optional backend: ORBSLAM3Runner (subprocess, when the C++ binary is built).
Metric scale + origin: AprilTag anchor (anchor.py).
Map + world-model bridge: LocalMap.
"""
from .anchor import (
    TagObservation,
    detect_tags,
    metric_scale_from_tag,
    tag_camera_pose,
    tag_object_points,
)
from .backend import SlamBackend
from .local_map import LocalMap
from .orbslam3_runner import ORBSLAM3Runner, orbslam_available
from .types import CameraModel, Frame, Landmark, Pose, Trajectory
from .vo import (
    MonocularVO,
    estimate_relative_pose,
    integrate_step,
    relative_scale,
    triangulate,
)

__all__ = [
    "SlamBackend", "MonocularVO", "ORBSLAM3Runner", "orbslam_available",
    "LocalMap", "CameraModel", "Frame", "Pose", "Landmark", "Trajectory",
    "TagObservation", "tag_object_points", "tag_camera_pose",
    "metric_scale_from_tag", "detect_tags",
    "estimate_relative_pose", "triangulate", "relative_scale", "integrate_step",
]
