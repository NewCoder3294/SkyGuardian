"""Post-mission exporter: push a packaged dataset into Palantir Foundry.

ONLINE, back-at-base only — NEVER imported by the live server/runtime (an offline
mission must not gain a network dependency). Pushes the manifest summary as Ontology
objects (Actions API) and the dataset files into a backing Foundry Dataset.
"""
from __future__ import annotations

import os
import time
import httpx
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
