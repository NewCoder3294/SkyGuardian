"""FastAPI app: the local server that is the single source of truth.

Binds 0.0.0.0. Serves one WebSocket endpoint that:
  - broadcasts world_snapshot + mission_state + health at BROADCAST_HZ
  - accepts client intent / device_location, validated against Contract B

Run: uvicorn app.server:app --host 0.0.0.0 --port 8000
(or ./run.sh)

Real producers:
  - PerceptionPipeline reads Mavic frames (MAVIC_SOURCE env), runs SLAM + YOLO,
    upserts entities. Idle if MAVIC_SOURCE is unset.
  - FollowController reads Tello frames, detects the soldier AprilTag, upserts
    soldier + drone entities, and sends RC to the Tello when stage=FOLLOWING.
    Idle if the Tello link is down.
  - device_location messages from the phone upsert a soldier entity tagged
    source=manual. This is the fallback soldier marker when the follow controller
    isn't producing one — keeps the dashboard useful before Tello is up.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from .clock import RealClock
from .contracts import (
    Command,
    Detections,
    DeviceLocation,
    Entity,
    EntitySource,
    EntityType,
    Health,
    IntentMessage,
    MissionState,
    WorldSnapshot,
    parse_client_message,
)
from .follow.controller import FollowController
from .perception.pipeline import PerceptionPipeline
from .state_machine import MissionStateMachine
from .tello.client import TelloClient, TelloState
from .tello.video import TelloVideoSource
from .video import NullSource, make_source
from .world_model import WorldModel
from .ws_hub import Hub


BROADCAST_HZ = float(os.environ.get("BROADCAST_HZ", "10"))

clock = RealClock()
world = WorldModel(clock=clock)
mission = MissionStateMachine(clock=clock)
hub = Hub()

# Mavic source — env-driven. Unset → NullSource (perception idles).
mavic_camera = make_source(os.environ.get("MAVIC_SOURCE"))

# YOLO weights — optional. Without weights, perception runs SLAM-only.
_YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS") or None

# YOLO-World custom vocabulary. If unset and we're loading a -world checkpoint,
# we default to a defense-relevant prompt set so the detector is useful out of
# the box. Set `YOLO_CLASSES="a,b,c"` to override.
_DEFAULT_VOCAB = [
    "person", "soldier", "gun", "rifle", "handgun", "pistol",
    "knife", "machete", "backpack", "helmet", "tactical vest",
    "vehicle", "car", "truck", "motorcycle",
    "explosive device", "grenade", "bomb", "ied",
    "drone", "weapon",
]
_yolo_classes_env = os.environ.get("YOLO_CLASSES")
_YOLO_CLASSES: list[str] | None = (
    [c.strip() for c in _yolo_classes_env.split(",") if c.strip()]
    if _yolo_classes_env
    else (_DEFAULT_VOCAB if _YOLO_WEIGHTS and "world" in _YOLO_WEIGHTS.lower() else None)
)
_YOLO_IMGSZ = int(os.environ.get("YOLO_IMGSZ", "960"))
_YOLO_CONF = float(os.environ.get("YOLO_CONF", "0.20"))

# Monocular depth model — unlocks true 3D positions for YOLO entities.
# Disable with DEPTH_MODEL="off". Calibration: DEPTH_SCALE tunes the
# (relative inverse depth) → metres mapping.
_DEPTH_MODEL_ENV = os.environ.get("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf")
_DEPTH_MODEL: str | None = None if _DEPTH_MODEL_ENV.lower() == "off" else _DEPTH_MODEL_ENV
_DEPTH_SCALE = float(os.environ.get("DEPTH_SCALE", "5.0"))

perception = PerceptionPipeline(
    video_source=mavic_camera,
    world=world,
    clock=clock,
    yolo_weights=_YOLO_WEIGHTS,
    yolo_classes=_YOLO_CLASSES,
    yolo_imgsz=_YOLO_IMGSZ,
    yolo_conf=_YOLO_CONF,
    depth_model=_DEPTH_MODEL,
    depth_scale=_DEPTH_SCALE,
    tag_size_m=float(os.environ.get("ANCHOR_TAG_SIZE_M", "0.20")),
    perception_fps=float(os.environ.get("PERCEPTION_FPS", "5")),
)

# Tello — single owner. The supervisor thread auto-reconnects; we never fail to
# boot the server because the drone isn't on the network.
tello_client = TelloClient(retry_seconds=float(os.environ.get("TELLO_RETRY_S", "3")))
tello_camera = TelloVideoSource(tello_client)

follow = FollowController(
    tello=tello_client,
    video=tello_camera,
    world=world,
    mission=mission,
    clock=clock,
    tag_size_m=float(os.environ.get("FOLLOW_TAG_SIZE_M", "0.18")),
    soldier_tag_id=(
        int(os.environ["FOLLOW_TAG_ID"]) if os.environ.get("FOLLOW_TAG_ID") else None
    ),
)

app = FastAPI(title="SkyGuardian — local brain")
# Dashboard runs on a different port (3001) and pulls MJPEG via <img src>.
# Browsers enforce CORS even on streaming responses; allow any origin since this
# server is on a local LAN only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _mavic_health() -> str:
    if isinstance(mavic_camera, NullSource):
        return "offline"
    # `is_streaming` flips True only after at least one frame has been
    # successfully decoded — so we don't report "streaming" while the RTMP
    # URL is unreachable but the cv2.VideoCapture object exists.
    return "streaming" if getattr(mavic_camera, "is_streaming", False) else "linking"


def _tello_health() -> str:
    return tello_client.state.value


async def _broadcast_loop() -> None:
    interval = 1.0 / BROADCAST_HZ
    while True:
        now = clock.now()
        await hub.broadcast(WorldSnapshot(entities=world.snapshot(), t=now))
        await hub.broadcast(MissionState(
            stage=mission.stage.value,
            # Only real mission-state faults surface to the dashboard. Tello
            # connection errors live on the mobile app side; their last_error
            # would otherwise broadcast as a persistent dashboard FAULT line
            # ("connect: '192.168.10.1'") that the operator can't act on.
            last_error=mission.last_error,
            t=now,
        ))
        await hub.broadcast(Health(
            tello=_tello_health(),
            mavic=_mavic_health(),
            perception=perception.health_str,
            t=now,
        ))
        boxes, iw, ih, bt = perception.latest_boxes()
        # The dashboard speaks "leader" (recon) / "follower" (companion) — abstracts
        # away the actual airframe make. The brain still tracks them by hardware.
        await hub.broadcast(Detections(
            source="leader", boxes=boxes, image_w=iw, image_h=ih, t=bt or now,
        ))
        await asyncio.sleep(interval)


# --- MJPEG endpoints -------------------------------------------------------

_MJPEG_BOUNDARY = "frame"
_MJPEG_PART_HEADER = (
    b"--" + _MJPEG_BOUNDARY.encode() + b"\r\n"
    b"Content-Type: image/jpeg\r\n\r\n"
)


async def _mjpeg_stream(source) -> AsyncIterator[bytes]:
    """Multipart/x-mixed-replace generator.

    Each yielded chunk = full part: boundary + Content-Type + CRLF + JPEG + CRLF.
    No preamble — an empty part before the first real frame trips browsers that
    expect a Content-Type within each delimited section."""
    last_payload: bytes | None = None
    while True:
        jpeg = await asyncio.to_thread(source.read_jpeg)
        if jpeg is not None and jpeg is not last_payload:
            last_payload = jpeg
            yield _MJPEG_PART_HEADER + jpeg + b"\r\n"
        await asyncio.sleep(0.05)  # 20 Hz cap


def _mjpeg_response(source) -> Response:
    return StreamingResponse(
        _mjpeg_stream(source),
        media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY}",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.on_event("startup")
async def _startup() -> None:
    app.state.broadcast_task = asyncio.create_task(_broadcast_loop())
    # Spin up the hardware-facing producers. All of them are robust to "no
    # hardware present" — they report the right health string instead of crashing.
    await asyncio.to_thread(mavic_camera.start)
    tello_client.start()
    tello_camera.start()
    perception.start()
    follow.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    task = getattr(app.state, "broadcast_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await asyncio.to_thread(mavic_camera.stop)
    await asyncio.to_thread(tello_camera.stop)
    await asyncio.to_thread(tello_client.stop)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "clients": hub.client_count,
        "stage": mission.stage.value,
        "tello": _tello_health(),
        "mavic": _mavic_health(),
        "perception": perception.health_str,
    }


@app.get("/video/leader.mjpg")
async def leader_mjpeg() -> Response:
    """Legacy MJPEG endpoint (multipart/x-mixed-replace). Kept for debugging.
    The dashboard now polls /video/leader.jpg instead because multipart streams
    keep the browser tab's loading spinner active forever, which reads as
    'page refreshing' to operators."""
    return _mjpeg_response(mavic_camera)


@app.get("/video/leader.jpg")
async def leader_jpg() -> Response:
    """Single-frame JPEG of the latest leader video frame. Returned with a
    no-store cache header so each fetch is fresh. 204 when no frame is ready
    yet — the dashboard polls this at ~10 Hz, completing every request so the
    browser tab never shows a perpetual loading state."""
    jpeg = await asyncio.to_thread(mavic_camera.read_jpeg)
    if jpeg is None:
        return Response(status_code=204)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/video/follower.mjpg")
async def follower_mjpeg() -> Response:
    """Legacy multipart endpoint for the companion feed."""
    return _mjpeg_response(tello_camera)


@app.get("/video/follower.jpg")
async def follower_jpg() -> Response:
    """Single-frame JPEG of the latest companion video frame, polled."""
    jpeg = await asyncio.to_thread(tello_camera.read_jpeg)
    if jpeg is None:
        return Response(status_code=204)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


def _apply_device_location(msg: DeviceLocation) -> None:
    """Phone GPS-less device_location → soldier entity.

    This is the soldier marker when the follow controller isn't running (no
    Tello, or AprilTag not in frame). The follow controller will overwrite this
    entity once it produces a higher-quality reading.
    """
    world.upsert(Entity(
        id="soldier",
        type=EntityType.SOLDIER,
        position=msg.position,
        confidence=0.7,
        timestamp=msg.t,
        source=EntitySource.MANUAL,
        label="operator",
        ttl_s=4.0,
    ))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await hub.add(ws)
    try:
        while True:
            raw = await ws.receive_json()
            try:
                msg = parse_client_message(raw)
            except (ValidationError, ValueError):
                # Unknown/malformed intent is rejected, never guessed.
                continue
            if isinstance(msg, IntentMessage):
                mission.apply(msg.command)
            elif isinstance(msg, DeviceLocation):
                _apply_device_location(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(ws)
