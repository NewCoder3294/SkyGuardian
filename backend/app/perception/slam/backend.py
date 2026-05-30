"""The SlamBackend seam. Both the pure-Python VO and the optional ORB-SLAM3
subprocess runner implement this, so the engine is swappable without touching
the rest of the mapping subsystem.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .types import CameraModel, Frame, Trajectory


class SlamBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def process_sequence(self, frames: Sequence[Frame], camera: CameraModel) -> Trajectory:
        """Estimate camera trajectory (and any sparse landmarks) from an ordered
        image sequence. Output is in arbitrary VO units (scale_known=False) until
        a metric anchor is applied downstream.
        """
        raise NotImplementedError
