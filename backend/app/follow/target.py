"""Target sensing for the autonomous approach behavior.

Mirrors apriltag.TagReading, but the target is a YOLO-detected object in the
Tello's OWN camera frame (not the Mavic world frame): bearing from the box
centre, range estimated from apparent box size. A Protocol lets tests inject
scripted readings without any model or hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


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
