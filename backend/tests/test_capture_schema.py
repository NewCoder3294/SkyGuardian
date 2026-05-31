import pytest
from pydantic import ValidationError

from app.capture.schema import Detection, Event, Observation
from app.contracts import Vec3


def test_observation_round_trips():
    obs = Observation(
        t=1.5, mission_id="m1", frame_path="frames/000001.jpg", source="leader",
        image_w=1280, image_h=720, pose=Vec3(x=1.0, y=2.0, z=0.0),
        detections=[Detection(label="vehicle", conf=0.42, box=[0.5, 0.5, 0.1, 0.2])],
        sampled_reason="low_conf",
    )
    dumped = obs.model_dump(mode="json")
    again = Observation.model_validate(dumped)
    assert again.frame_path == "frames/000001.jpg"
    assert again.detections[0].label == "vehicle"
    assert again.pose.x == 1.0
    assert again.sampled_reason == "low_conf"


def test_observation_pose_optional():
    obs = Observation(
        t=0.0, mission_id="m1", frame_path="f.jpg", source="leader",
        image_w=10, image_h=10, detections=[], sampled_reason="cadence",
    )
    assert obs.pose is None


def test_detection_conf_bounds():
    with pytest.raises(ValidationError):
        Detection(label="x", conf=1.5, box=[0, 0, 0, 0])
    with pytest.raises(ValidationError):
        Detection(label="x", conf=-0.1, box=[0, 0, 0, 0])


def test_detection_box_must_be_length_four():
    with pytest.raises(ValidationError):
        Detection(label="x", conf=0.5, box=[0, 0, 0])


def test_event_round_trips():
    ev = Event(t=2.0, mission_id="m1", kind="correct", source="follower",
               label="person", corrected_label="soldier", box=[0.1, 0.1, 0.2, 0.2])
    again = Event.model_validate(ev.model_dump(mode="json"))
    assert again.kind == "correct"
    assert again.corrected_label == "soldier"
