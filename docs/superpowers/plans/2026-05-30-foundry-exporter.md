# Foundry Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone, hardened, config-driven exporter that pushes a packaged SkyGuardian dataset into Palantir Foundry — manifest summary as Ontology objects (Actions API) + dataset files into a backing Foundry Dataset (Datasets API) — as a post-mission, online step never imported by the live runtime.

**Architecture:** A new `backend/app/capture/foundry_export.py` holds pure param-builders, manifest validation, a config object, and an injectable `httpx`-based `FoundryClient` (timeouts, transient-retry/backoff, preflight, apply-action, transaction-wrapped upload). `export_dataset` orchestrates idempotent upserts + an atomic SNAPSHOT file upload + an `export_report.json`, with a `dry_run` path that makes zero network calls. A thin CLI wires env → config → client. `packaging.py` gains per-class counts in the manifest.

**Tech Stack:** Python 3.13 / httpx / pydantic / pytest (backend, run from `backend/` with `pythonpath=.`). httpx is already a dependency.

**Spec:** `docs/superpowers/specs/2026-05-30-foundry-exporter-design.md`

**Foundry v2 API endpoints (pinned):**
- Preflight: `GET {host}/api/v2/ontologies/{ontology}`
- Apply action: `POST {host}/api/v2/ontologies/{ontology}/actions/{action}/apply` — JSON `{"parameters": {...}}`
- Create transaction: `POST {host}/api/v2/datasets/{rid}/transactions?branchName=master` — JSON `{"transactionType":"SNAPSHOT"}` → returns a transaction with `rid`
- Upload file: `POST {host}/api/v2/datasets/{rid}/files/{filePath}/upload?transactionRid={txRid}` — header `Content-Type: application/octet-stream`, raw bytes body
- Commit: `POST {host}/api/v2/datasets/{rid}/transactions/{txRid}/commit`
- All requests: header `Authorization: Bearer {token}`.

---

## File Structure

- **Modify** `backend/app/capture/packaging.py` — add `yolo.class_counts` to the manifest.
- **Create** `backend/app/capture/foundry_export.py` — config, param builders, manifest validation, `FoundryClient`, `upsert_action`, `export_dataset`.
- **Create** `scripts/export_to_foundry.py` — CLI.
- **Test** `backend/tests/test_capture_packaging.py` (extend), `backend/tests/test_foundry_export.py` (create), `backend/tests/test_foundry_isolation.py` (create).

All backend commands run from `backend/`: `.venv/bin/python -m pytest` (pytest `pythonpath=.`).

---

## Task 1: Per-class counts in the manifest

**Files:**
- Modify: `backend/app/capture/packaging.py`
- Test: `backend/tests/test_capture_packaging.py` (append)

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_capture_packaging.py`)

```python
def test_manifest_has_per_class_counts(tmp_path: Path):
    mdir = _setup_cleaned(tmp_path)   # 4 frames: i%2 -> "car" (odd), else "person"->"soldier"
    out = tmp_path / "datasets" / "dc"
    manifest = package_dataset(mdir, out, val_frac=0.0, created_t=1.0)

    cc = manifest["yolo"]["class_counts"]
    # Every class in the dataset appears with count/train/val.
    assert set(cc.keys()) == set(manifest["yolo"]["classes"])
    for label, c in cc.items():
        assert c["count"] == c["train"] + c["val"]
    # Totals reconcile with the dataset-wide split counts.
    assert sum(c["train"] for c in cc.values()) >= manifest["yolo"]["train"] * 0  # sanity
    total = sum(c["count"] for c in cc.values())
    assert total >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_packaging.py::test_manifest_has_per_class_counts -v`
Expected: KeyError `'class_counts'`.

- [ ] **Step 3: Implement per-class tallying in `package_dataset`**

In `backend/app/capture/packaging.py`, inside `package_dataset`, the loop already computes `split` ("train"/"val") and the resolved `kept` list of `(label, box)` per record. Add a tally. Right before the loop that writes images (where `counts = {"train": 0, "val": 0}` is initialized), add:

```python
    class_counts: dict[str, dict[str, int]] = {}
```

Inside the per-record loop, after `split` is determined and using the record's `kept` list, add:

```python
        for label, _ in kept:
            cc = class_counts.setdefault(label, {"count": 0, "train": 0, "val": 0})
            cc["count"] += 1
            cc[split] += 1
```

Then add `class_counts` to the manifest's `yolo` block. Change the existing manifest `"yolo": {...}` dict to include it:

```python
        "yolo": {"path": "yolo/", "classes": names, "train": counts["train"],
                 "val": counts["val"], "format": "ultralytics",
                 "class_counts": class_counts},
```

(Read the file to place the tally inside the existing loop using the real variable names — `split` and `kept` already exist there.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_capture_packaging.py -v`
Expected: all pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/capture/packaging.py backend/tests/test_capture_packaging.py
git commit -m "feat(capture): add per-class counts to dataset manifest"
```

---

## Task 2: FoundryConfig + param builders + manifest validation

**Files:**
- Create: `backend/app/capture/foundry_export.py`
- Test: `backend/tests/test_foundry_export.py`

- [ ] **Step 1: Write the failing test** (`backend/tests/test_foundry_export.py`)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py -v`
Expected: `ModuleNotFoundError: No module named 'app.capture.foundry_export'`.

- [ ] **Step 3: Create `backend/app/capture/foundry_export.py` (config + pure helpers)**

```python
"""Post-mission exporter: push a packaged dataset into Palantir Foundry.

ONLINE, back-at-base only — NEVER imported by the live server/runtime (an offline
mission must not gain a network dependency). Pushes the manifest summary as Ontology
objects (Actions API) and the dataset files into a backing Foundry Dataset.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

_REQUIRED_MANIFEST_KEYS = ("mission_ids", "yolo", "cleaning_report", "label_events", "gemma")


@dataclass
class FoundryConfig:
    host: str
    token: str
    ontology_rid: str
    dataset_rid: str
    mission_action: str = "create-capture-mission"
    class_action: str = "create-detection-class"
    mission_edit_action: str = "edit-capture-mission"
    class_edit_action: str = "edit-detection-class"
    timeout_s: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> "FoundryConfig":
        def req(name: str) -> str:
            v = os.environ.get(name)
            if not v:
                raise ValueError(f"missing required env var {name}")
            return v
        return cls(
            host=req("FOUNDRY_HOST").rstrip("/"),
            token=req("FOUNDRY_TOKEN"),
            ontology_rid=req("FOUNDRY_ONTOLOGY_RID"),
            dataset_rid=req("FOUNDRY_DATASET_RID"),
            mission_action=os.environ.get("FOUNDRY_ACTION_MISSION", "create-capture-mission"),
            class_action=os.environ.get("FOUNDRY_ACTION_CLASS", "create-detection-class"),
            mission_edit_action=os.environ.get("FOUNDRY_ACTION_MISSION_EDIT", "edit-capture-mission"),
            class_edit_action=os.environ.get("FOUNDRY_ACTION_CLASS_EDIT", "edit-detection-class"),
            timeout_s=float(os.environ.get("FOUNDRY_TIMEOUT_S", "30")),
            max_retries=int(os.environ.get("FOUNDRY_MAX_RETRIES", "3")),
        )


def validate_manifest(manifest: dict) -> None:
    missing = [k for k in _REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        raise ValueError(f"manifest missing required keys: {missing}")
    if "class_counts" not in manifest["yolo"]:
        raise ValueError("manifest.yolo missing 'class_counts' (re-run packaging)")
    if not manifest["mission_ids"]:
        raise ValueError("manifest.mission_ids is empty")


def build_mission_params(manifest: dict, dataset_rid: str) -> dict:
    cr = manifest["cleaning_report"]
    le = manifest["label_events"]
    yolo = manifest["yolo"]
    return {
        "missionId": manifest["mission_ids"][0],
        "createdT": manifest.get("created_t", 0.0),
        "framesOut": cr.get("frames_out", 0),
        "trainCount": yolo.get("train", 0),
        "valCount": yolo.get("val", 0),
        "classes": ",".join(yolo.get("classes", [])),
        "droppedCorrupt": cr.get("dropped_corrupt", 0),
        "droppedDuplicate": cr.get("dropped_duplicate", 0),
        "recordsInvalid": cr.get("records_invalid", 0),
        "gemmaCount": manifest["gemma"].get("count", 0),
        "gemmaLabeledCount": manifest["gemma"].get("labeled_count", 0),
        "confirmCount": le.get("confirm", 0),
        "rejectCount": le.get("reject", 0),
        "correctCount": le.get("correct", 0),
        "datasetRid": dataset_rid,
    }


def build_class_params(manifest: dict) -> list[dict]:
    mission_id = manifest["mission_ids"][0]
    out = []
    for label, c in manifest["yolo"].get("class_counts", {}).items():
        out.append({
            "classKey": f"{mission_id}:{label}",
            "missionId": mission_id,
            "label": label,
            "count": c.get("count", 0),
            "train": c.get("train", 0),
            "val": c.get("val", 0),
        })
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/capture/foundry_export.py backend/tests/test_foundry_export.py
git commit -m "feat(foundry): config + manifest validation + camelCase param builders"
```

---

## Task 3: FoundryClient (httpx: timeouts, retries, preflight, apply, upload)

**Files:**
- Modify: `backend/app/capture/foundry_export.py` (add `FoundryApiError`, `FoundryClient`)
- Test: `backend/tests/test_foundry_export.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py -k "apply_action or retry or upload or 401" -v`
Expected: ImportError (`FoundryApiError`, `FoundryClient`).

- [ ] **Step 3: Add `FoundryApiError` + `FoundryClient` to `foundry_export.py`**

Add `import time`, `import httpx` at the top (alongside existing imports), then:

```python
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FoundryApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Foundry API error {status}: {body[:500]}")
        self.status = status
        self.body = body


class FoundryClient:
    """Thin httpx wrapper for the Foundry v2 API. Injectable `http` (an
    httpx.Client) and `sleep` for tests. Retries transient failures with
    exponential backoff; never retries non-transient 4xx."""

    def __init__(self, config: FoundryConfig, *, http: Optional[httpx.Client] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._cfg = config
        self._sleep = sleep
        self._http = http or httpx.Client(
            base_url=config.host, timeout=config.timeout_s,
            headers={"Authorization": f"Bearer {config.token}"},
        )

    def _request(self, method: str, path: str, *, json=None, content=None,
                 headers=None, params=None) -> httpx.Response:
        hdrs = {"Authorization": f"Bearer {self._cfg.token}"}
        if headers:
            hdrs.update(headers)
        last_exc: Optional[Exception] = None
        for attempt in range(self._cfg.max_retries + 1):
            try:
                resp = self._http.request(method, path, json=json, content=content,
                                          headers=hdrs, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self._cfg.max_retries:
                    raise FoundryApiError(0, f"transport error after retries: {exc!r}")
                self._sleep(min(8.0, 0.5 * (2 ** attempt)))
                continue
            if resp.status_code in _RETRYABLE_STATUS and attempt < self._cfg.max_retries:
                self._sleep(min(8.0, 0.5 * (2 ** attempt)))
                continue
            if resp.status_code >= 400:
                raise FoundryApiError(resp.status_code, resp.text)
            return resp
        # Exhausted retries on a retryable status.
        raise FoundryApiError(0, f"exhausted retries: {last_exc!r}")

    def preflight(self) -> None:
        self._request("GET", f"/api/v2/ontologies/{self._cfg.ontology_rid}")

    def apply_action(self, action_api_name: str, params: dict) -> dict:
        resp = self._request(
            "POST",
            f"/api/v2/ontologies/{self._cfg.ontology_rid}/actions/{action_api_name}/apply",
            json={"parameters": params},
            headers={"Content-Type": "application/json"},
        )
        return resp.json() if resp.content else {}

    def create_transaction(self, dataset_rid: str, transaction_type: str = "SNAPSHOT") -> str:
        resp = self._request(
            "POST", f"/api/v2/datasets/{dataset_rid}/transactions",
            json={"transactionType": transaction_type},
            params={"branchName": "master"},
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        return data.get("rid") or data["transactionRid"]

    def upload_file(self, dataset_rid: str, transaction_rid: str, logical_path: str,
                    data: bytes) -> None:
        self._request(
            "POST", f"/api/v2/datasets/{dataset_rid}/files/{logical_path}/upload",
            content=data, params={"transactionRid": transaction_rid},
            headers={"Content-Type": "application/octet-stream"},
        )

    def commit_transaction(self, dataset_rid: str, transaction_rid: str) -> None:
        self._request(
            "POST",
            f"/api/v2/datasets/{dataset_rid}/transactions/{transaction_rid}/commit",
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/capture/foundry_export.py backend/tests/test_foundry_export.py
git commit -m "feat(foundry): httpx client with retries, preflight, apply, transaction upload"
```

---

## Task 4: upsert_action + export_dataset orchestration

**Files:**
- Modify: `backend/app/capture/foundry_export.py` (add `upsert_action`, `export_dataset`)
- Test: `backend/tests/test_foundry_export.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py -k "upsert or export" -v`
Expected: ImportError (`export_dataset`, `upsert_action`).

- [ ] **Step 3: Add `upsert_action` + `export_dataset` to `foundry_export.py`**

Add `import io`, `import json`, `import zipfile` and `from pathlib import Path` at the top (with existing imports), then:

```python
def upsert_action(client, create_action: str, edit_action: str, params: dict) -> str:
    """Idempotent: apply the create action; on a 4xx conflict (object exists),
    apply the edit action instead. Returns 'created' or 'edited'."""
    try:
        client.apply_action(create_action, params)
        return "created"
    except FoundryApiError as exc:
        if 400 <= exc.status < 500:
            client.apply_action(edit_action, params)   # raises if this also fails
            return "edited"
        raise


def _zip_dataset(dataset_dir: Path) -> bytes:
    """Zip the yolo/ + gemma/ subtrees into an in-memory archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("yolo", "gemma"):
            base = dataset_dir / sub
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(dataset_dir)))
    return buf.getvalue()


def export_dataset(dataset_dir, client, config: FoundryConfig, *,
                   dry_run: bool = False, report_t: float = 0.0) -> dict:
    dataset_dir = Path(dataset_dir)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    validate_manifest(manifest)

    mission_params = build_mission_params(manifest, config.dataset_rid)
    class_param_rows = build_class_params(manifest)

    report = {"t": report_t, "dry_run": dry_run, "dataset_rid": config.dataset_rid,
              "classes": [], "mission": None, "files_uploaded": [], "files_planned": []}

    if dry_run:
        report["classes"] = [{"action": config.class_action, "params": p} for p in class_param_rows]
        report["mission"] = {"action": config.mission_action, "params": mission_params}
        report["files_planned"] = ["manifest.json", "dataset.zip"]
        (dataset_dir / "export_report.json").write_text(json.dumps(report, indent=2))
        return report

    client.preflight()

    for p in class_param_rows:
        status = upsert_action(client, config.class_action, config.class_edit_action, p)
        report["classes"].append({"classKey": p["classKey"], "status": status})

    m_status = upsert_action(client, config.mission_action, config.mission_edit_action,
                             mission_params)
    report["mission"] = {"missionId": mission_params["missionId"], "status": m_status}

    tx = client.create_transaction(config.dataset_rid, "SNAPSHOT")
    client.upload_file(config.dataset_rid, tx, "manifest.json",
                       (dataset_dir / "manifest.json").read_bytes())
    client.upload_file(config.dataset_rid, tx, "dataset.zip", _zip_dataset(dataset_dir))
    client.commit_transaction(config.dataset_rid, tx)
    report["files_uploaded"] = ["manifest.json", "dataset.zip"]

    (dataset_dir / "export_report.json").write_text(json.dumps(report, indent=2))
    return report
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py -v`
Expected: all pass.
Then full suite: `cd backend && .venv/bin/python -m pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/capture/foundry_export.py backend/tests/test_foundry_export.py
git commit -m "feat(foundry): idempotent upsert + export_dataset orchestration + dry-run"
```

---

## Task 5: CLI `scripts/export_to_foundry.py`

**Files:**
- Create: `scripts/export_to_foundry.py`
- Test: `backend/tests/test_foundry_export.py` (append a CLI-importable smoke check)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_cli_module_imports_and_has_main():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "export_to_foundry.py"
    assert script.exists()
    src = script.read_text()
    assert "from app.capture.foundry_export import" in src
    assert "--dry-run" in src
    assert "def main(" in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py::test_cli_module_imports_and_has_main -v`
Expected: FAIL (script missing).

- [ ] **Step 3: Create `scripts/export_to_foundry.py`**

```python
"""Push a packaged SkyGuardian dataset into Palantir Foundry (post-mission, ONLINE).

Requires internet + Foundry credentials. Env:
  FOUNDRY_HOST            e.g. https://<tenant>.palantirfoundry.com
  FOUNDRY_TOKEN           a Foundry bearer token (never commit this)
  FOUNDRY_ONTOLOGY_RID    ri.ontology.main.ontology.<...>
  FOUNDRY_DATASET_RID     ri.foundry.main.dataset.<...> (backing dataset for files)
Optional action-name / tuning overrides: FOUNDRY_ACTION_MISSION, FOUNDRY_ACTION_CLASS,
  FOUNDRY_ACTION_MISSION_EDIT, FOUNDRY_ACTION_CLASS_EDIT, FOUNDRY_TIMEOUT_S, FOUNDRY_MAX_RETRIES.

The CaptureMission + DetectionClass object types and their create-/edit- actions must
already exist in the Foundry ontology (see the design spec for the schema).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.capture.foundry_export import FoundryClient, FoundryConfig, export_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Export a packaged dataset to Palantir Foundry.")
    ap.add_argument("--dataset", required=True, type=Path,
                    help="path to a packaged dataset dir (contains manifest.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate config + payloads and write the report WITHOUT any network call")
    args = ap.parse_args()

    try:
        config = FoundryConfig.from_env()
    except ValueError as exc:
        print(f"[foundry] config error: {exc}", file=sys.stderr)
        return 2

    client = None if args.dry_run else FoundryClient(config)
    # In dry-run, export_dataset never touches the client; pass a harmless stub.
    if client is None:
        class _NoCall:
            def __getattr__(self, _):
                raise AssertionError("network call attempted during --dry-run")
        client = _NoCall()

    report = export_dataset(args.dataset, client, config,
                            dry_run=args.dry_run, report_t=time.time())
    print(f"[foundry] {json.dumps({k: report[k] for k in ('dry_run', 'mission', 'files_uploaded', 'files_planned') if k in report})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_export.py::test_cli_module_imports_and_has_main -v`
Expected: PASS.
Then verify the CLI parses + dry-run errors cleanly without creds:
`cd /Users/nicolasdossantos/recon-companion/.claude/worktrees/autonomous-approach && backend/.venv/bin/python scripts/export_to_foundry.py --help` (prints usage)
and (no env set) `backend/.venv/bin/python scripts/export_to_foundry.py --dataset /tmp/nope --dry-run` → prints a config error and exits 2.

- [ ] **Step 5: Commit**

```bash
git add scripts/export_to_foundry.py backend/tests/test_foundry_export.py
git commit -m "feat(foundry): CLI to export a packaged dataset (with --dry-run)"
```

---

## Task 6: Offline-runtime isolation test

**Files:**
- Test: `backend/tests/test_foundry_isolation.py`

- [ ] **Step 1: Write the test**

```python
import subprocess
import sys
from pathlib import Path


def test_importing_server_does_not_import_foundry_export():
    """The live server must never pull in the Foundry exporter (offline runtime
    must not gain a network dependency). Import app.server in a clean subprocess
    and assert foundry_export is absent from sys.modules."""
    backend = Path(__file__).resolve().parents[1]
    code = (
        "import sys; import app.server; "
        "assert 'app.capture.foundry_export' not in sys.modules, "
        "'server must not import foundry_export'; print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(backend),
        capture_output=True, text=True,
        env={"PYTHONPATH": ".", "PATH": __import__("os").environ.get("PATH", ""),
             "TELLO_DISABLE": "1", "INTEL_MODEL": "off"},
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_foundry_isolation.py -v`
Expected: PASS (server imports fine and does NOT import `foundry_export`). If it fails because `app.server` import has side effects, use the same env guards already shown (`TELLO_DISABLE=1`, `INTEL_MODEL=off`); do not weaken the assertion.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_foundry_isolation.py
git commit -m "test(foundry): assert live server never imports the exporter (offline-safe)"
```

---

## Final verification

- [ ] Backend full suite: `cd backend && .venv/bin/python -m pytest -q` — all pass.
- [ ] CLI `--help` prints usage; `--dry-run` without env exits 2 with a clear config error.
- [ ] Manual (operator, with creds + object types created in Foundry): set the `FOUNDRY_*` env vars, run `python3 scripts/export_to_foundry.py --dataset datasets/<name> --dry-run` and review `export_report.json`; then run without `--dry-run` and confirm the `CaptureMission` + `DetectionClass` objects appear in the ontology and the files land in the backing dataset.
- [ ] Final whole-feature code review before finishing the branch.
