from app.contracts import Command
from app.follow.arming import ArmingLock
from app.state_machine import Stage


def test_route_arming_transfers_lock_between_resulting_stages():
    """Arming is gated on the ACTUAL resulting mission stage, not the raw command.
    APPROACH stage arms approach; FOLLOWING/RECALL arm follow; STOPPED disarms."""
    from app.server import _route_arming_for_command
    lock = ArmingLock(); lock.acquire("follow")
    _route_arming_for_command(Stage.APPROACH, lock); assert lock.holder == "approach"
    _route_arming_for_command(Stage.RECALL, lock); assert lock.holder == "follow"
    _route_arming_for_command(Stage.APPROACH, lock); assert lock.holder == "approach"
    # An emergency stop disarms entirely rather than re-arming a laptop controller.
    _route_arming_for_command(Stage.STOPPED, lock); assert lock.holder is None


def test_rejected_transition_does_not_move_the_lock():
    """A command the state machine rejects (no-op transition) must not desync the
    lock from the stage. APPROACH from IDLE/STOPPED stays IDLE -> lock untouched."""
    from app.server import _route_arming_for_command
    # IDLE stage (APPROACH rejected from IDLE): lock must stay where it was.
    lock = ArmingLock(); lock.acquire("follow")
    _route_arming_for_command(Stage.IDLE, lock); assert lock.holder == "follow"
    # HOLDING stage is also not an arming target here — lock is left untouched.
    _route_arming_for_command(Stage.HOLDING, lock); assert lock.holder == "follow"


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
    server.mission.apply(Command.FOLLOW_ME)   # Lock starts unheld; the WS handler (not this call) routes arming on FOLLOW_ME.
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
