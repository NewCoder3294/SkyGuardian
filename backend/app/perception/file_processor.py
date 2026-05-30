"""Pre-process an uploaded video file through the same perception stack the
live RTMP pipeline uses, then write a sidecar JSON keyed by video timestamp
so the dashboard can scrub through it like a normal video.

This is the "VOD" path. The live RTMP path emits detections over WebSocket as
they happen (no rewind possible). The file path is different: we run YOLO +
depth + (lightweight) SLAM-aware fusion across every Nth frame, dump the
results to disk, and serve them back as a time-indexed array. The browser
plays the source video natively (HTML5 <video controls>) and overlays boxes
at video.currentTime by lookup.

We deliberately reuse the same primitives:
  - YoloDetector (open-vocab YOLO-World)
  - DepthEstimator (DepthAnything-V2)
  - fusion.detection_to_entity (image-plane box + camera pose → world Entity)
  - MonocularVO + AprilTag anchor (best-effort; logged-only on file mode)

so a single source of truth governs both pipelines.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .fusion import fuse_detections
from .slam import CameraModel, Frame, LocalMap, MonocularVO
from .yolo import YoloDetection, YoloDetector


# Per-frame snapshot saved to JSON. cx/cy/w/h are normalised [0,1] against the
# source frame size; the dashboard projects onto the displayed video rect.
@dataclass
class FrameBox:
    label: str
    confidence: float
    cx: float
    cy: float
    w: float
    h: float


# A single time slice of the dashboard's world: image-plane detections plus
# the SLAM-derived 3D entities the operator sees on the Map tab.
@dataclass
class FrameSnapshot:
    t: float                          # seconds from video start
    boxes: list[FrameBox] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)


@dataclass
class ProcessedVideo:
    """Top-level JSON shape. Matches what /video/detections/{name} serves."""
    name: str
    duration_s: float
    image_w: int
    image_h: int
    sample_fps: float                 # how often we ran perception
    source_fps: float                 # native fps of the source video
    frames: list[FrameSnapshot]
    summary: dict                     # {"frame_count": N, "detection_count": M, ...}


def process_video_file(
    video_path: Path,
    output_json_path: Path,
    *,
    yolo_weights: Optional[str] = None,
    yolo_classes: Optional[list[str]] = None,
    yolo_imgsz: int = 960,
    yolo_conf: float = 0.20,
    depth_model: Optional[str] = None,
    depth_scale: float = 5.0,
    sample_fps: float = 5.0,
    on_progress: Optional[Callable[[float], None]] = None,
) -> ProcessedVideo:
    """Run perception over every Nth frame of `video_path` and write the
    results to `output_json_path`. `on_progress(0..1)` is called periodically.

    Returns the structured result; the JSON file mirrors it.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"cv2 could not open video: {video_path}")

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_s = total_frames / source_fps if source_fps > 0 else 0.0

    sample_stride = max(1, int(round(source_fps / max(sample_fps, 0.1))))
    effective_fps = source_fps / sample_stride

    detector: YoloDetector | None = None
    if yolo_weights:
        try:
            detector = YoloDetector(
                yolo_weights,
                conf_threshold=yolo_conf,
                classes=yolo_classes,
                imgsz=yolo_imgsz,
            )
        except Exception as exc:  # YOLO is optional — log and continue
            print(f"[file_processor] YOLO disabled: {exc}")

    depth_est = None
    if depth_model:
        try:
            from .depth import DepthEstimator  # noqa: PLC0415
            depth_est = DepthEstimator(depth_model, scale=depth_scale)
        except Exception as exc:
            print(f"[file_processor] depth disabled: {exc}")

    camera = CameraModel.from_resolution(width or 1280, height or 720)
    vo = MonocularVO()
    local_map = LocalMap()
    sliding: list[Frame] = []
    _MAX_WINDOW = 8

    frames_out: list[FrameSnapshot] = []
    detection_count = 0
    frame_idx = 0
    sampled_idx = 0

    while True:
        ok, bgr = cap.read()
        if not ok:
            break

        # Sample every Nth frame for perception; the rest are decoded just to
        # advance cap's position. We can't seek by time for some codecs.
        if frame_idx % sample_stride != 0:
            frame_idx += 1
            continue

        t_video = frame_idx / source_fps if source_fps > 0 else float(sampled_idx)

        # --- SLAM trajectory (best-effort) ---------------------------------
        sliding.append(Frame(image=bgr, t=t_video))
        if len(sliding) > _MAX_WINDOW:
            sliding = sliding[-_MAX_WINDOW:]
        current_pose = None
        if len(sliding) >= 2:
            try:
                traj = vo.process_sequence(sliding, camera)
                if traj.poses:
                    local_map.ingest(traj)
                    current_pose = traj.poses[-1]
            except Exception as exc:
                print(f"[file_processor] SLAM tick error: {exc}")

        # --- YOLO ---------------------------------------------------------
        yolo_dets: list[YoloDetection] = []
        if detector is not None:
            try:
                yolo_dets = detector.detect(bgr)
            except Exception as exc:
                print(f"[file_processor] YOLO error: {exc}")

        # --- depth (only when YOLO produced something) --------------------
        depth_map = None
        if yolo_dets and depth_est is not None:
            try:
                depth_map = depth_est.depth(bgr)
            except Exception as exc:
                print(f"[file_processor] depth error: {exc}")

        # --- fusion: YOLO boxes -> world Entity objects -------------------
        entities = fuse_detections(yolo_dets, camera, current_pose, t_video, depth_map=depth_map)
        slam_entities = local_map.to_entities(t_video)

        # --- normalise boxes for the JSON ---------------------------------
        h, w = bgr.shape[:2]
        inv_w = 1.0 / max(w, 1)
        inv_h = 1.0 / max(h, 1)
        boxes = [
            FrameBox(
                label=d.label,
                confidence=d.confidence,
                cx=float(d.cx_px * inv_w),
                cy=float(d.cy_px * inv_h),
                w=float(d.w_px * inv_w),
                h=float(d.h_px * inv_h),
            )
            for d in yolo_dets
        ]
        detection_count += len(boxes)

        # Combine YOLO-derived + SLAM-derived entities into a flat list the
        # dashboard renders directly on the Map tab.
        merged_entities: list[dict] = []
        for e in list(entities) + list(slam_entities):
            merged_entities.append({
                "id": e.id,
                "type": e.type.value if hasattr(e.type, "value") else str(e.type),
                "label": e.label,
                "x": float(e.position.x),
                "y": float(e.position.y),
                "z": float(e.position.z),
                "confidence": float(e.confidence),
                "source": e.source.value if hasattr(e.source, "value") else str(e.source),
            })

        frames_out.append(FrameSnapshot(t=t_video, boxes=boxes, entities=merged_entities))

        sampled_idx += 1
        frame_idx += 1
        if on_progress is not None and total_frames > 0:
            on_progress(min(1.0, frame_idx / total_frames))

    cap.release()

    result = ProcessedVideo(
        name=video_path.name,
        duration_s=duration_s,
        image_w=width,
        image_h=height,
        sample_fps=effective_fps,
        source_fps=source_fps,
        frames=frames_out,
        summary={
            "frame_count": len(frames_out),
            "detection_count": detection_count,
            "processed_at": time.time(),
        },
    )

    # Serialise. Use dict-of-dict so the JSON keys match the structured types.
    serialisable = {
        "name": result.name,
        "duration_s": result.duration_s,
        "image_w": result.image_w,
        "image_h": result.image_h,
        "sample_fps": result.sample_fps,
        "source_fps": result.source_fps,
        "frames": [
            {
                "t": f.t,
                "boxes": [asdict(b) for b in f.boxes],
                "entities": f.entities,
            }
            for f in result.frames
        ],
        "summary": result.summary,
    }
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(serialisable))
    return result
