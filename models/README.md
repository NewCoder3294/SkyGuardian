# `models/` — Local model weights (offline, no cloud)

All inference runs on local hardware. Weights live here (or anywhere on disk you
point the brain at), **git-ignored** as large binaries — distribute out-of-band
among the team. `.gitignore` excludes `models/**/*.{pt,pth,onnx,bin,mlpackage}`
(the `.mlpackage` glob covers the CoreML bundle the mobile app ships on-device),
so only this README is tracked.

## Owns
Local-only weight files for the perception subsystems. Nothing here is fetched
from the network at runtime.

## How the brain finds weights
The brain does **not** auto-scan this directory. Paths are passed via environment
variables, read in `backend/app/server.py` and handed to `PerceptionPipeline`
(`backend/app/perception/pipeline.py`), which constructs one `YoloDetector`
(`backend/app/perception/yolo.py`) for the primary open-vocab model and an
optional second `YoloDetector` for the COCO ensemble. `models/` is just the
conventional place to keep the files the env vars point at.

| Env var | What it points at | Default |
|---|---|---|
| `YOLO_WEIGHTS` | Primary detector `.pt`. A YOLO-World checkpoint (filename contains `world`) runs open-vocab via `YOLOWorld`; anything else runs stock `YOLO`. | unset → fall back to the best bundled COCO model in `models/` (`yolov8s.pt` preferred over `yolov8n.pt`), so recon detection + target designation work out of the box. `YOLO_WEIGHTS=off` is an explicit disable (no primary detector; SLAM-only unless a COCO/specialty detector is configured). No bundled weight present → SLAM-only. |
| `YOLO_CLASSES` | Comma-separated open-vocab prompt list for a `-world` checkpoint. | a defense-relevant default vocab (`server.py` `_DEFAULT_VOCAB`: person, soldier, gun, rifle, knife, backpack, vehicle, drone, ied, …) when a `-world` checkpoint is loaded |
| `YOLO_COCO_WEIGHTS` | Optional second detector — stock COCO YOLOv8 — ensembled with the open-vocab one. The kept classes are pruned from the YOLO-World vocab so the same object isn't double-detected; both detectors' boxes are merged. | unset → no COCO ensemble |
| `YOLO_COCO_KEEP` | Comma-separated COCO labels to trust over open-vocab (lowercased; COCO boxes outside this set are dropped). | `person,car,truck,motorcycle,bicycle,bus,backpack` when `YOLO_COCO_WEIGHTS` is set |
| `YOLO_IMGSZ` | Inference resolution (applies to both detectors). | `960` |
| `YOLO_CONF` | Confidence threshold (applies to both detectors). | `0.20` |
| `DEPTH_MODEL` | Monocular depth model (HuggingFace id, downloaded once to the HF cache); set `off` to disable. | `depth-anything/Depth-Anything-V2-Small-hf` |
| `ORB_SLAM3_ROOT` | Root of an externally-built ORB-SLAM3 (see SLAM below). | unset → pure-Python VO |

The **default recon model is now stock `yolov8s`** (COCO classes): with
`YOLO_WEIGHTS` unset, the brain auto-selects the best bundled COCO weight in
`models/`, preferring `yolov8s.pt` over `yolov8n.pt`, so recon detection + target
designation work out of the box. A stock checkpoint ignores `YOLO_CLASSES`.
Open-vocabulary defense detection (a YOLO-World checkpoint, e.g.
`yolov8l-worldv2.pt`, filename containing `world`, driven by the built-in defense
vocab) is the heavier follow-up you opt into by pointing `YOLO_WEIGHTS` at the
`-world` file — not the default.

## Expected contents
Drop-in locations for each subsystem's weights. Subdirectories are created
out-of-band when the weights land — only this README is tracked. The paths below
are conventions; what actually matters is the env var.
- ⬜ `yolo/` — detector weights for the Mavic recon perception path. The default
  is a stock COCO checkpoint (`yolov8s.pt`, with `yolov8n.pt` as the lighter
  fallback) auto-selected when `YOLO_WEIGHTS` is unset; point `YOLO_WEIGHTS` at a
  `-world` checkpoint (e.g. `yolov8l-worldv2.pt`) to opt into open-vocab, and
  optionally `YOLO_COCO_WEIGHTS` at a stock checkpoint for the COCO ensemble. The
  laptop loads `.pt` weights; the mobile app's on-device Tello detector ships a
  separate CoreML `yolov8n.mlpackage` (COCO, NMS baked in), also git-ignored.
- ✅ `slam/` — the pure-Python monocular VO (`perception/slam/vo.py`) is the
  default backend and needs **no weights**. The optional ORB-SLAM3 backend
  (`perception/slam/orbslam3_runner.py`) is a separate externally-built C++ tree
  located via `ORB_SLAM3_ROOT`, expecting `Vocabulary/ORBvoc.txt` and
  `Examples/Monocular/mono_tum_vi`; it is not a drop-in `.pt` file. See
  [`../docs/SLAM.md`](../docs/SLAM.md).
- 🟡 `gemma/` — on-device Gemma weights for the mobile voice + vision layer are
  loaded on the phone via Cactus, **not** by the laptop brain — they do not live
  in this directory at runtime. Listed here only for completeness. See
  [`../docs/VOICE.md`](../docs/VOICE.md).

The monocular depth model (`DEPTH_MODEL`) is the one exception to "weights live
here": it is a HuggingFace model id resolved into the HF cache on first load, not
a file in `models/`.

## Rule
No model is fetched from the network at runtime once cached (offline-first).
Pre-download any HF depth model before going offline. If a YOLO weights file is
absent, `YoloDetector` raises `FileNotFoundError` and the pipeline degrades
loudly (`health = "degraded"`, SLAM-only) — it never silently returns empty
detections pretending to have run.
