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
