"""FollowState: the relative soldier↔Tello geometry the phone reports.

It is both an inbound client message (phone → laptop) and an outbound broadcast
(laptop → dashboard). These cover the contract + parser; the server relay is a
one-line rebroadcast of the stored latest.
"""
import pytest

from app.contracts import FollowState, parse_client_message


def test_parse_follow_state_roundtrip():
    raw = {
        "type": "follow_state",
        "active": True,
        "phase": "following",
        "distance_m": 2.5,
        "bearing_deg": 15.0,
        "source": "phone",
        "t": 1.0,
    }
    msg = parse_client_message(raw)
    assert isinstance(msg, FollowState)
    assert msg.active is True
    assert msg.phase == "following"
    assert msg.distance_m == 2.5
    assert msg.bearing_deg == 15.0


def test_follow_state_defaults_are_disarmed():
    msg = FollowState(t=0.0)
    assert msg.active is False
    assert msg.phase == "disarmed"
    assert msg.distance_m == 0.0


def test_unknown_client_message_still_rejected():
    with pytest.raises((ValueError,)):
        parse_client_message({"type": "nope", "t": 0.0})
