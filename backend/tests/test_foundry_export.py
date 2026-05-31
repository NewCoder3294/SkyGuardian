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


import httpx

from app.capture.foundry_export import FoundryApiError, FoundryClient


def _cfg():
    return FoundryConfig(host="https://x.pf.com", token="tok",
                         ontology_rid="ri.ont.1", dataset_rid="ri.ds.1", max_retries=3)


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://x.pf.com")
    # sleep is injected as a no-op so backoff doesn't slow tests.
    return FoundryClient(_cfg(), http=http, sleep=lambda _s: None)


def test_apply_action_builds_request():
    seen = {}
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"validation": {"result": "VALID"}})
    c = _client(handler)
    c.apply_action("create-detection-class", {"classKey": "m1:car"})
    assert seen["url"] == "https://x.pf.com/api/v2/ontologies/ri.ont.1/actions/create-detection-class/apply"
    assert seen["auth"] == "Bearer tok"
    assert '"parameters"' in seen["body"] and "m1:car" in seen["body"]


def test_retry_on_503_then_success():
    calls = {"n": 0}
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"errorCode": "INTERNAL"})
        return httpx.Response(200, json={"ok": True})
    c = _client(handler)
    c.apply_action("create-capture-mission", {"missionId": "m1"})
    assert calls["n"] == 3   # retried twice, succeeded on the 3rd


def test_no_retry_on_401():
    calls = {"n": 0}
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"errorCode": "UNAUTHORIZED"})
    c = _client(handler)
    with pytest.raises(FoundryApiError) as ei:
        c.apply_action("create-capture-mission", {"missionId": "m1"})
    assert ei.value.status == 401
    assert calls["n"] == 1   # auth error not retried


def test_upload_transaction_flow():
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, str(request.url.query)))
        if request.url.path.endswith("/transactions"):
            return httpx.Response(200, json={"rid": "ri.tx.1"})
        if request.url.path.endswith("/commit"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"path": "x"})  # upload
    c = _client(handler)
    tx = c.create_transaction("ri.ds.1")
    assert tx == "ri.tx.1"
    c.upload_file("ri.ds.1", tx, "manifest.json", b"{}")
    c.commit_transaction("ri.ds.1", tx)
    paths = [p for _, p, _ in seen]
    assert "/api/v2/datasets/ri.ds.1/transactions" in paths
    assert "/api/v2/datasets/ri.ds.1/files/manifest.json/upload" in paths
    assert "/api/v2/datasets/ri.ds.1/transactions/ri.tx.1/commit" in paths


def test_exhausted_retries_surface_real_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"errorCode": "UNAVAILABLE"})
    c = _client(handler)
    with pytest.raises(FoundryApiError) as ei:
        c.apply_action("create-capture-mission", {})
    assert ei.value.status == 503   # real status, never a confusing 0


import json
import zipfile
from pathlib import Path

from app.capture.foundry_export import export_dataset, upsert_action


class _MockClient:
    def __init__(self, conflict_on=None):
        self.applied = []          # (action, params)
        self.uploads = []          # logical paths
        self.preflighted = False
        self.committed = False
        self._conflict_on = conflict_on or set()

    def preflight(self):
        self.preflighted = True

    def apply_action(self, action, params):
        self.applied.append((action, params))
        if action in self._conflict_on:
            raise FoundryApiError(400, "ObjectAlreadyExists")
        return {"ok": True}

    def create_transaction(self, rid, transaction_type="SNAPSHOT"):
        return "ri.tx.1"

    def upload_file(self, rid, tx, path, data):
        self.uploads.append(path)

    def commit_transaction(self, rid, tx):
        self.committed = True


def _dataset_dir(tmp_path: Path) -> Path:
    d = tmp_path / "datasets" / "d1"
    (d / "yolo").mkdir(parents=True)
    (d / "gemma").mkdir(parents=True)
    (d / "yolo" / "data.yaml").write_text("names: [person]\n")
    (d / "gemma" / "examples.jsonl").write_text("{}\n")
    (d / "manifest.json").write_text(json.dumps(_manifest()))
    return d


def test_upsert_action_create_then_edit_on_conflict():
    c = _MockClient(conflict_on={"create-x"})
    assert upsert_action(c, "create-x", "edit-x", {"a": 1}) == "edited"
    c2 = _MockClient()
    assert upsert_action(c2, "create-x", "edit-x", {"a": 1}) == "created"


def test_export_dataset_full(tmp_path: Path):
    d = _dataset_dir(tmp_path)
    cfg = _cfg()
    c = _MockClient()
    report = export_dataset(d, c, cfg, report_t=9.0)

    assert c.preflighted is True and c.committed is True
    class_actions = [a for a, _ in c.applied if a == cfg.class_action]
    mission_actions = [a for a, _ in c.applied if a == cfg.mission_action]
    assert len(class_actions) == 2     # person, vehicle
    assert len(mission_actions) == 1
    assert set(c.uploads) == {"manifest.json", "dataset.zip"}
    assert report["dry_run"] is False
    assert report["mission"]["status"] == "created"
    assert len(report["classes"]) == 2
    assert (d / "export_report.json").exists()


def test_export_dataset_dry_run_makes_no_calls(tmp_path: Path):
    d = _dataset_dir(tmp_path)
    c = _MockClient()
    report = export_dataset(d, c, _cfg(), dry_run=True, report_t=9.0)
    assert c.preflighted is False and c.applied == [] and c.uploads == [] and c.committed is False
    assert report["dry_run"] is True
    assert len(report["classes"]) == 2          # intended actions recorded
    assert report["files_planned"] == ["manifest.json", "dataset.zip"]
    assert (d / "export_report.json").exists()


def test_export_uploads_valid_zip(tmp_path: Path):
    d = _dataset_dir(tmp_path)
    captured = {}

    class _ZipClient(_MockClient):
        def upload_file(self, rid, tx, path, data):
            super().upload_file(rid, tx, path, data)
            if path == "dataset.zip":
                captured["zip"] = data

    export_dataset(d, _ZipClient(), _cfg(), report_t=1.0)
    import io
    zf = zipfile.ZipFile(io.BytesIO(captured["zip"]))
    names = zf.namelist()
    assert any(n.endswith("data.yaml") for n in names)
    assert any(n.endswith("examples.jsonl") for n in names)
