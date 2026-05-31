import pytest

from app.capture.foundry_export import (
    FoundryConfig,
    build_class_params,
    build_mission_params,
    validate_manifest,
)


def _manifest():
    return {
        "v": 1, "created_t": 5.0, "mission_ids": ["m1"],
        "source_counts": {"leader": 3, "follower": 0},
        "yolo": {"path": "yolo/", "classes": ["person", "vehicle"], "train": 3, "val": 1,
                 "format": "ultralytics",
                 "class_counts": {"person": {"count": 2, "train": 2, "val": 0},
                                  "vehicle": {"count": 1, "train": 0, "val": 1}}},
        "gemma": {"path": "gemma/examples.jsonl", "count": 4, "labeled_count": 2},
        "cleaning_report": {"frames_in": 5, "dropped_corrupt": 1, "dropped_duplicate": 1,
                            "frames_out": 3, "boxes_in": 4, "boxes_dropped": 0,
                            "records_invalid": 1},
        "label_events": {"confirm": 2, "reject": 1, "correct": 1},
    }


def test_build_mission_params_camelcase():
    p = build_mission_params(_manifest(), dataset_rid="ri.foundry.main.dataset.abc")
    assert p["missionId"] == "m1"
    assert p["createdT"] == 5.0
    assert p["framesOut"] == 3
    assert p["trainCount"] == 3 and p["valCount"] == 1
    assert p["classes"] == "person,vehicle"
    assert p["droppedCorrupt"] == 1 and p["droppedDuplicate"] == 1
    assert p["recordsInvalid"] == 1
    assert p["gemmaCount"] == 4 and p["gemmaLabeledCount"] == 2
    assert p["confirmCount"] == 2 and p["rejectCount"] == 1 and p["correctCount"] == 1
    assert p["datasetRid"] == "ri.foundry.main.dataset.abc"


def test_build_class_params_one_per_class():
    rows = build_class_params(_manifest())
    assert len(rows) == 2
    by_label = {r["label"]: r for r in rows}
    assert by_label["person"]["classKey"] == "m1:person"
    assert by_label["person"]["missionId"] == "m1"
    assert by_label["person"]["count"] == 2 and by_label["person"]["train"] == 2 and by_label["person"]["val"] == 0
    assert by_label["vehicle"]["classKey"] == "m1:vehicle"


def test_validate_manifest_rejects_missing_keys():
    bad = {"v": 1}
    with pytest.raises(ValueError):
        validate_manifest(bad)
    validate_manifest(_manifest())  # valid -> no raise


def test_config_from_env_requires_fields(monkeypatch):
    for k in ("FOUNDRY_HOST", "FOUNDRY_TOKEN", "FOUNDRY_ONTOLOGY_RID", "FOUNDRY_DATASET_RID"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError):
        FoundryConfig.from_env()
    monkeypatch.setenv("FOUNDRY_HOST", "https://x.palantirfoundry.com")
    monkeypatch.setenv("FOUNDRY_TOKEN", "tok")
    monkeypatch.setenv("FOUNDRY_ONTOLOGY_RID", "ri.ontology.main.ontology.123")
    monkeypatch.setenv("FOUNDRY_DATASET_RID", "ri.foundry.main.dataset.abc")
    cfg = FoundryConfig.from_env()
    assert cfg.host == "https://x.palantirfoundry.com"
    assert cfg.mission_action == "create-capture-mission"
    assert cfg.class_action == "create-detection-class"
    assert cfg.mission_edit_action == "edit-capture-mission"
    assert cfg.class_edit_action == "edit-detection-class"
    assert cfg.timeout_s == 30.0 and cfg.max_retries == 3
