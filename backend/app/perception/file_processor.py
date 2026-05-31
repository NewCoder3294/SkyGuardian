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
from .slam import (
    CameraModel, Frame, LocalMap, MonocularVO,
    detect_tags, metric_scale_from_tag,
)
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
    yolo_coco_weights: Optional[str] = None,
    yolo_coco_keep: Optional[list[str]] = None,
    # Optional third "specialty" detector — mirrors the live pipeline's
    # ensemble layout so an upload-only model swap (e.g. weapon-finetuned)
    # works without re-jigging the live config.
    yolo_specialty_weights: Optional[str] = None,
    yolo_specialty_keep: Optional[list[str]] = None,
    yolo_specialty_conf: Optional[float] = None,
    # Optional fourth detector: UAV / drone supervised model.
    yolo_drone_weights: Optional[str] = None,
    yolo_drone_keep: Optional[list[str]] = None,
    yolo_drone_conf: Optional[float] = None,
    yolo_drone_label_overrides: Optional[dict[int, str]] = None,
    depth_model: Optional[str] = None,
    depth_scale: float = 5.0,
    sample_fps: float = 5.0,
    # AprilTag of this physical size (metres) is treated as the metric
    # anchor for the SLAM trajectory: see the live PerceptionPipeline.
    # Unset → no anchor → SLAM positions stay in arbitrary VO units.
    tag_size_m: float = 0.20,
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

    # Optional second detector: supervised COCO YOLOv8. Same ensemble logic
    # as the live PerceptionPipeline — partitions class space.
    coco_detector: YoloDetector | None = None
    coco_keep_set: set[str] = {c.lower() for c in (yolo_coco_keep or [])}
    if yolo_coco_weights:
        try:
            coco_detector = YoloDetector(
                yolo_coco_weights,
                conf_threshold=yolo_conf,
                classes=None,
                imgsz=yolo_imgsz,
            )
        except Exception as exc:
            print(f"[file_processor] COCO ensemble disabled: {exc}")

    # Optional third detector: specialty supervised model. Filters via
    # `specialty_keep_set` so the operator picks which raw labels surface.
    specialty_detector: YoloDetector | None = None
    specialty_keep_set: set[str] = {c.lower() for c in (yolo_specialty_keep or [])}
    if yolo_specialty_weights:
        _spec_conf = yolo_specialty_conf if yolo_specialty_conf is not None else yolo_conf
        try:
            specialty_detector = YoloDetector(
                yolo_specialty_weights,
                conf_threshold=_spec_conf,
                classes=None,
                imgsz=yolo_imgsz,
            )
        except Exception as exc:
            print(f"[file_processor] specialty ensemble disabled: {exc}")

    # Optional fourth detector: UAV/drone model.
    drone_detector: YoloDetector | None = None
    drone_keep_set: set[str] = {c.lower() for c in (yolo_drone_keep or [])}
    if yolo_drone_weights:
        _drone_conf = yolo_drone_conf if yolo_drone_conf is not None else yolo_conf
        try:
            drone_detector = YoloDetector(
                yolo_drone_weights,
                conf_threshold=_drone_conf,
                classes=None,
                imgsz=yolo_imgsz,
                class_label_overrides=yolo_drone_label_overrides,
            )
        except Exception as exc:
            print(f"[file_processor] drone ensemble disabled: {exc}")

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

    # AprilTag metric-anchor state: collect ≥2 tag observations at different
    # camera positions so we can solve for the VO→metres scale once. Mirrors
    # the live PerceptionPipeline anchor loop. Without this the per-frame
    # entities sit in arbitrary VO units, not metres.
    tag_obs_buffer: list[tuple] = []
    anchored = False

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

        # --- AprilTag metric anchor (once, while the tag is in frame) -----
        # Mirrors PerceptionPipeline: accumulate two observations at distinct
        # camera positions, then solve once for the VO→metres scale.
        if not anchored and current_pose is not None:
            try:
                tags = detect_tags(bgr)
            except RuntimeError:
                tags = []
            if tags:
                tag_obs_buffer.append((tags[0], current_pose.position.copy()))
            if len(tag_obs_buffer) >= 2:
                obs_a, vo_a = tag_obs_buffer[0]
                obs_b, vo_b = tag_obs_buffer[-1]
                try:
                    scale = metric_scale_from_tag(
                        camera.K, tag_size_m, obs_a, vo_a, obs_b, vo_b,
                    )
                    local_map.set_anchor(scale)
                    anchored = True
                    print(f"[file_processor] metric anchor: scale={scale:.4f}")
                except ValueError:
                    # Not enough camera motion between the two observations yet.
                    pass

        # --- YOLO (ensemble: open-vocab + supervised COCO + specialty) ---
        yolo_dets: list[YoloDetection] = []
        if detector is not None:
            try:
                yolo_dets.extend(detector.detect(bgr))
            except Exception as exc:
                print(f"[file_processor] world YOLO error: {exc}")
        if coco_detector is not None:
            try:
                coco_dets = coco_detector.detect(bgr)
                if coco_keep_set:
                    coco_dets = [d for d in coco_dets if d.label.lower() in coco_keep_set]
                yolo_dets.extend(coco_dets)
            except Exception as exc:
                print(f"[file_processor] COCO YOLO error: {exc}")
        if specialty_detector is not None:
            try:
                spec_dets = specialty_detector.detect(bgr)
                if specialty_keep_set:
                    spec_dets = [d for d in spec_dets if d.label.lower() in specialty_keep_set]
                yolo_dets.extend(spec_dets)
            except Exception as exc:
                print(f"[file_processor] specialty YOLO error: {exc}")
        if drone_detector is not None:
            try:
                drone_dets = drone_detector.detect(bgr)
                if drone_keep_set:
                    drone_dets = [d for d in drone_dets if d.label.lower() in drone_keep_set]
                yolo_dets.extend(drone_dets)
            except Exception as exc:
                print(f"[file_processor] drone YOLO error: {exc}")

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
                # Lowercase to match the live broadcast normalisation. Avoids
                # the dashboard ending up with `yolo_Gun` and `yolo_gun` as
                # two different world-model slots, and matches the casing the
                # frontend threat-class check expects.
                label=d.label.lower(),
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
