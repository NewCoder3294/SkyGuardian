import pytest
from pydantic import ValidationError

from app.contracts import (
    Command,
    DeviceLocation,
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
