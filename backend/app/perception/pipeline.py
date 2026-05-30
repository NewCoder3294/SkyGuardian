"""Perception pipeline — the live loop that was missing.

Reads frames from the Mavic video source at perception_fps (default 5 Hz,
well below the 20 Hz MJPEG relay so the relay is never starved), runs:
  1. SLAM (MonocularVO) to maintain a local-frame camera pose.
  2. AprilTag detection to anchor metric scale on the first tag observation.
  3. YOLO detection on the same frame.
  4. Fusion: convert YOLO boxes + current SLAM pose -> world-model entities.
  5. SLAM map entities (mavic_cam drone, landmarks) -> world-model.

The loop is intentionally simple: process_sequence() runs on an accumulated
window of frames (sliding, capped) rather than incrementally, because MonocularVO
takes a sequence. Incremental VO is a future optimisation; this is correct first.

Health string returned to server.py:
  "ok"       - running, weights loaded, SLAM anchored
  "running"  - running but not yet metric (tag not seen yet)
  "degraded" - running but YOLO weights missing; SLAM-only
  "error"    - fatal startup error; pipeline is not running
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import cv2
import numpy as np

from ..clock import Clock, RealClock
from ..contracts import DetectionBox
from ..world_model import WorldModel
from ..perception.slam import (
    CameraModel, Frame, LocalMap, MonocularVO,
    detect_tags, metric_scale_from_tag,
)
from ..perception.slam.types import Pose
from .fusion import fuse_detections

# How many frames to keep in the sliding window fed to MonocularVO.
# More frames = better trajectory but more compute. 8 @ 5 Hz = 1.6 s window.
_WINDOW = 8

# Minimum frames before running VO (need at least 2).
_MIN_FRAMES = 2


class PerceptionPipeline:
    """Owns the perception loop. Call start() once at server startup.
    Query health_str for the current status string.
    """

    def __init__(
        self,
        video_source,           # FrameSource — the mavic_camera from server.py
        world: WorldModel,
        clock: Clock | None = None,
        yolo_weights: str | Path | None = None,
        yolo_classes: list[str] | None = None,
        yolo_imgsz: int = 640,
        yolo_conf: float = 0.25,
        depth_model: str | None = None,
        depth_scale: float = 5.0,
        tag_size_m: float = 0.20,
        perception_fps: float = 5.0,
        img_width: int = 640,
        img_height: int = 480,
    ) -> None:
        self._source = video_source
        self._world = world
        self._clock = clock or RealClock()
        self._tag_size = tag_size_m
        self._interval = 1.0 / perception_fps
        self._camera = CameraModel.from_resolution(img_width, img_height)

        self._detector = None       # YoloDetector | None
        self._depth = None          # DepthEstimator | None
        self._health = "starting"
        self._task: asyncio.Task | None = None
        self._needs_slam_reset = False
        # Latest normalised YOLO boxes + the frame dims they were measured on.
        # Read by the broadcast loop and overlay-rendered on the dashboard.
        self._latest_boxes: list[DetectionBox] = []
        self._latest_dims: tuple[int, int] = (0, 0)
        self._latest_boxes_t: float = 0.0

        # Try to load YOLO weights. Failure -> degraded (SLAM-only), not a crash.
        if yolo_weights is not None:
            try:
                from .yolo import YoloDetector  # noqa: PLC0415
                self._detector = YoloDetector(
                    yolo_weights,
                    conf_threshold=yolo_conf,
                    classes=yolo_classes,
                    imgsz=yolo_imgsz,
                )
                summary = (
                    f"vocab={len(yolo_classes)}cls" if yolo_classes else "default vocab"
                )
                print(f"[perception] YOLO loaded from {yolo_weights} ({summary}, imgsz={yolo_imgsz})")
            except FileNotFoundError as exc:
                print(f"[perception] YOLO degraded: {exc}")
                self._health = "degraded"
            except ImportError:
                print("[perception] ultralytics not installed — add 'ultralytics>=8.1' to requirements.txt")
                self._health = "degraded"

        # Try to load monocular depth model. Failure -> SLAM + YOLO only,
        # entities will clamp to ground plane.
        if depth_model:
            try:
                from .depth import DepthEstimator  # noqa: PLC0415
                self._depth = DepthEstimator(depth_model, scale=depth_scale)
                print(f"[perception] depth model loaded: {depth_model} (scale={depth_scale})")
            except Exception as exc:
                print(f"[perception] depth disabled: {exc}")

    @property
    def health_str(self) -> str:
        return self._health

    # Detections expire if no new perception frame arrived within this window.
    # Prevents stale boxes from being broadcast forever once the video source
    # disconnects (was producing phantom dashboard detections after RTMP dropped).
    _STALENESS_WINDOW_S = 2.0

    def latest_boxes(self) -> tuple[list[DetectionBox], int, int, float]:
        """Snapshot the latest YOLO boxes (normalised), the source frame dims,
        and the timestamp they were captured at. Returns empty list when no
        recent perception frame has been processed — so the dashboard's
        Leader/Perception/Detections all go clean the moment the feed drops."""
        if self._latest_boxes_t <= 0:
            return [], 0, 0, 0.0
        age = self._clock.now() - self._latest_boxes_t
        if age > self._STALENESS_WINDOW_S:
            return [], 0, 0, 0.0
        return list(self._latest_boxes), self._latest_dims[0], self._latest_dims[1], self._latest_boxes_t

    def reset(self) -> None:
        """Clear all derived state (detection buffer, SLAM map) so a freshly
        attached source starts from a clean slate. The server calls this when
        the operator swaps the leader source (RTMP ↔ uploaded video).
        Important: does NOT stop the loop — the worker thread just sees an
        empty buffer next tick and re-fills as soon as new frames arrive."""
        self._latest_boxes = []
        self._latest_dims = (0, 0)
        self._latest_boxes_t = 0.0
        # SLAM anchor + landmark drift from a previous feed are no longer valid
        # in the new feed's coordinate system. Set a flag the loop reads to
        # rebuild local_map / vo on the next iteration.
        self._needs_slam_reset = True
        if self._health not in ("error", "degraded"):
            self._health = "running"

    def start(self) -> None:
        """Schedule the perception loop as an asyncio task.
        Call from server _startup() inside the running event loop.
        """
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        local_map = LocalMap()
        vo = MonocularVO()
        frames: list[Frame] = []

        # Tag anchor state: need two observations with camera motion between them.
        tag_obs_buffer: list[tuple] = []  # (TagObservation, vo_position_ndarray)
        anchored = False

        if self._health == "starting":
            self._health = "running"

        while True:
            t_start = time.monotonic()

            # --- handle source-switch reset ---
            if self._needs_slam_reset:
                local_map = LocalMap()
                vo = MonocularVO()
                frames = []
                tag_obs_buffer = []
                anchored = False
                self._needs_slam_reset = False

            # --- read frame ---
            # read_jpeg() is sync and may block briefly; run off the event loop.
            jpeg_bytes = await asyncio.to_thread(self._source.read_jpeg)

            if jpeg_bytes is not None:
                # Decode JPEG back to BGR for OpenCV.
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if frame_bgr is not None:
                    now = self._clock.now()
                    frames.append(Frame(image=frame_bgr, t=now))

                    # Keep sliding window.
                    if len(frames) > _WINDOW:
                        frames = frames[-_WINDOW:]

                    if len(frames) >= _MIN_FRAMES:
                        # --- SLAM ---
                        try:
                            traj = await asyncio.to_thread(
                                vo.process_sequence, frames, self._camera
                            )
                        except Exception as exc:
                            print(f"[perception] SLAM error: {exc}")
                            traj = None

                        current_pose: Pose | None = None

                        if traj and traj.poses:
                            local_map.ingest(traj)
                            current_pose = traj.poses[-1]

                            # --- AprilTag metric anchor (once) ---
                            if not anchored:
                                try:
                                    tags = detect_tags(frame_bgr)
                                except RuntimeError:
                                    tags = []

                                if tags and current_pose is not None:
                                    tag_obs_buffer.append(
                                        (tags[0], current_pose.position.copy())
                                    )

                                if len(tag_obs_buffer) >= 2:
                                    obs_a, vo_a = tag_obs_buffer[0]
                                    obs_b, vo_b = tag_obs_buffer[-1]
                                    try:
                                        scale = metric_scale_from_tag(
                                            self._camera.K, self._tag_size,
                                            obs_a, vo_a, obs_b, vo_b,
                                        )
                                        local_map.set_anchor(scale)
                                        anchored = True
                                        print(f"[perception] metric anchor: scale={scale:.4f}")
                                        if self._health == "running":
                                            self._health = "ok"
                                    except ValueError:
                                        # Not enough camera motion between observations yet.
                                        pass

                            # Push SLAM entities (mavic_cam, landmarks) into world model.
                            local_map.integrate(self._world, now)

                        # --- YOLO + (optional) depth + fusion ---
                        if self._detector is not None and frame_bgr is not None:
                            try:
                                detections = await asyncio.to_thread(
                                    self._detector.detect, frame_bgr
                                )
                            except Exception as exc:
                                print(f"[perception] YOLO error: {exc}")
                                detections = []

                            depth_map = None
                            if detections and self._depth is not None:
                                try:
                                    depth_map = await asyncio.to_thread(
                                        self._depth.depth, frame_bgr
                                    )
                                except Exception as exc:
                                    print(f"[perception] depth error: {exc}")

                            entities = fuse_detections(
                                detections, self._camera, current_pose, now,
                                depth_map=depth_map,
                            )
                            for entity in entities:
                                self._world.upsert(entity)

                            # Publish the boxes (normalised against the frame
                            # dims) so the dashboard can overlay them on the
                            # MJPEG stream.
                            h, w = frame_bgr.shape[:2]
                            inv_w = 1.0 / max(w, 1)
                            inv_h = 1.0 / max(h, 1)
                            self._latest_boxes = [
                                DetectionBox(
                                    label=det.label,
                                    confidence=det.confidence,
                                    cx=float(det.cx_px * inv_w),
                                    cy=float(det.cy_px * inv_h),
                                    w=float(det.w_px * inv_w),
                                    h=float(det.h_px * inv_h),
                                )
                                for det in detections
                            ]
                            self._latest_dims = (w, h)
                            self._latest_boxes_t = now

            # --- pace the loop ---
            elapsed = time.monotonic() - t_start
            sleep_for = max(0.0, self._interval - elapsed)
            await asyncio.sleep(sleep_for)
