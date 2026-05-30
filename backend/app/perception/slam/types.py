"""Core types for the GPS-less mapping subsystem.

Frame convention (local map): right-handed, metres, anchored at the launch point
(the first AprilTag anchor observation) = origin (0, 0, 0). No GPS, no lat/lng.

Camera/world convention: a 3D point in camera coordinates ``Xc`` maps to the local
world frame as ``Xw = R_wc @ Xc + C``, where ``R_wc`` is the camera->world rotation
and ``C`` is the camera centre in the local frame. Equivalently the projection uses
``[R_cw | t_cw]`` with ``R_cw = R_wc.T`` and ``t_cw = -R_wc.T @ C``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class CameraModel:
    """Pinhole intrinsics. No distortion (Tello/Mavic streams are close enough
    after the stream resamples; calibrate per-camera for production)."""

    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def from_resolution(cls, width: int, height: int, focal_factor: float = 0.78) -> "CameraModel":
        """Reasonable default intrinsics when no calibration is available.
        focal_factor 0.78 * max(dim) matches the prior rig's empirical guess.
        """
        f = max(width, height) * focal_factor
        return cls(fx=f, fy=f, cx=width / 2.0, cy=height / 2.0)

    @property
    def K(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )


@dataclass
class Frame:
    """A single image with a source timestamp (unix seconds)."""

    image: np.ndarray  # HxW or HxWx3, uint8
    t: float


@dataclass
class Pose:
    """Camera pose in the local frame at time ``t``.

    R_wc: 3x3 camera->world rotation. position: camera centre (metres, local frame).
    scale_known is False while the trajectory is still in arbitrary VO units.
    """

    t: float
    R_wc: np.ndarray  # (3, 3)
    position: np.ndarray  # (3,)
    scale_known: bool = False

    def scaled(self, scale: float, origin: np.ndarray) -> "Pose":
        """Return this pose re-expressed in the metric local frame: multiply the
        position by the metric scale and shift so ``origin`` becomes (0,0,0)."""
        return Pose(
            t=self.t,
            R_wc=self.R_wc.copy(),
            position=(self.position - origin) * scale,
            scale_known=True,
        )


@dataclass
class Landmark:
    """A sparse 3D map point in the local frame."""

    position: np.ndarray  # (3,)
    confidence: float = 0.5
    label: str | None = None


@dataclass
class Trajectory:
    poses: list[Pose] = field(default_factory=list)
    landmarks: list[Landmark] = field(default_factory=list)
