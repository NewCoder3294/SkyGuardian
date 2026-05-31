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
import socket
import uuid
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse, urlunparse

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from .clock import RealClock
from . import map_area
from .contracts import (
    BuildingsUpdated,
    Command,
    Detections,
    DeviceLocation,
    Entity,
    EntityReport,
    EntitySource,
    EntityType,
    FollowState,
    Health,
    IntentMessage,
    LabelEvent,
    MapAreaRequest,
    MissionState,
    WorldSnapshot,
    parse_client_message,
)
from .follow.approach import ApproachController
from .designation import Designator
from .follow.arming import ArmingLock
from .follow.controller import FollowController
from .perception.file_processor import process_video_file
from .perception.pipeline import PerceptionPipeline
from .reasoning.intel import IntelChat, IntelReasoner, IntelSummary, ollama_alive
from .state_machine import MissionStateMachine, Stage
from .tello.client import TelloClient, TelloState
from .tello.video import TelloVideoSource
from .video import NullSource, StreamVideoSource, SwitchableSource, make_source
from .world_model import WorldModel
from .ws_hub import Hub


BROADCAST_HZ = float(os.environ.get("BROADCAST_HZ", "10"))

clock = RealClock()
world = WorldModel(clock=clock)
mission = MissionStateMachine(clock=clock)
hub = Hub()

# Mavic source — env-driven. Unset → NullSource (perception idles at boot).
# Wrapped in SwitchableSource so the operator can hot-swap to an uploaded
# video file from the dashboard without restarting the backend.
_MAVIC_SOURCE_ENV = os.environ.get("MAVIC_SOURCE") or ""
# Sensible default for the dashboard's "RTMP" button when MAVIC_SOURCE wasn't
# set at boot. Matches the loopback relay (MediaMTX) we expect to run alongside
# the backend during a demo. Boot stays quiet (NullSource) — this URL is only
# attempted when the operator explicitly clicks RTMP.
_DEFAULT_RTMP_URL = os.environ.get(
    "MAVIC_RTMP_DEFAULT", "url:rtmp://127.0.0.1:1935/live"
)


def _detect_lan_ip() -> str | None:
    """Best-effort LAN IP for the publish-URL hint shown to the operator.

    The backend reads RTMP from loopback (MediaMTX runs on the same box), but
    the *publisher* is usually a phone or drone on the LAN — `127.0.0.1` in the
    displayed URL would never reach the relay. We open a UDP socket to a public
    address (no packets actually sent) so the OS picks the outbound interface,
    which is the IP a LAN publisher should target. Fully offline-safe.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.05)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return None


def _publish_url_for(spec: str) -> str:
    """Turn the internal RTMP read spec into a publish URL the operator can
    paste into a remote publisher. Strips the `url:` prefix and swaps a
    loopback host for the detected LAN IP when one is available."""
    raw = (spec or "").split(":", 1)[1] if (spec or "").lower().startswith("url:") else (spec or "")
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    host = parsed.hostname or ""
    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        lan = _detect_lan_ip()
        if lan:
            port = f":{parsed.port}" if parsed.port else ""
            netloc = f"{lan}{port}"
            parsed = parsed._replace(netloc=netloc)
            return urlunparse(parsed)
    return raw


_initial_mavic = make_source(_MAVIC_SOURCE_ENV or None)
_initial_kind = (
    "rtmp" if _MAVIC_SOURCE_ENV.lower().startswith("url:") else
    "file" if _MAVIC_SOURCE_ENV.lower().startswith("file:") else
    "device" if _MAVIC_SOURCE_ENV.lower().startswith("device:") else
    "none"
)
mavic_camera = SwitchableSource(
    _initial_mavic, initial_kind=_initial_kind, initial_label=_MAVIC_SOURCE_ENV,
)

# Uploaded video files live here. Gitignored; created on first upload.
_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / ".context" / "uploads"

# --- control-plane hardening (LAN-only, offline) ---------------------------
# The brain is a drone control plane. Even on a closed LAN, the state-mutating
# endpoints (source swap, file upload) deserve a CSRF/DoS floor.
_DASHBOARD_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "DASHBOARD_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001"
    ).split(",")
    if o.strip()
]
_OPERATOR_KEY = os.environ.get("OPERATOR_KEY") or ""
_MAX_UPLOAD_BYTES = int(float(os.environ.get("MAX_UPLOAD_MB", "500")) * 1_000_000)
_ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
_bg_tasks: set = set()

# When the PHONE is the Tello controller (the current demo topology), the laptop
# must NOT also talk to the Tello — two SDK controllers on one plain Tello fight.
# Set TELLO_DISABLE=1 so the backend skips connecting to / commanding the Tello
# entirely (it can then sit on the Tello AP purely to serve the dashboard/WS).
# Mavic recon (perception) is unaffected. See CLAUDE.md "One Tello controller
# armed at a time".
_TELLO_DISABLED = os.environ.get("TELLO_DISABLE", "0").lower() in ("1", "true", "yes")

# Latest follow geometry reported by the phone (the Tello's range/bearing from the
# soldier). Rebroadcast to the dashboard each tick for the relative follow inset.
# None until the phone first reports — the dashboard shows no follow widget then.
# _follow_rx_t is the LAPTOP receipt time (not the phone's t, which is a different
# wall clock) so the staleness check below is immune to clock skew.
_follow_state: FollowState | None = None
_follow_rx_t: float = 0.0
# Phone publishes follow geometry at a few Hz; if we haven't heard for this long the
# link is dead/wedged and a stale "FOLLOWING 2.5 m" reading would be dangerously
# misleading — downgrade the broadcast to a visible stale state instead.
_FOLLOW_STALE_S = 2.0

# Pre-cached OSM buildings for the operational area. Generated by
# `scripts/fetch_buildings.py` BEFORE going offline. Served read-only to the
# dashboard.
_BUILDINGS_PATH = Path(__file__).resolve().parent.parent.parent / ".context" / "buildings.json"

# On-device reasoning (offline equivalent of Gemini Live). Periodically runs a
# vision LLM on the latest frame + detections. Disabled if Ollama isn't
# reachable. Set INTEL_MODEL=off to skip even if ollama is up.
_INTEL_MODEL_ENV = os.environ.get("INTEL_MODEL", "gemma3:4b")
_INTEL_ENABLED = _INTEL_MODEL_ENV.lower() != "off"
_INTEL_INTERVAL_S = float(os.environ.get("INTEL_INTERVAL_S", "5"))
# Vision pass is ~30× slower than text-only on M-series for Gemma 3. Default ON
# (image-aware reasoning) for the demo; set INTEL_VISION=0 to fall back to the
# faster text-only path if the dashboard feels sluggish.
_INTEL_VISION = os.environ.get("INTEL_VISION", "1") == "1"
_intel_reasoner: IntelReasoner | None = (
    IntelReasoner(model=_INTEL_MODEL_ENV, with_vision=_INTEL_VISION) if _INTEL_ENABLED else None
)
# Same local model powers the operator chat — no extra weights download.
_intel_chat: IntelChat | None = (
    IntelChat(model=_INTEL_MODEL_ENV) if _INTEL_ENABLED else None
)
_intel_summary: IntelSummary | None = None
_intel_state = {
    "available": False,        # ollama reachable
    "running": False,          # an inference is currently in flight
    "last_error": None,        # str | None
}
# Dedicated vision-enabled reasoner for the on-demand /intel/deep-look route.
# Always uses with_vision=True regardless of INTEL_VISION; constructed lazily
# here so the model name stays in sync with the periodic reasoner.
_deep_look_reasoner: IntelReasoner | None = (
    IntelReasoner(model=_INTEL_MODEL_ENV, with_vision=True) if _INTEL_ENABLED else None
)


def _detections_path_for(video_name: str) -> Path:
    """Sidecar JSON path next to the uploaded video."""
    return _UPLOADS_DIR / f"{video_name}.detections.json"


# Single-slot upload status registry. The dashboard polls this while a file
# is being processed so it can show progress + flip into playback mode when
# processing completes. We don't need multi-job tracking — one operator,
# one feed at a time.
_upload_status: dict = {
    "name": None,                  # str | None
    "state": "idle",               # idle | uploading | processing | ready | error
    "progress": 0.0,               # 0..1 (processing fraction)
    "error": None,                 # str | None
    "duration_s": 0.0,
    "frame_count": 0,
    "detection_count": 0,
}

# YOLO weights — optional. Without weights, perception runs SLAM-only. If
# YOLO_WEIGHTS is unset, fall back to a bundled COCO model (models/yolov8n.pt)
# when present, so recon detection + target designation work out of the box. The
# file is gitignored (fetch once with ultralytics); absence degrades gracefully
# to SLAM-only.
_DEFAULT_YOLO_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "yolov8n.pt"
_YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS") or (
    str(_DEFAULT_YOLO_PATH) if _DEFAULT_YOLO_PATH.exists() else None
)

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

# Ensemble: optional second detector — standard YOLOv8 (COCO supervised) for
# high-precision person / vehicle / backpack. When set, we ALSO prune those
# labels from the YOLO-World vocab so the same physical object isn't
# double-detected. Two detectors, partitioned class space, results merged.
_YOLO_COCO_WEIGHTS = os.environ.get("YOLO_COCO_WEIGHTS") or None
# COCO classes we trust over open-vocab. Lowercased.
_COCO_KEEP_DEFAULT = [
    "person", "car", "truck", "motorcycle", "bicycle", "bus", "backpack",
]
_yolo_coco_keep_env = os.environ.get("YOLO_COCO_KEEP")
_YOLO_COCO_KEEP: list[str] = (
    [c.strip().lower() for c in _yolo_coco_keep_env.split(",") if c.strip()]
    if _yolo_coco_keep_env
    else (_COCO_KEEP_DEFAULT if _YOLO_COCO_WEIGHTS else [])
)
# Remove the COCO-handled classes from YOLO-World's vocab to avoid duplicates.
if _YOLO_COCO_WEIGHTS and _YOLO_CLASSES:
    _strip = set(_YOLO_COCO_KEEP)
    _YOLO_CLASSES = [c for c in _YOLO_CLASSES if c.lower() not in _strip]

# Monocular depth model — unlocks true 3D positions for YOLO entities.
# Disable with DEPTH_MODEL="off". Calibration: DEPTH_SCALE tunes the
# (relative inverse depth) → metres mapping.
_DEPTH_MODEL_ENV = os.environ.get("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf")
_DEPTH_MODEL: str | None = None if _DEPTH_MODEL_ENV.lower() == "off" else _DEPTH_MODEL_ENV
_DEPTH_SCALE = float(os.environ.get("DEPTH_SCALE", "5.0"))

_capture_recorder = None
if os.environ.get("CAPTURE_ENABLED") == "1":
    from .capture.recorder import CaptureRecorder  # noqa: PLC0415
    _capture_recorder = CaptureRecorder(
        root=Path(__file__).resolve().parent.parent.parent / "captures",
        mission_id=os.environ.get("CAPTURE_MISSION_ID", "mission"),
        max_mb=float(os.environ.get("CAPTURE_MAX_MB", "2000")),
        cadence_s=float(os.environ.get("CAPTURE_CADENCE_S", "2.0")),
        low_conf=float(os.environ.get("CAPTURE_LOW_CONF", "0.4")),
        enabled=True,
    )

perception = PerceptionPipeline(
    video_source=mavic_camera,
    world=world,
    clock=clock,
    yolo_weights=_YOLO_WEIGHTS,
    yolo_classes=_YOLO_CLASSES,
    yolo_imgsz=_YOLO_IMGSZ,
    yolo_conf=_YOLO_CONF,
    yolo_coco_weights=_YOLO_COCO_WEIGHTS,
    yolo_coco_keep=_YOLO_COCO_KEEP,
    depth_model=_DEPTH_MODEL,
    depth_scale=_DEPTH_SCALE,
    tag_size_m=float(os.environ.get("ANCHOR_TAG_SIZE_M", "0.20")),
    perception_fps=float(os.environ.get("PERCEPTION_FPS", "5")),
    recorder=_capture_recorder,
)

# Tello — single owner. The supervisor thread auto-reconnects; we never fail to
# boot the server because the drone isn't on the network.
tello_client = TelloClient(retry_seconds=float(os.environ.get("TELLO_RETRY_S", "3")))
tello_camera = TelloVideoSource(tello_client)

# Software arming interlock for the Tello. Exactly one laptop-side controller
# (follow OR approach) may command the drone at a time. Starts UNHELD: the
# laptop is DISARMED BY DEFAULT. Combined with the fail-closed gate in the
# controllers, nothing drives the Tello until an explicit FOLLOW_ME/APPROACH
# command routes the lock to that mode. Do NOT auto-arm here.
arming = ArmingLock()

follow = FollowController(
    tello=tello_client,
    video=tello_camera,
    world=world,
    mission=mission,
    arming=arming,
    owner="follow",
    clock=clock,
    tag_size_m=float(os.environ.get("FOLLOW_TAG_SIZE_M", "0.18")),
    soldier_tag_id=(
        int(os.environ["FOLLOW_TAG_ID"]) if os.environ.get("FOLLOW_TAG_ID") else None
    ),
)

approach = ApproachController(
    tello=tello_client, world=world, arming=arming, clock=clock,
    standoff_m=float(os.environ.get("APPROACH_STANDOFF_M", "1.5")),
    owner="approach",
)

# Mission-consistent target designation: ranks recon (Mavic/YOLO) detections and
# marks the top one for the operator. Read-only situational awareness — commands
# nothing. Emits a `designated_target` world entity that rides the broadcast.
_designator = Designator()


def _apply_designation(now: float) -> None:
    """Rank current recon detections and mark the top one as `designated_target`.

    No-op (the prior mark TTL-clears) when there's no high-value candidate. The
    emitted entity's label is not a high-value class, so it is excluded from
    re-selection — no feedback loop. Read-only situational awareness; commands
    nothing.
    """
    threat = _intel_summary.threat_level if _intel_summary is not None else "unknown"
    designation = _designator.select(world.snapshot(), threat)
    if designation is not None:
        world.upsert(Entity(
            id="designated_target",
            type=EntityType.POI,
            position=designation.position,
            confidence=designation.confidence,
            timestamp=now,
            source=EntitySource.YOLO,
            label=f"DESIGNATED: {designation.label}",
            ttl_s=3.0,
        ))


def _route_arming_for_command(command: Command, lock: ArmingLock) -> None:
    """Transfer the Tello arming lock to match the commanded mode."""
    if command is Command.APPROACH:
        lock.release("follow"); lock.acquire("approach")
    elif command is Command.FOLLOW_ME:
        lock.release("approach"); lock.acquire("follow")
    elif command in (Command.STOP, Command.RECALL):
        lock.release("approach"); lock.acquire("follow")

app = FastAPI(title="SkyGuardian — local brain")
# Dashboard runs on a different port (3001) and pulls MJPEG/JPEG via <img src>.
# Browsers enforce CORS even on streaming responses; restrict to the known
# dashboard origin(s) rather than "*" so a random page can't read our feeds or
# drive the state-mutating POSTs. See _DASHBOARD_ORIGINS above.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_DASHBOARD_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _require_operator(x_operator_key: str | None = Header(default=None)) -> None:
    """Gate state-mutating endpoints behind an optional shared secret. No-op
    when OPERATOR_KEY is unset (local demos stay frictionless); when set,
    rejects any POST that can't supply the matching `X-Operator-Key` header."""
    if _OPERATOR_KEY and x_operator_key != _OPERATOR_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-Operator-Key")


def _mavic_health() -> str:
    if isinstance(mavic_camera, NullSource):
        return "offline"
    # `is_streaming` flips True only after at least one frame has been
    # successfully decoded — so we don't report "streaming" while the RTMP
    # URL is unreachable but the cv2.VideoCapture object exists.
    return "streaming" if getattr(mavic_camera, "is_streaming", False) else "linking"


def _tello_health() -> str:
    if _TELLO_DISABLED:
        return "disabled"
    return tello_client.state.value


async def _broadcast_loop() -> None:
    interval = 1.0 / BROADCAST_HZ
    while True:
        # One bad tick (e.g. a transient build/validation error) must not kill the
        # single producer of world/mission/health for every client.
        try:
            now = clock.now()
            _apply_designation(now)
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
            # IMPORTANT: t = bt (the real perception-frame timestamp), NOT `bt or now`.
            # The dashboard uses t==0 as the signal that no frame has actually been
            # processed yet; falling back to `now` makes the Leader badge falsely
            # pulse green when nothing is connected.
            await hub.broadcast(Detections(
                source="leader", boxes=boxes, image_w=iw, image_h=ih, t=bt,
            ))
            # Relative follow geometry from the phone, if it has reported. Carries
            # range/bearing only (not map coordinates) — see FollowState. Downgrade
            # to a stale state if the phone has gone quiet, so the dashboard never
            # shows a confident-but-dead follow reading.
            if _follow_state is not None:
                fs = _follow_state
                if now - _follow_rx_t > _FOLLOW_STALE_S:
                    fs = fs.model_copy(update={"active": False, "phase": "stale", "t": now})
                await hub.broadcast(fs)
        except Exception as exc:  # noqa: BLE001 — keep the loop alive, log and continue
            print(f"[broadcast] tick failed: {exc!r}")
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


async def _intel_loop() -> None:
    """Periodically run the local LLM over the latest perception state.

    In text-only mode (default) the reasoner sees the YOLO label list only —
    fast (~2s) and runs whenever the brain has produced at least one
    perception frame. In vision mode it ALSO sees the current JPEG — slower
    (~120s on Apple Silicon) and requires a live frame too.
    """
    global _intel_summary
    while True:
        try:
            if _intel_reasoner is None:
                await asyncio.sleep(_INTEL_INTERVAL_S)
                continue
            alive = await ollama_alive(base_url="http://localhost:11434")
            _intel_state["available"] = alive
            if not alive or _intel_state["running"]:
                await asyncio.sleep(_INTEL_INTERVAL_S)
                continue

            boxes, _iw, _ih, bt = perception.latest_boxes()
            # Run whenever perception has produced a recent frame — even when
            # the box list is empty (operator wants to see "area clear" too).
            if bt <= 0:
                await asyncio.sleep(_INTEL_INTERVAL_S)
                continue

            jpeg = None
            if _INTEL_VISION:
                jpeg = await asyncio.to_thread(mavic_camera.read_jpeg)
                if jpeg is None:
                    # Vision mode without a frame is pointless; skip this tick.
                    await asyncio.sleep(_INTEL_INTERVAL_S)
                    continue

            labels = [b.label for b in boxes]
            _intel_state["running"] = True
            try:
                summary = await _intel_reasoner.summarise(jpeg, labels)
                _intel_summary = summary
                _intel_state["last_error"] = None
            except Exception as exc:
                _intel_state["last_error"] = f"{type(exc).__name__}: {exc}"
            finally:
                _intel_state["running"] = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _intel_state["last_error"] = f"loop: {exc}"
        await asyncio.sleep(_INTEL_INTERVAL_S)


# Placeholder: real Tello-frame target detection is a follow-up. Returns None
# so an armed approach safely hovers until the detector lands.
class _NoTargetDetector:
    def detect(self, jpeg, now):
        return None


approach_detector = _NoTargetDetector()


async def _run_deep_look(reasoner, jpeg, labels) -> "IntelSummary":
    """Run exactly one vision-enabled assessment over `jpeg`.

    Returns an error summary (no model call) when no frame is available so the
    caller always gets a well-typed result rather than an exception.
    """
    import time as _time

    if jpeg is None:
        return IntelSummary(
            text="No frame available for deep look.",
            threat_level="unknown",
            labels_seen=sorted(set(labels)),
            t=_time.time(),
            model="",
            latency_ms=0.0,
        )
    return await reasoner.summarise(jpeg, labels)


async def _approach_loop() -> None:
    interval = 1.0 / 15.0
    while True:
        if mission.stage is Stage.APPROACH:
            jpeg = tello_camera.read_jpeg()
            approach.step(approach_detector.detect(jpeg, clock.now()), clock.now())
        await asyncio.sleep(interval)


@app.on_event("startup")
async def _startup() -> None:
    app.state.broadcast_task = asyncio.create_task(_broadcast_loop())
    # Spin up the hardware-facing producers. All of them are robust to "no
    # hardware present" — they report the right health string instead of crashing.
    await asyncio.to_thread(mavic_camera.start)
    # Mavic recon (perception) always runs. The Tello stack is skipped when the
    # phone owns the drone (TELLO_DISABLE=1) so the laptop never contends for it.
    if not _TELLO_DISABLED:
        tello_client.start()
        tello_camera.start()
        follow.start()
        app.state.approach_task = asyncio.create_task(_approach_loop())
    perception.start()
    if _INTEL_ENABLED:
        app.state.intel_task = asyncio.create_task(_intel_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    # Cancel both the broadcast + intel reasoning tasks.
    for attr in ("broadcast_task", "intel_task", "approach_task"):
        task = getattr(app.state, attr, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    # Release camera sockets/captures/threads. Best-effort so one failing stop
    # doesn't prevent the others (drone-safety: always release the Tello link).
    for stop_call in (mavic_camera.stop, tello_camera.stop, tello_client.stop):
        with contextlib.suppress(Exception):
            await asyncio.to_thread(stop_call)


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


@app.get("/map/buildings")
async def get_buildings() -> Response:
    """Serve the pre-cached OSM buildings file (real data, projected to local
    metres). 404s when the operator hasn't run the fetch script yet — the
    dashboard handles that gracefully."""
    if not _BUILDINGS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No cached buildings. Run scripts/fetch_buildings.py "
                "--lat X --lng Y --radius 400 once with internet."
            ),
        )
    return FileResponse(_BUILDINGS_PATH, media_type="application/json")


@app.post("/map/area")
async def post_map_area(
    req: MapAreaRequest,
    _: None = Depends(_require_operator),
) -> dict:
    """Re-fetch OSM buildings for a new operational area, overwrite the served
    cache, and broadcast a buildings_updated signal. REQUIRES internet at call
    time (pre-mission staging); on failure the cached layer is left untouched."""
    try:
        # Offload the blocking Overpass fetch (urllib, up to 3 mirror timeouts)
        # to a thread so a slow/failed fetch can't stall the WS hub event loop.
        payload = await asyncio.to_thread(
            map_area.fetch_and_project, req.lat, req.lng, req.radius_m
        )
    except Exception as exc:  # noqa: BLE001 - any fetch failure → 503, cache intact
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch buildings (requires internet); cached area unchanged: {exc}",
        )
    map_area.write_buildings(payload, _BUILDINGS_PATH, backup=True)
    await hub.broadcast(
        BuildingsUpdated(
            origin=payload["origin"],
            radius_m=payload["radius_m"],
            count=payload["count"],
            t=clock.now(),
        )
    )
    return {"origin": payload["origin"], "radius_m": payload["radius_m"], "count": payload["count"]}


@app.get("/intel/summary")
async def get_intel_summary() -> dict:
    """Latest on-device reasoning result. `available` says whether the local
    Ollama server is reachable; `running` says an inference is in flight."""
    s = _intel_summary
    return {
        "available": _intel_state["available"],
        "running": _intel_state["running"],
        "last_error": _intel_state["last_error"],
        "model": _intel_reasoner._model if _intel_reasoner is not None else None,
        "summary": (
            {
                "text": s.text,
                "threat_level": s.threat_level,
                "labels_seen": s.labels_seen,
                "t": s.t,
                "model": s.model,
                "latency_ms": s.latency_ms,
            }
            if s is not None
            else None
        ),
    }


@app.post("/intel/deep-look")
async def post_deep_look() -> dict:
    """On-demand vision-enabled assessment over the current Mavic frame.

    Unlike the periodic /intel/summary (text-only by default), this endpoint
    always encodes the latest JPEG into the prompt so the model literally sees
    the frame. One inference per request — expect ~30–120 s on Apple Silicon
    for Gemma 3 4B. Returns immediately with an error payload when intel is
    disabled or no frame is available.
    """
    if _deep_look_reasoner is None:
        return {"summary": None, "error": "intel disabled"}
    jpeg = await asyncio.to_thread(mavic_camera.read_jpeg)
    boxes, _w, _h, _t = perception.latest_boxes()
    labels = [b.label for b in boxes]
    summary = await _run_deep_look(_deep_look_reasoner, jpeg, labels)
    return {
        "summary": {
            "text": summary.text,
            "threat_level": summary.threat_level,
            "labels_seen": summary.labels_seen,
            "t": summary.t,
            "model": summary.model,
            "latency_ms": summary.latency_ms,
        }
    }


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list, max_length=20)


@app.post("/intel/chat")
async def post_intel_chat(body: ChatRequest) -> dict:
    """Operator chatbot over the local Ollama model. Grounded in the latest
    intel summary + the labels visible in the most recent detection layer so
    the assistant answers about THIS feed, not generic knowledge."""
    if _intel_chat is None:
        return {"reply": "Intel reasoning is disabled on this server.", "ok": False}
    if not _intel_state["available"]:
        return {
            "reply": "Local LLM is offline — start Ollama and try again.",
            "ok": False,
        }

    # Build context: latest summary + current frame labels.
    s = _intel_summary
    parts: list[str] = []
    if s is not None:
        parts.append(f"Latest assessment: {s.text}")
        parts.append(f"Threat level: {s.threat_level}")
        if s.labels_seen:
            parts.append("Recently observed: " + ", ".join(s.labels_seen))
    context = "\n".join(parts)

    try:
        reply = await _intel_chat.reply(
            history=[m.model_dump() for m in body.messages], context=context
        )
        return {"reply": reply, "ok": True, "model": _INTEL_MODEL_ENV}
    except Exception as exc:
        return {
            "reply": f"Local LLM call failed: {type(exc).__name__}",
            "ok": False,
        }


@app.get("/video/source")
async def get_source() -> dict:
    """Current video source state — mode + label + (when in file mode) the
    processing/playback status the dashboard needs to switch UI modes."""
    spec = _MAVIC_SOURCE_ENV or _DEFAULT_RTMP_URL
    return {
        "kind": mavic_camera.kind,
        "label": mavic_camera.label,
        "streaming": mavic_camera.is_streaming,
        "rtmp_default": spec,
        # LAN-reachable hint for the operator's publisher. When MediaMTX runs
        # on the laptop the read spec stays on loopback, but a phone/drone has
        # to target the laptop's LAN IP — the dashboard shows this.
        "publish_url": _publish_url_for(spec),
        "upload": dict(_upload_status),
    }


@app.get("/video/upload/status")
async def get_upload_status() -> dict:
    """Granular processing status (polled by SourceSelector during upload).
    Same shape as `_upload_status`."""
    return dict(_upload_status)


@app.post("/video/source/rtmp")
async def use_rtmp_source(_: None = Depends(_require_operator)) -> dict:
    """Switch the leader source to the configured RTMP feed. Uses
    MAVIC_SOURCE if set, otherwise falls back to the loopback default
    (MediaMTX on 127.0.0.1:1935/live). Clears any upload-in-progress status
    so the dashboard exits playback mode."""
    # Cancel any in-flight upload processing task so it can't race with the
    # reset below and resurrect upload_status="ready" after the swap. Without
    # this, clicking RTMP mid-processing leaves a brief window where the
    # background task completes and writes state="ready", which the dashboard
    # can misread as "playback ready" if the kind hasn't propagated yet.
    for t in list(_bg_tasks):
        if not t.done():
            t.cancel()
    target = _MAVIC_SOURCE_ENV or _DEFAULT_RTMP_URL
    new = make_source(target)
    await asyncio.to_thread(mavic_camera.replace, new, "rtmp", target)
    # Clear perception/SLAM state so the new feed isn't anchored against
    # landmarks/tags from the previous one (different coordinate system).
    perception.reset()
    _upload_status.update({
        "name": None, "state": "idle", "progress": 0.0,
        "error": None, "duration_s": 0.0, "frame_count": 0, "detection_count": 0,
    })
    return {"ok": True, "kind": "rtmp", "label": target}


def _save_upload_capped(upload_file, dest: Path, max_bytes: int) -> int:
    """Stream an upload to disk in 1 MiB chunks, aborting if it exceeds
    max_bytes. Runs in a worker thread (synchronous file IO). Removes the
    partial file and raises ValueError if the cap is tripped. Returns the byte
    count on success."""
    written = 0
    with dest.open("wb") as out:
        while True:
            chunk = upload_file.read(1 << 20)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"file exceeds max upload size ({max_bytes // 1_000_000} MB)"
                )
            out.write(chunk)
    return written


@app.post("/video/source/upload")
async def upload_source_video(
    file: UploadFile = File(...), _: None = Depends(_require_operator),
) -> dict:
    """Accept a pre-recorded video and run perception over the entire clip
    *before* returning the dashboard to playback. The browser then plays the
    raw file natively (HTML5 <video controls>) and overlays detections by
    looking up sidecar JSON at video.currentTime.

    Why pre-process synchronously instead of streaming through the live
    pipeline:
      - The operator needs to scrub backwards/forwards arbitrarily; the live
        path emits over WebSocket once.
      - YOLO + depth latency (~150 ms/frame) makes real-time playback impossible
        for HD video on CPU. Doing it once up front and caching is the only
        sensible answer.

    The leader's SwitchableSource flips to NullSource so the live perception
    loop goes idle while a file is loaded — the dashboard reads detections
    from JSON, not from the WS stream, in this mode.

    Guards (single-operator control plane): reject a second upload while one is
    in flight, restrict to video container extensions, cap the size, and write
    to a unique on-disk name so a re-upload can't clobber a clip the dashboard
    is still scrubbing.
    """
    if _upload_status["state"] in ("uploading", "processing"):
        raise HTTPException(
            status_code=409, detail="an upload is already in progress",
        )

    raw_name = Path(file.filename or "").name
    ext = Path(raw_name).suffix.lower()
    if ext not in _ALLOWED_VIDEO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unsupported file type {ext or '(none)'}; "
                f"allowed: {', '.join(sorted(_ALLOWED_VIDEO_EXTS))}"
            ),
        )
    # Unique name: the dashboard keys file/detections URLs off the server-
    # returned label, so a uuid prefix is transparent to it.
    safe_name = f"{uuid.uuid4().hex[:8]}-{raw_name}"
    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UPLOADS_DIR / safe_name

    _upload_status.update({
        "name": safe_name, "state": "uploading", "progress": 0.0,
        "error": None, "duration_s": 0.0, "frame_count": 0, "detection_count": 0,
    })
    try:
        await asyncio.to_thread(
            _save_upload_capped, file.file, dest, _MAX_UPLOAD_BYTES,
        )
    except ValueError as exc:
        _upload_status.update({"state": "error", "error": str(exc)})
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    # Park the live source — the dashboard will switch to playback UI on the
    # next /video/source poll.
    await asyncio.to_thread(mavic_camera.replace, NullSource(), "file", safe_name)
    perception.reset()

    # Run perception async so the upload POST returns immediately. The
    # dashboard polls /video/upload/status until state == "ready". Hold a strong
    # ref so the task isn't garbage-collected before it finishes.
    _upload_status["state"] = "processing"
    task = asyncio.create_task(_process_uploaded_file(safe_name, dest))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    return {"ok": True, "kind": "file", "label": safe_name, "status_url": "/video/upload/status"}


async def _process_uploaded_file(safe_name: str, dest: Path) -> None:
    """Background task: run process_video_file in a worker thread so it doesn't
    block the event loop, update status as it goes."""

    def _on_progress(frac: float) -> None:
        _upload_status["progress"] = frac

    try:
        result = await asyncio.to_thread(
            process_video_file,
            dest,
            _detections_path_for(safe_name),
            yolo_weights=_YOLO_WEIGHTS,
            yolo_classes=_YOLO_CLASSES,
            yolo_imgsz=_YOLO_IMGSZ,
            yolo_conf=_YOLO_CONF,
            yolo_coco_weights=_YOLO_COCO_WEIGHTS,
            yolo_coco_keep=_YOLO_COCO_KEEP,
            depth_model=_DEPTH_MODEL,
            depth_scale=_DEPTH_SCALE,
            sample_fps=float(os.environ.get("PERCEPTION_FPS", "5")),
            on_progress=_on_progress,
        )
        _upload_status.update({
            "state": "ready",
            "progress": 1.0,
            "duration_s": result.duration_s,
            "frame_count": result.summary["frame_count"],
            "detection_count": result.summary["detection_count"],
        })
    except asyncio.CancelledError:
        # The /video/source/rtmp handler cancels in-flight uploads to win the
        # race against `state=ready` being written after the swap. Leave
        # _upload_status alone — the handler already reset it to idle.
        raise
    except Exception as exc:
        _upload_status.update({
            "state": "error",
            "error": f"{type(exc).__name__}: {exc}",
        })


@app.get("/video/file/{name}")
async def serve_video_file(name: str) -> Response:
    """Serve a previously-uploaded video file with HTTP byte-range support
    (FastAPI/Starlette FileResponse does this automatically). The browser's
    <video> element needs ranges so the scrubber can seek without re-downloading."""
    safe_name = Path(name).name
    src = _UPLOADS_DIR / safe_name
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"video not found: {safe_name}")
    return FileResponse(src, media_type="video/mp4")


@app.get("/video/detections/{name}")
async def serve_detections_json(name: str) -> Response:
    """Pre-computed per-timestamp detections + entities for an uploaded video.
    The dashboard fetches this once after `state == ready`, then runs all
    overlay math client-side off the cached array."""
    safe_name = Path(name).name
    src = _detections_path_for(safe_name)
    if not src.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"detections not ready for {safe_name}. "
                "Poll /video/upload/status until state=='ready'."
            ),
        )
    return FileResponse(src, media_type="application/json")


def _record_label_event(msg: LabelEvent) -> None:
    """Persist an operator label decision for the data flywheel (no-op when
    capture is disabled)."""
    if _capture_recorder is None:
        return
    from .capture.schema import Event  # noqa: PLC0415
    _capture_recorder.record_event(Event(
        t=msg.t, mission_id=_capture_recorder.mission_id,
        kind=msg.kind, source=msg.source, label=msg.label,
        corrected_label=msg.corrected_label, box=msg.box, note=msg.note,
    ))


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


def _apply_entity_report(msg: EntityReport) -> None:
    """Phone-localized entities (operator + drone), already in the shared world
    frame. The phone co-registers against the launch anchor tag, so these upsert
    straight into the world model. TTL on each entity ages them out if the phone
    link drops (no frozen drone left on the map).

    Trust note: the phone is a trusted local peer on the offline network, so the
    client-supplied id/timestamp/ttl_s are taken as-is. The TTL-staleness guarantee
    therefore depends on the phone sending honest timestamps; a stuck/future
    timestamp would keep an entity ACTIVE. Acceptable under the offline threat
    model; namespacing phone ids / clamping timestamp to receipt time is a
    future hardening step.
    """
    for entity in msg.entities:
        world.upsert(entity)


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
                _route_arming_for_command(msg.command, arming)
            elif isinstance(msg, DeviceLocation):
                _apply_device_location(msg)
            elif isinstance(msg, FollowState):
                # Phone owns the follow loop; keep its latest relative geometry for
                # the broadcast loop to relay to the dashboard. Stamp the laptop
                # receipt time (for the staleness check) and overwrite the
                # client-supplied source — it's advisory and must not be trusted.
                global _follow_state, _follow_rx_t
                _follow_state = msg.model_copy(update={"source": "phone"})
                _follow_rx_t = clock.now()
            elif isinstance(msg, EntityReport):
                _apply_entity_report(msg)
            elif isinstance(msg, LabelEvent):
                _record_label_event(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(ws)
