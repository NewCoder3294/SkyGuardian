"""Monocular depth estimation (offline) for fusion's Z coordinate.

Wraps the HuggingFace transformers `depth-estimation` pipeline around
DepthAnything-V2-Small. Weights are cached locally on first use, then load
fully offline. Returns a per-pixel depth map in approximate metres so
fusion can place each detected object at a real 3D position instead of
clamping it to the ground plane.

Honesty notes:
- DepthAnything outputs *relative inverse depth*. We convert to approximate
  metres via `metres ≈ scale / max(predicted, eps)`. The scale is a heuristic
  (env-tunable). For accurate metric depth, calibrate against SLAM landmarks
  once anchored — future work.
- Inference is single-frame; runs at ~100–300 ms per frame on M-series CPU.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


class DepthEstimator:
    """Lazy-loaded DepthAnything-V2 wrapper. Construct once; call depth() per
    frame. Thread-safe after construction (model is read-only)."""

    def __init__(
        self,
        model_name: str = "depth-anything/Depth-Anything-V2-Small-hf",
        scale: float = 5.0,
        device: Optional[str] = None,
    ) -> None:
        from transformers import pipeline  # noqa: PLC0415
        # device=-1 forces CPU; "mps" works on Apple Silicon for ~3x speedup.
        kwargs = {"task": "depth-estimation", "model": model_name}
        if device is not None:
            kwargs["device"] = device
        self._pipe = pipeline(**kwargs)
        self._scale = float(scale)

    def depth(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Run depth inference on a single BGR frame.

        Returns a float32 array shaped like the input (HxW) where each entry
        is an estimated distance from the camera in metres."""
        import cv2  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        out = self._pipe(img)
        inv = out["predicted_depth"].cpu().numpy().astype(np.float32)

        h, w = frame_bgr.shape[:2]
        if inv.shape != (h, w):
            inv = cv2.resize(inv, (w, h), interpolation=cv2.INTER_LINEAR)

        # DepthAnything outputs inverse depth; convert to metres.
        metres = self._scale / np.maximum(inv, 1e-3)
        return metres
