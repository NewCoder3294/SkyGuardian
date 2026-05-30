from app.clock import FakeClock
from app.contracts import Entity, EntitySource, EntityStatus, EntityType, Vec3
from app.world_model import WorldModel


def test_phone_reported_drone_appears_then_goes_stale():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    world.upsert(Entity(
        id="drone", type=EntityType.DRONE,
        position=Vec3(x=5.0, y=3.0, z=0.0),
        timestamp=100.0, source=EntitySource.FOLLOW, label="tello", ttl_s=4.0,
    ))
    snap = world.snapshot()
    assert any(e.id == "drone" and e.status == EntityStatus.ACTIVE for e in snap)

    clock.advance(5.0)  # 5s later, past ttl_s=4 -> stale
    snap = world.snapshot()
    drone = next(e for e in snap if e.id == "drone")
    assert drone.status == EntityStatus.STALE


def _entity(t: float, ttl: float = 5.0) -> Entity:
    return Entity(
        id="e1", type=EntityType.POI, position=Vec3(x=0, y=0, z=0),
        confidence=0.9, timestamp=t, source=EntitySource.YOLO, ttl_s=ttl,
    )


def test_upsert_admits_as_active():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    world.upsert(_entity(t=100.0))
    snap = world.snapshot()
    assert len(snap) == 1
    assert snap[0].status is EntityStatus.ACTIVE


def test_entity_goes_stale_after_ttl():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    world.upsert(_entity(t=100.0, ttl=5.0))
    clock.advance(6.0)  # past ttl, within lost window
    assert world.snapshot()[0].status is EntityStatus.STALE


def test_entity_goes_lost_then_dropped():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    world.upsert(_entity(t=100.0, ttl=5.0))
    clock.advance(16.0)  # past ttl * lost_factor (15s)
    assert world.snapshot()[0].status is EntityStatus.LOST
    clock.advance(10.0)  # well past the GC window
    assert world.snapshot() == []


def test_producer_cannot_set_lost():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    e = _entity(t=100.0).model_copy(update={"status": EntityStatus.LOST})
    world.upsert(e)  # world model overrides to active on admit
    assert world.snapshot()[0].status is EntityStatus.ACTIVE


def test_upsert_replaces_by_id_and_refreshes():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    world.upsert(_entity(t=100.0))
    clock.advance(6.0)
    world.upsert(_entity(t=106.0))  # fresh timestamp re-activates
    assert world.snapshot()[0].status is EntityStatus.ACTIVE
    assert len(world.snapshot()) == 1
