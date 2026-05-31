"""Versioned on-disk record schema for field-captured data (collect phase).

These are the JSONL line formats written under captures/<mission_id>/. Versioned
(`v`) so the clean/package steps stay stable as the schema evolves.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..contracts import Vec3


class Detection(BaseModel):
    """One detection on a saved frame. `box` is [cx, cy, w, h], normalized 0..1."""
    label: str
    conf: float = Field(ge=0.0, le=1.0)
    box: list[float]


class Observation(BaseModel):
    """One saved frame + its detections + context. One per observations.jsonl line."""
    v: int = 1
    t: float
    mission_id: str
    frame_path: str            # relative to the mission dir, e.g. "frames/000001.jpg"
    source: str                # "leader" (Mavic) | "follower" (Tello)
    image_w: int
    image_h: int
    pose: Optional[Vec3] = None
    detections: list[Detection]
    sampled_reason: Literal["low_conf", "novel_class", "cadence"]


class Event(BaseModel):
    """An operator label action. One per events.jsonl line."""
    v: int = 1
    t: float
    mission_id: str
    kind: Literal["confirm", "reject", "correct"]
    source: str
    label: Optional[str] = None
    corrected_label: Optional[str] = None
    box: Optional[list[float]] = None
    note: Optional[str] = None
