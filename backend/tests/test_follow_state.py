"""FollowState: the relative soldier↔Tello geometry the phone reports.

It is both an inbound client message (phone → laptop) and an outbound broadcast
(laptop → dashboard). These cover the contract + parser; the server relay is a
one-line rebroadcast of the stored latest.
"""
import math

import pytest
from pydantic import ValidationError

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


# --- hardening: a malformed/hostile payload must not poison the dashboard -----

def test_rejects_unknown_phase():
    with pytest.raises(ValidationError):
        FollowState(phase="pwned", t=0.0)


@pytest.mark.parametrize("dist", [-1.0, 5000.0])
def test_rejects_out_of_range_distance(dist):
    with pytest.raises(ValidationError):
        FollowState(distance_m=dist, t=0.0)


def test_rejects_out_of_range_bearing():
    with pytest.raises(ValidationError):
        FollowState(bearing_deg=99999.0, t=0.0)


@pytest.mark.parametrize("bad", [math.inf, math.nan, -math.inf])
def test_rejects_nan_and_inf(bad):
    with pytest.raises(ValidationError):
        FollowState(distance_m=bad, t=0.0)


def test_confirming_phase_is_accepted():
    # Airborne target-confirmation hover before follow/track begins.
    assert FollowState(active=True, phase="confirming", distance_m=2.0, t=1.0).phase == "confirming"


def test_server_injected_stale_phase_is_valid():
    # The broadcast loop downgrades to phase="stale"; the model must allow it.
    msg = FollowState(active=True, phase="following", distance_m=2.0, t=1.0)
    stale = msg.model_copy(update={"active": False, "phase": "stale", "t": 2.0})
    assert stale.phase == "stale"
