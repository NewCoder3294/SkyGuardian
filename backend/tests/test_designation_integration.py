"""Integration test for the designation wiring in the broadcast path.

Exercises server._apply_designation against a real WorldModel: a high-value YOLO
detection becomes a `designated_target` entity; with no candidate the prior mark
ages out via TTL.
"""
from __future__ import annotations

import app.server as server
from app.contracts import Entity, EntitySource, EntityType, Vec3


def _yolo(id: str, label: str, conf: float = 0.9) -> Entity:
    return Entity(
        id=id, type=EntityType.OBJECT, position=Vec3(x=2.0, y=1.0, z=0.0),
        confidence=conf, timestamp=server.clock.now(), source=EntitySource.YOLO,
        label=label, ttl_s=5.0,
    )


def _ids(world) -> set[str]:
    return {e.id for e in world.snapshot()}


def test_apply_designation_emits_designated_target():
    # Clear any residual state, then add a high-value recon detection.
    server.world.remove("designated_target")
    server.world.upsert(_yolo("yolo_person_9", "person"))

    server._apply_designation(server.clock.now())

    snap = {e.id: e for e in server.world.snapshot()}
    assert "designated_target" in snap
    dt = snap["designated_target"]
    assert dt.label == "DESIGNATED: person"
    assert dt.type is EntityType.POI
    assert dt.position.x == 2.0
    # Cleanup so we don't leak into other tests sharing the module-level world.
    server.world.remove("designated_target")
    server.world.remove("yolo_person_9")


def test_apply_designation_no_candidate_is_noop():
    server.world.remove("designated_target")
    # Only a non-high-value detection present.
    server.world.upsert(_yolo("yolo_debris_1", "debris"))

    server._apply_designation(server.clock.now())

    assert "designated_target" not in _ids(server.world)
    server.world.remove("yolo_debris_1")
