import numpy as np

from app.clock import FakeClock
from app.contracts import EntitySource, EntityType
from app.perception.slam.local_map import LocalMap
from app.perception.slam.types import Landmark, Pose, Trajectory
from app.world_model import WorldModel


def _traj():
    return Trajectory(
        poses=[
            Pose(t=0.0, R_wc=np.eye(3), position=np.array([0.0, 0.0, 0.0])),
            Pose(t=1.0, R_wc=np.eye(3), position=np.array([1.0, 0.0, 0.0])),
        ],
        landmarks=[Landmark(position=np.array([2.0, 0.0, 0.0]), confidence=0.4)],
    )


def test_metric_scale_applied_to_camera_position():
    lm = LocalMap()
    lm.ingest(_traj())
    assert lm.metric is False
    lm.set_anchor(scale=2.0)
    assert lm.metric is True
    # latest VO position [1,0,0] * scale 2 = [2,0,0]
    assert np.allclose(lm.camera_position(), [2.0, 0.0, 0.0])


def test_origin_shifts_to_launch_point():
    lm = LocalMap()
    lm.ingest(_traj())
    lm.set_anchor(scale=1.0, origin=np.array([1.0, 0.0, 0.0]))
    # launch point becomes (0,0,0); latest pose [1,0,0] - origin = [0,0,0]
    assert np.allclose(lm.camera_position(), [0.0, 0.0, 0.0])


def test_to_entities_emits_mavic_and_landmarks_no_gps():
    lm = LocalMap()
    lm.ingest(_traj())
    lm.set_anchor(scale=2.0)
    ents = lm.to_entities(t=5.0, tag_position=np.array([0.0, 0.0, 0.0]))
    by_id = {e.id: e for e in ents}

    assert by_id["mavic_cam"].type is EntityType.DRONE
    assert by_id["mavic_cam"].source is EntitySource.SLAM
    assert np.allclose([by_id["mavic_cam"].position.x, by_id["mavic_cam"].position.y], [2.0, 0.0])
    assert by_id["anchor_tag"].type is EntityType.POI
    assert any(e.type is EntityType.OBJECT for e in ents)
    # GPS-less invariant: positions are plain metric Vec3, no lat/lng fields exist.
    assert not hasattr(by_id["mavic_cam"].position, "lat")


def test_integrate_into_world_model():
    world = WorldModel(clock=FakeClock(100.0))
    lm = LocalMap()
    lm.ingest(_traj())
    lm.set_anchor(scale=1.0)
    count = lm.integrate(world, t=100.0)
    snap = {e.id: e for e in world.snapshot()}
    assert count >= 2
    assert "mavic_cam" in snap and snap["mavic_cam"].type is EntityType.DRONE
