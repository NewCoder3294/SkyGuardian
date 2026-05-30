"""YOLO detection on a single frame (local weights, fully offline).

Wraps ultralytics YOLO. The model is loaded once at construction from a local
weights file. If the file is absent, construction raises FileNotFoundError so the
caller (PerceptionPipeline) can set health = "degraded" and skip detection — it
never silently returns empty results pretending to have run.

Output: list of YoloDetection, one per box above the confidence threshold.
The position field is the image-plane box centre in pixels — fusion.py converts
this to a local-frame Vec3 using the current SLAM camera pose.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class YoloDetection:
    label: str          # class name from the model (e.g. "person", "vehicle")
    confidence: float   # 0..1
    cx_px: float        # box centre x in image pixels
    cy_px: float        # box centre y in image pixels
    w_px: float         # box width in pixels
    h_px: float         # box height in pixels


class YoloDetector:
    """Single-model YOLO detector. Thread-safe after construction (weights are
    read-only). Call detect() from any thread; it does not mutate state.

    When the weights file is a YOLO-World checkpoint (filename contains
    "world"), the detector accepts a custom open-vocabulary class list and uses
    YOLOWorld at inference time. Otherwise it runs a stock YOLO model and the
    `classes` argument is ignored. `imgsz` controls inference resolution —
    higher = better small/far targets, slower.
    """

    def __init__(
        self,
        weights_path: str | Path,
        conf_threshold: float = 0.25,
        classes: list[str] | None = None,
        imgsz: int = 640,
    ) -> None:
        path = Path(weights_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"YOLO weights not found: {path}. "
                "Place a YOLOv8 .pt file there (e.g. yolov8s.pt or yolov8l-worldv2.pt). "
                "No cloud download at runtime — distribute weights out-of-band."
            )
        from ultralytics import YOLO, YOLOWorld  # noqa: PLC0415

        is_world = "world" in path.name.lower()
        if is_world:
            self._model = YOLOWorld(str(path))
            # Open-vocab: set the prompt list once at construction. CLIP-encoded
            # at this step, so detect() doesn't pay the cost per frame.
            if classes:
                self._model.set_classes(classes)
        else:
            self._model = YOLO(str(path))

        self._conf = conf_threshold
        self._imgsz = int(imgsz)

    def detect(self, frame_bgr: np.ndarray) -> list[YoloDetection]:
        """Run inference on a single BGR frame. Returns detections above threshold.
        Never returns None; returns an empty list on a clean frame with no detections."""
        results = self._model(
            frame_bgr, conf=self._conf, imgsz=self._imgsz, verbose=False,
        )
        detections: list[YoloDetection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls_idx = int(box.cls[0])
                label = result.names.get(cls_idx, str(cls_idx))
                detections.append(YoloDetection(
                    label=label,
                    confidence=conf,
                    cx_px=(x1 + x2) / 2.0,
                    cy_px=(y1 + y2) / 2.0,
                    w_px=x2 - x1,
                    h_px=y2 - y1,
                ))
        return detections
