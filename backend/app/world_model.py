"""The world model: the single source of truth for all entities.

Producers (perception, follow controller, manual) upsert entities. The world
model alone owns the lifecycle: it demotes active -> stale -> lost as each
entity's ttl lapses relative to the clock. Producers never set `lost`.
"""
from __future__ import annotations

from .clock import Clock, RealClock
from .contracts import Entity, EntityStatus


class WorldModel:
    def __init__(self, clock: Clock | None = None, stale_factor: float = 1.0) -> None:
        self._clock = clock or RealClock()
        self._entities: dict[str, Entity] = {}
        # An entity goes stale after ttl_s and lost after ttl_s * lost_factor.
        self._stale_factor = stale_factor
        self._lost_factor = 3.0

    def upsert(self, entity: Entity) -> None:
        """Insert or replace an entity by id. Always (re)admitted as active."""
        entity = entity.model_copy(update={"status": EntityStatus.ACTIVE})
        self._entities[entity.id] = entity

    def remove(self, entity_id: str) -> None:
        self._entities.pop(entity_id, None)

    def clear(self) -> None:
        """Drop every entity in one go. Producers will refill on the next
        perception tick / device_location upsert / follow loop iteration —
        this is for the operator's reset-the-map button, not a teardown."""
        self._entities.clear()

    def _age(self, entity: Entity, now: float) -> float:
        return now - entity.timestamp

    def _evaluate_status(self, entity: Entity, now: float) -> EntityStatus:
        age = self._age(entity, now)
        if age > entity.ttl_s * self._lost_factor:
            return EntityStatus.LOST
        if age > entity.ttl_s * self._stale_factor:
            return EntityStatus.STALE
        return EntityStatus.ACTIVE

    def tick(self) -> None:
        """Advance lifecycle. Demote stale/lost; drop entities long past lost."""
        now = self._clock.now()
        drop: list[str] = []
        for eid, entity in self._entities.items():
            status = self._evaluate_status(entity, now)
            if status != entity.status:
                self._entities[eid] = entity.model_copy(update={"status": status})
            # Garbage-collect entities that have been lost for a full extra window.
            if self._age(entity, now) > entity.ttl_s * (self._lost_factor + 1.0):
                drop.append(eid)
        for eid in drop:
            self._entities.pop(eid, None)

    def snapshot(self) -> list[Entity]:
        """Current entities with lifecycle applied. Pure read (calls tick first)."""
        self.tick()
        return list(self._entities.values())
