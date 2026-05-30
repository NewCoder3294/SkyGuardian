"""Fake-entity injector so the dashboard and mobile app can be built with zero
hardware. Produces a soldier, the Tello drone, and a couple of POIs/hazards
drifting around the local frame. Swap out for real perception/follow producers.
"""
from __future__ import annotations

import math

from .clock import Clock, RealClock
from .contracts import Entity, EntitySource, EntityType, Vec3
from .world_model import WorldModel


class MockSource:
    def __init__(self, world: WorldModel, clock: Clock | None = None) -> None:
        self._world = world
        self._clock = clock or RealClock()

    def step(self) -> None:
        t = self._clock.now()
        # Soldier walks a slow circle; drone station-keeps just behind.
        angle = t * 0.3
        soldier = Vec3(x=3.0 * math.cos(angle), y=3.0 * math.sin(angle), z=0.0)
        drone = Vec3(x=soldier.x * 0.85, y=soldier.y * 0.85, z=1.2)

        self._world.upsert(Entity(
            id="soldier_1", type=EntityType.SOLDIER, position=soldier,
            confidence=1.0, timestamp=t, source=EntitySource.MANUAL, label="operator",
        ))
        self._world.upsert(Entity(
            id="tello_1", type=EntityType.DRONE, position=drone,
            confidence=1.0, timestamp=t, source=EntitySource.FOLLOW, label="companion",
        ))
        self._world.upsert(Entity(
            id="poi_door", type=EntityType.POI, position=Vec3(x=-4.0, y=2.0, z=0.0),
            confidence=0.82, timestamp=t, source=EntitySource.YOLO, label="doorway",
        ))
        self._world.upsert(Entity(
            id="hazard_1", type=EntityType.HAZARD, position=Vec3(x=1.5, y=-3.5, z=0.0),
            confidence=0.66, timestamp=t, source=EntitySource.YOLO, label="debris",
        ))
