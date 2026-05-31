"""Post-mission exporter: push a packaged dataset into Palantir Foundry.

ONLINE, back-at-base only — NEVER imported by the live server/runtime (an offline
mission must not gain a network dependency). Pushes the manifest summary as Ontology
objects (Actions API) and the dataset files into a backing Foundry Dataset.
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
import httpx
from dataclasses import dataclass, field
from pathlib import Path
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
    # Foundry input ids that receive the primary key. The auto-generated "create"
    # action exposes the PK under a manually-added string param (this tenant left it
    # at Foundry's default id `new_parameter`); the auto-generated "edit" action
    # locates the object via an object-reference param whose id is the object type's
    # API name. Our builders emit the logical keys `missionId`/`classKey`; these map
    # them onto each action's real input id. All env-overridable.
    mission_pk_param: str = "new_parameter"
    class_pk_param: str = "new_parameter"
    mission_edit_locator: str = "CaptureMission"
    class_edit_locator: str = "DetectionClass"
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
            mission_pk_param=os.environ.get("FOUNDRY_MISSION_PK_PARAM", "new_parameter"),
            class_pk_param=os.environ.get("FOUNDRY_CLASS_PK_PARAM", "new_parameter"),
            mission_edit_locator=os.environ.get("FOUNDRY_MISSION_EDIT_LOCATOR", "CaptureMission"),
            class_edit_locator=os.environ.get("FOUNDRY_CLASS_EDIT_LOCATOR", "DetectionClass"),
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


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FoundryApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Foundry API error {status}: {body[:500]}")
        self.status = status
        self.body = body[:500]   # bound to avoid bloating tracebacks/logs


class FoundryClient:
    """Thin httpx wrapper for the Foundry v2 API. Injectable `http` (an
    httpx.Client) and `sleep` for tests. Retries transient failures with
    exponential backoff; never retries non-transient 4xx."""

    def __init__(self, config: FoundryConfig, *, http: Optional[httpx.Client] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._cfg = config
        self._sleep = sleep
        # Auth is set per-request in _request (the single source of truth), so the
        # default client does not also set it (avoids a redundant double header).
        self._http = http or httpx.Client(base_url=config.host, timeout=config.timeout_s)

    def _request(self, method: str, path: str, *, json=None, content=None,
                 headers=None, params=None) -> httpx.Response:
        hdrs = {"Authorization": f"Bearer {self._cfg.token}"}
        if headers:
            hdrs.update(headers)
        last_exc: Optional[Exception] = None
        last_resp: Optional[httpx.Response] = None
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
                last_resp = resp
                self._sleep(min(8.0, 0.5 * (2 ** attempt)))
                continue
            if resp.status_code >= 400:
                raise FoundryApiError(resp.status_code, resp.text)
            return resp
        # Only reached on a misconfigured non-positive max_retries; surface the
        # real status if we have one rather than a confusing 0.
        if last_resp is not None:
            raise FoundryApiError(last_resp.status_code, last_resp.text)
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


def upsert_action(client, create_action: str, edit_action: str, params: dict, *,
                  pk_field: Optional[str] = None, create_pk_param: Optional[str] = None,
                  edit_locator: Optional[str] = None) -> str:
    """Idempotent: apply the create action; on a 4xx conflict (object exists),
    apply the edit action instead. Returns 'created' or 'edited'.

    `params` carries the primary key under the logical `pk_field` key. Foundry's
    create and edit actions reference the PK under DIFFERENT input ids (the create
    action via a string param, the edit action via an object-reference locator), so
    the PK value is rebound onto `create_pk_param` for create and `edit_locator` for
    edit. When these are unset the params pass through unchanged (used in tests)."""
    create_params = dict(params)
    if pk_field and create_pk_param and create_pk_param != pk_field and pk_field in create_params:
        create_params[create_pk_param] = create_params.pop(pk_field)
    try:
        client.apply_action(create_action, create_params)
        return "created"
    except FoundryApiError as exc:
        if 400 <= exc.status < 500:
            # Object likely already exists -> update it. The edit action locates the
            # object by its PK under the object-reference locator id. Chain the
            # original create error so a failing edit still shows the create context.
            edit_params = dict(params)
            if pk_field and edit_locator and pk_field in edit_params:
                edit_params[edit_locator] = edit_params.pop(pk_field)
            try:
                client.apply_action(edit_action, edit_params)
            except FoundryApiError as edit_exc:
                raise edit_exc from exc
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
        status = upsert_action(client, config.class_action, config.class_edit_action, p,
                               pk_field="classKey", create_pk_param=config.class_pk_param,
                               edit_locator=config.class_edit_locator)
        report["classes"].append({"classKey": p["classKey"], "status": status})

    m_status = upsert_action(client, config.mission_action, config.mission_edit_action,
                             mission_params, pk_field="missionId",
                             create_pk_param=config.mission_pk_param,
                             edit_locator=config.mission_edit_locator)
    report["mission"] = {"missionId": mission_params["missionId"], "status": m_status}

    # Objects are already upserted at this point. If the file upload fails, record
    # that the export is partial (objects persisted, files did not) so the operator
    # can reconcile, write the report, and re-raise.
    try:
        tx = client.create_transaction(config.dataset_rid, "SNAPSHOT")
        client.upload_file(config.dataset_rid, tx, "manifest.json",
                           (dataset_dir / "manifest.json").read_bytes())
        client.upload_file(config.dataset_rid, tx, "dataset.zip", _zip_dataset(dataset_dir))
        client.commit_transaction(config.dataset_rid, tx)
        report["files_uploaded"] = ["manifest.json", "dataset.zip"]
    except Exception as exc:  # noqa: BLE001 - record partial state then re-raise
        report["partial_failure"] = str(exc)
        (dataset_dir / "export_report.json").write_text(json.dumps(report, indent=2))
        raise

    (dataset_dir / "export_report.json").write_text(json.dumps(report, indent=2))
    return report
