"""Unit tests for the pure target Designator."""
from __future__ import annotations

from app.contracts import Entity, EntitySource, EntityType, Vec3
from app.designation import Designator


def _ent(id: str, label: str, conf: float, source=EntitySource.YOLO,
         pos=(0.0, 0.0, 0.0)) -> Entity:
    return Entity(
        id=id, type=EntityType.OBJECT, position=Vec3(x=pos[0], y=pos[1], z=pos[2]),
        confidence=conf, timestamp=1.0, source=source, label=label,
    )


def test_empty_returns_none():
    assert Designator().select([], "low") is None


def test_picks_highest_confidence_high_value():
    ents = [
        _ent("a", "person", 0.6),
        _ent("b", "car", 0.9),
        _ent("c", "person", 0.7),
    ]
    d = Designator().select(ents, "elevated")
    assert d is not None
    assert d.entity_id == "b"
    assert d.label == "car"
    assert d.threat_level == "elevated"


def test_ignores_non_yolo_sources():
    ents = [
        _ent("slammed", "person", 0.99, source=EntitySource.SLAM),
        _ent("manual", "person", 0.99, source=EntitySource.MANUAL),
    ]
    assert Designator().select(ents, "low") is None


def test_ignores_non_high_value_labels():
    ents = [_ent("d", "debris", 0.95), _ent("t", "tree", 0.95)]
    assert Designator().select(ents, "low") is None


def test_tie_break_by_proximity_to_launch():
    # Equal confidence -> the one nearer the launch origin (0,0,0) wins.
    ents = [
        _ent("far", "person", 0.8, pos=(10.0, 0.0, 0.0)),
        _ent("near", "person", 0.8, pos=(1.0, 0.0, 0.0)),
    ]
    d = Designator().select(ents, "low")
    assert d is not None and d.entity_id == "near"


def test_label_case_insensitive():
    d = Designator().select([_ent("p", "Person", 0.5)], "low")
    assert d is not None and d.entity_id == "p"
