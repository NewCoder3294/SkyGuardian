"""LocalMap — the GPS-less map: a metric trajectory + sparse landmarks anchored
at the launch point, and the bridge into the world model.

It takes a raw (VO-unit) Trajectory plus a metric scale from the AprilTag anchor,
re-expresses everything in metres with the launch point at the origin, and emits
world-model entities so the Mavic, the anchor tag, and landmarks appear live on
both clients — with no GPS anywhere.
"""
from __future__ import annotations

import numpy as np

from ...contracts import Entity, EntitySource, EntityType, Vec3
from .types import Landmark, Pose, Trajectory


class LocalMap:
    def __init__(self) -> None:
        self._poses: list[Pose] = []
        self._landmarks: list[Landmark] = []
        self._scale: float | None = None
        self._origin = np.zeros(3)
        self._anchored = False

    @property
    def anchored(self) -> bool:
        return self._anchored

    @property
    def metric(self) -> bool:
        """True once a metric scale has been applied (positions are real metres)."""
        return self._scale is not None

    def set_anchor(self, scale: float, origin: np.ndarray | None = None) -> None:
        """Fix the metric scale (VO units -> metres) and the local-frame origin
        (the launch point). Call once the AprilTag anchor has been resolved."""
        if scale <= 0:
            raise ValueError("scale must be positive")
        self._scale = scale
        self._origin = np.zeros(3) if origin is None else np.asarray(origin, dtype=np.float64)
        self._anchored = True

    def ingest(self, traj: Trajectory) -> None:
        self._poses = list(traj.poses)
        self._landmarks = list(traj.landmarks)

    def _to_metric(self, position: np.ndarray) -> np.ndarray:
        scale = self._scale if self._scale is not None else 1.0
        return (np.asarray(position, dtype=np.float64) - self._origin) * scale

    def camera_position(self) -> np.ndarray | None:
        """Latest Mavic camera centre in the metric local frame, or None."""
        if not self._poses:
            return None
        return self._to_metric(self._poses[-1].position)

    # --- world-model integration -------------------------------------------

    def _vec3(self, p: np.ndarray) -> Vec3:
        return Vec3(x=float(p[0]), y=float(p[1]), z=float(p[2]))

    def to_entities(self, t: float, tag_position: np.ndarray | None = None) -> list[Entity]:
        """Build world-model entities for the current map state.

        - the Mavic camera as a `drone` entity (source=slam)
        - the anchor tag as a `poi` launch marker, if provided
        - sparse landmarks as low-confidence `object` entities
        """
        entities: list[Entity] = []
        cam = self.camera_position()
        if cam is not None:
            entities.append(Entity(
                id="mavic_cam", type=EntityType.DRONE, position=self._vec3(cam),
                confidence=1.0 if self.metric else 0.5, timestamp=t,
                source=EntitySource.SLAM, label="leader", ttl_s=3.0,
            ))
        if tag_position is not None:
            entities.append(Entity(
                id="anchor_tag", type=EntityType.POI, position=self._vec3(self._to_metric(tag_position)),
                confidence=1.0, timestamp=t, source=EntitySource.SLAM,
                # 10s TTL so the anchor disappears from the dashboard when SLAM
                # stops refreshing it (e.g. the operator switched video source).
                # As long as the tag is visible, the entity stays fresh.
                label="launch anchor", ttl_s=10.0,
            ))
        for i, lm in enumerate(self._landmarks):
            entities.append(Entity(
                id=f"lm_{i}", type=EntityType.OBJECT, position=self._vec3(self._to_metric(lm.position)),
                confidence=lm.confidence, timestamp=t, source=EntitySource.SLAM,
                label=lm.label, ttl_s=10.0,
            ))
        return entities

    def integrate(self, world_model, t: float, tag_position: np.ndarray | None = None) -> int:
        """Upsert all current entities into a WorldModel. Returns the count."""
        ents = self.to_entities(t, tag_position=tag_position)
        for e in ents:
            world_model.upsert(e)
        return len(ents)
