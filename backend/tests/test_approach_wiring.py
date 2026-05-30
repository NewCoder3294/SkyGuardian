from app.contracts import Command
from app.follow.arming import ArmingLock


def test_route_arming_transfers_lock_between_modes():
    from app.server import _route_arming_for_command
    lock = ArmingLock(); lock.acquire("follow")
    _route_arming_for_command(Command.APPROACH, lock)
    assert lock.holder == "approach"
    _route_arming_for_command(Command.FOLLOW_ME, lock)
    assert lock.holder == "follow"
    _route_arming_for_command(Command.STOP, lock)
    assert lock.holder is None


def test_server_followcontroller_is_disarmed_by_default():
    """Production wiring drift guard: the FollowController the server builds must
    NOT command the drone until something explicitly arms 'follow'. Proves the
    interlock is fail-closed and the laptop starts disarmed."""
    import asyncio
    from app import server
    from app.contracts import Command
    from app.follow.apriltag import TagReading
    # The server's module-level arming lock starts unheld (disarmed).
    assert server.arming.holder in (None, "phone")
    # Drive the server's real follow controller in FOLLOWING with a valid reading.
    server.mission.apply(Command.FOLLOW_ME)   # also routes arming if wired via handler? No—handler does that; here lock still unheld
    reading = TagReading(tag_id=1, distance_m=3.0, bearing_x_norm=0.3,
                         bearing_y_norm=0.0, centre_px=(0, 0), timestamp=0.0)
    # Capture whether send_rc is called by swapping the tello with a recorder.
    calls = []
    orig = server.tello_client.send_rc
    server.tello_client.send_rc = lambda *a, **k: calls.append(a) or True
    try:
        asyncio.run(server.follow._drive_tello(reading, now=0.0))
    finally:
        server.tello_client.send_rc = orig
    assert calls == []   # disarmed-by-default => no command
