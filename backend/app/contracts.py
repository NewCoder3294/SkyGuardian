"""The two integration contracts the whole system meets at.

Contract A — Entity: the shared world-model data shape.
Contract B — WebSocket messages: server->client broadcasts and client->server intent.

These are validated with Pydantic at the WS boundary. Keep this file the single
source of truth; the TS mirror lives in shared/contracts.ts.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Contract A — World model entity
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    POI = "poi"
    HAZARD = "hazard"
    OBJECT = "object"
    SOLDIER = "soldier"
    DRONE = "drone"


class EntityStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    LOST = "lost"


class EntitySource(str, Enum):
    YOLO = "yolo"
    SLAM = "slam"
    FOLLOW = "follow"
    MANUAL = "manual"


class Vec3(BaseModel):
    x: float
    y: float
    z: float = 0.0


class Entity(BaseModel):
    """A single thing in the local-frame world model (metres, no GPS)."""

    id: str
    type: EntityType
    position: Vec3
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    timestamp: float  # unix seconds from the producing source
    source: EntitySource
    label: Optional[str] = None
    ttl_s: float = 5.0
    # status is owned by the world model, not the producer; default active on upsert.
    status: EntityStatus = EntityStatus.ACTIVE


# ---------------------------------------------------------------------------
# Contract B — WebSocket messages
# ---------------------------------------------------------------------------

# Closed intent vocabulary. Voice and UI must map onto exactly these. No free text.
class Command(str, Enum):
    FOLLOW_ME = "follow_me"
    HOLD = "hold"
    RECALL = "recall"
    STOP = "stop"


# stop/recall are always-live and highest priority, honored from any stage.
PRIORITY_COMMANDS = {Command.STOP, Command.RECALL}


# --- server -> clients ---

class WorldSnapshot(BaseModel):
    type: Literal["world_snapshot"] = "world_snapshot"
    entities: list[Entity]
    t: float


class MissionState(BaseModel):
    type: Literal["mission_state"] = "mission_state"
    stage: str
    last_error: Optional[str] = None
    t: float


class Health(BaseModel):
    type: Literal["health"] = "health"
    tello: str = "unknown"
    mavic: str = "unknown"
    perception: str = "unknown"
    t: float


class DetectionBox(BaseModel):
    """One YOLO box in image-plane coords, normalised 0..1 against the source frame.

    Position is centre + size in normalised units so the dashboard overlay scales
    automatically regardless of source resolution. `label`, `confidence` mirror
    the underlying YoloDetection.
    """

    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    cx: float = Field(ge=0.0, le=1.0)
    cy: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0, le=1.0)
    h: float = Field(ge=0.0, le=1.0)


class Detections(BaseModel):
    """A snapshot of the most recent YOLO detections on one video source.

    `source` identifies the video stream the boxes belong to (`leader` = recon
    Mavic, `follower` = companion Tello) so the dashboard overlay knows which
    `<img>` to draw on top of. `image_w/h` are the source frame dimensions in
    pixels (advisory — the boxes are already normalised).
    """

    type: Literal["detections"] = "detections"
    source: str  # "leader" (recon Mavic) | "follower" (companion Tello)
    boxes: list[DetectionBox]
    image_w: int = 0
    image_h: int = 0
    t: float


ServerMessage = Union[WorldSnapshot, MissionState, Health, Detections]


# --- clients -> server ---

class IntentMessage(BaseModel):
    type: Literal["intent"] = "intent"
    command: Command
    source: str  # "phone" | "dashboard"
    t: float


class DeviceLocation(BaseModel):
    type: Literal["device_location"] = "device_location"
    position: Vec3
    source: str = "phone"
    t: float


ClientMessage = Union[IntentMessage, DeviceLocation]


def parse_client_message(raw: dict) -> ClientMessage:
    """Validate an inbound client message. Raises pydantic.ValidationError on
    unknown command / malformed payload — unknown intents are rejected, never guessed.
    """
    kind = raw.get("type")
    if kind == "intent":
        return IntentMessage.model_validate(raw)
    if kind == "device_location":
        return DeviceLocation.model_validate(raw)
    raise ValueError(f"unknown client message type: {kind!r}")
