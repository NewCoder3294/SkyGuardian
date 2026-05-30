import math

import pytest
from pydantic import ValidationError

from app.contracts import (
    Command,
    DeviceLocation,
    EntityReport,
    IntentMessage,
    parse_client_message,
)


def test_parse_valid_intent():
    msg = parse_client_message({"type": "intent", "command": "follow_me", "source": "phone", "t": 1.0})
    assert isinstance(msg, IntentMessage)
    assert msg.command is Command.FOLLOW_ME


def test_parse_device_location():
    msg = parse_client_message(
        {"type": "device_location", "position": {"x": 1, "y": 2, "z": 0}, "source": "phone", "t": 1.0}
    )
    assert isinstance(msg, DeviceLocation)
    assert msg.position.x == 1


def test_unknown_command_rejected():
    with pytest.raises(ValidationError):
        parse_client_message({"type": "intent", "command": "fire_missile", "source": "phone", "t": 1.0})


def test_unknown_message_type_rejected():
    with pytest.raises(ValueError):
        parse_client_message({"type": "lol", "t": 1.0})


def test_confidence_bounds_enforced():
    from app.contracts import Entity, EntitySource, EntityType, Vec3

    with pytest.raises(ValidationError):
        Entity(
            id="x", type=EntityType.POI, position=Vec3(x=0, y=0, z=0),
            confidence=1.5, timestamp=0.0, source=EntitySource.YOLO,
        )


def test_entity_report_parses_with_entities():
    raw = {
        "type": "entity_report",
        "entities": [
            {"id": "drone", "type": "drone", "position": {"x": 1.0, "y": 2.0, "z": 0.0},
             "timestamp": 100.0, "source": "follow"},
        ],
        "source": "phone",
        "t": 100.0,
    }
    msg = parse_client_message(raw)
    assert isinstance(msg, EntityReport)
    assert msg.entities[0].id == "drone"


def test_entity_report_rejects_nan_position():
    raw = {
        "type": "entity_report",
        "entities": [
            {"id": "drone", "type": "drone",
             "position": {"x": math.nan, "y": 0.0, "z": 0.0},
             "timestamp": 1.0, "source": "follow"},
        ],
        "source": "phone", "t": 1.0,
    }
    with pytest.raises((ValidationError, ValueError)):
        parse_client_message(raw)


def test_entity_report_rejects_too_many_entities():
    raw = {
        "type": "entity_report",
        "entities": [
            {"id": f"e{i}", "type": "object", "position": {"x": 0, "y": 0, "z": 0},
             "timestamp": 1.0, "source": "follow"} for i in range(20)
        ],
        "source": "phone", "t": 1.0,
    }
    with pytest.raises((ValidationError, ValueError)):
        parse_client_message(raw)
