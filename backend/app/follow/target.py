"""Target sensing for the autonomous approach behavior.

Mirrors apriltag.TagReading, but the target is a YOLO-detected object in the
Tello's OWN camera frame (not the Mavic world frame): bearing from the box
centre, range estimated from apparent box size. A Protocol lets tests inject
scripted readings without any model or hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol

from ..perception.slam.types import CameraModel


@dataclass(frozen=True)
class TargetReading:
    """One frame's observation of the approach target, normalised for control."""
    label: str
    distance_m: float
    bearing_x_norm: float
    bearing_y_norm: float
    confidence: float
    timestamp: float


class TargetDetector(Protocol):
    def detect(self, jpeg: Optional[bytes], now: float) -> Optional[TargetReading]:
        """Return the current target reading, or None if not seen this frame."""
        ...


def _clip(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else (hi if value > hi else value)


class BoxTargetDetector:
    """Convert YOLO detection boxes (in the Tello's camera frame) into a
    TargetReading using camera intrinsics and the pinhole range formula.

    Geometry (all pixel coordinates):
      bearing_x_norm = clip((cx_px - camera.cx) / camera.cx, -1, 1)
                       >0 means target is to the RIGHT of centre
      bearing_y_norm = clip((camera.cy - cy_px) / camera.cy, -1, 1)
                       >0 means target is ABOVE centre (image y inverted)
      distance_m     = camera.fy * nominal_height_m / h_px   (pinhole)

    Construction args:
      camera            — CameraModel with fx/fy/cx/cy (e.g. from_resolution(960,720))
      target_label      — YOLO class name to follow (case-insensitive)
      nominal_height_m  — real-world height of target class (metres); e.g. 1.7 for a person
    """

    def __init__(
        self,
        camera: CameraModel,
        target_label: str,
        nominal_height_m: float,
    ) -> None:
        self._camera = camera
        self._target_label = target_label.lower()
        self._nominal_height_m = float(nominal_height_m)

    def select(self, boxes: list, now: float) -> Optional[TargetReading]:
        """Return a TargetReading for the highest-confidence matching box,
        or None if no matching box is present or the box height is degenerate."""
        camera = self._camera

        # Filter to boxes whose label matches (case-insensitive).
        matches = [b for b in boxes if b.label.lower() == self._target_label]
        if not matches:
            return None

        # Pick the highest-confidence match.
        best = max(matches, key=lambda b: b.confidence)

        # Guard against degenerate box height (avoid divide-by-zero).
        if best.h_px <= 0:
            return None

        # Pinhole range estimate from apparent object height.
        distance_m = camera.fy * self._nominal_height_m / best.h_px

        # Normalised bearing: positive x = right, positive y = up.
        bearing_x_norm = _clip((best.cx_px - camera.cx) / camera.cx, -1.0, 1.0)
        bearing_y_norm = _clip((camera.cy - best.cy_px) / camera.cy, -1.0, 1.0)

        return TargetReading(
            label=best.label,
            distance_m=distance_m,
            bearing_x_norm=bearing_x_norm,
            bearing_y_norm=bearing_y_norm,
            confidence=best.confidence,
            timestamp=now,
        )


class SyntheticTargetDetector:
    """Deterministic detector that replays a scripted list of readings, one per
    detect() call. Used by the approach tests; no model, no hardware."""
    def __init__(self, script: List[Optional[TargetReading]]) -> None:
        self._script = list(script)
        self._i = 0

    def detect(self, jpeg: Optional[bytes], now: float) -> Optional[TargetReading]:
        if self._i >= len(self._script):
            return None
        r = self._script[self._i]
        self._i += 1
        return r
