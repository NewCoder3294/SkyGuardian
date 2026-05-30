from app.clock import FakeClock
from app.follow.arming import ArmingLock
from app.follow.approach import ApproachController, ApproachPhase
from app.follow.target import TargetReading
from app.world_model import WorldModel


class _SimTello:
    """Integrates RC forward/back into a closing range, so we can prove the PD
    loop actually drives target distance to standoff."""
    def __init__(self, start_dist=5.0):
        from app.tello.client import TelloState
        self.dist = start_dist
        self.state = TelloState.CONNECTED
        self.is_connected = True
        self._dt = 1.0 / 15.0
    def send_rc(self, lr, fb, ud, yaw):
        # RC fb is a velocity command (Tello semantics); integrate over one tick.
        self.dist = max(0.0, self.dist - fb * 0.01 * self._dt)
    def hover(self): pass


def test_approach_converges_to_standoff():
    lock = ArmingLock(); lock.acquire("approach")
    tello = _SimTello(start_dist=5.0)
    world = WorldModel(clock=FakeClock())
    c = ApproachController(tello=tello, world=world, arming=lock,
                          clock=FakeClock(), standoff_m=1.5, owner="approach")
    t = 0.0
    for _ in range(300):
        r = TargetReading("person", distance_m=tello.dist, bearing_x_norm=0.0,
                          bearing_y_norm=0.0, confidence=0.9, timestamp=t)
        c.step(r, now=t)
        t += 1.0 / 15.0
        if c.phase is ApproachPhase.STANDOFF:
            break
    assert c.phase is ApproachPhase.STANDOFF
    assert abs(tello.dist - 1.5) <= 0.3
