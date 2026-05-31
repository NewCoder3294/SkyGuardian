"""The two integration contracts the whole system meets at.

Contract A — Entity: the shared world-model data shape.
Contract B — WebSocket messages: server->client broadcasts and client->server intent.

These are validated with Pydantic at the WS boundary. Keep this file the single
source of truth; the TS mirror lives in shared/contracts.ts.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


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
    APPROACH = "approach"


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


class FollowState(BaseModel):
    """Relative follow geometry between the soldier and the companion Tello.

    Published by the PHONE (which runs the follow loop) and rebroadcast by the
    laptop so the dashboard can render a self-contained 'follow' inset. This is
    deliberately NOT in the SLAM map frame — the phone's follow frame and the
    Mavic SLAM frame aren't co-registered — so it carries only the Tello's range
    and bearing relative to the soldier, never absolute map coordinates.
    """

    # Reject NaN/inf so a malformed payload can't poison the dashboard render.
    model_config = ConfigDict(allow_inf_nan=False)

    type: Literal["follow_state"] = "follow_state"
    active: bool = False           # drone airborne under follow control
    # "stale" is server-injected when the phone's stream ages out; the phone only
    # ever sends the five live phases.
    phase: Literal[
        "disarmed", "searching", "confirming", "following", "lost", "manual", "stale"
    ] = "disarmed"
    distance_m: float = Field(default=0.0, ge=0.0, le=200.0)   # metres, bounded
    bearing_deg: float = Field(default=0.0, ge=-360.0, le=360.0)
    source: str = "phone"          # advisory only; not trusted for any decision
    t: float


class GeoPoint(BaseModel):
    """A WGS84 lat/lng. Used to geo-reference the local map frame's origin."""
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)


class BuildingsUpdated(BaseModel):
    """Signal that the served OSM buildings layer changed (operator set a new
    operational area). Clients re-GET /map/buildings on receipt — the polygon
    blob is intentionally NOT carried over the socket."""
    type: Literal["buildings_updated"] = "buildings_updated"
    origin: GeoPoint
    radius_m: int
    count: int
    t: float


class MapAreaRequest(BaseModel):
    """Operator request to re-fetch the OSM buildings layer for a new area."""
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    radius_m: int = Field(default=400, ge=50, le=2000)


ServerMessage = Union[WorldSnapshot, MissionState, Health, Detections, FollowState, BuildingsUpdated]


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


class LabelEvent(BaseModel):
    """Operator label decision on a detection / follow target, recorded for the
    data flywheel (confirm a true positive, reject a false positive, or correct
    the class). Box (if given) is [cx, cy, w, h] normalized 0..1."""
    type: Literal["label_event"] = "label_event"
    kind: Literal["confirm", "reject", "correct"]
    source: str
    label: Optional[str] = None
    corrected_label: Optional[str] = None
    box: Optional[list[float]] = Field(default=None, min_length=4, max_length=4)
    note: Optional[str] = None
    t: float


ClientMessage = Union[IntentMessage, DeviceLocation, FollowState, LabelEvent]


def parse_client_message(raw: dict) -> ClientMessage:
    """Validate an inbound client message. Raises pydantic.ValidationError on
    unknown command / malformed payload — unknown intents are rejected, never guessed.
    """
    kind = raw.get("type")
    if kind == "intent":
        return IntentMessage.model_validate(raw)
    if kind == "device_location":
        return DeviceLocation.model_validate(raw)
    if kind == "follow_state":
        return FollowState.model_validate(raw)
    if kind == "label_event":
        return LabelEvent.model_validate(raw)
    raise ValueError(f"unknown client message type: {kind!r}")
