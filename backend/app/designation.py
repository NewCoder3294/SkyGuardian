"""Target designation — pure, mission-consistent situational awareness.

The recon Mavic feed already produces YOLO detection entities (in the world
model) and the intel reasoner produces a threat level. The Designator ranks the
current detections and picks the single highest-priority one to *designate* —
mark for the operator. It commands nothing and flies nothing: designation is
read-only situational awareness, on-mission ("recon only, no targeting").

Pure and deterministic given its inputs (no I/O, no clock) so it is trivially
unit-testable. The server turns a Designation into a `designated_target` world
entity that rides the existing broadcast to both clients.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .contracts import Entity, EntitySource, EntityStatus, Vec3

# High-value classes worth designating on a recon feed. Override via the server
# if the deployed YOLO vocabulary differs.
DEFAULT_HIGH_VALUE = frozenset(
    {"person", "car", "truck", "vehicle", "backpack", "motorcycle", "bus"}
)


@dataclass(frozen=True)
class Designation:
    """The chosen target: which detection, where, and the prevailing threat."""

    entity_id: str
    position: Vec3
    label: str
    confidence: float
    threat_level: str


class Designator:
    def __init__(self, high_value: frozenset[str] = DEFAULT_HIGH_VALUE) -> None:
        self._high_value = high_value

    def select(
        self, entities: list[Entity], threat_level: str = "unknown"
    ) -> Optional[Designation]:
        """Pick the top-priority recon detection, or None if there is no candidate.

        Candidates: ACTIVE entities sourced from YOLO whose label is in the
        high-value set. Ranked by confidence (desc); ties broken by proximity to
        the launch origin (closer first) for a deterministic, stable choice.

        The ACTIVE filter prevents promoting a STALE/LOST detection (perception
        last refreshed up to ~12 s ago) to the operator's designated target.
        """
        candidates = [
            e
            for e in entities
            if e.source == EntitySource.YOLO
            and e.status == EntityStatus.ACTIVE
            and e.label is not None
            and e.label.lower() in self._high_value
        ]
        if not candidates:
            return None

        def _range(e: Entity) -> float:
            p = e.position
            return (p.x * p.x + p.y * p.y + p.z * p.z) ** 0.5

        # Highest confidence first; nearer to launch breaks ties; id last for
        # full determinism when confidence and range are identical.
        best = min(candidates, key=lambda e: (-e.confidence, _range(e), e.id))
        return Designation(
            entity_id=best.id,
            position=best.position,
            label=best.label or best.id,
            confidence=best.confidence,
            threat_level=threat_level,
        )
