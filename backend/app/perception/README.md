# `perception/` — Mavic recon: YOLO + SLAM (Track 2 · Brain)

## Responsibility
Consume the Mavic video stream → run YOLO detection + monocular SLAM pose →
write detected entities (with local-frame position) into the `WorldModel`.

## Interfaces
- **Reads:** Mavic video (server `FrameSource`); dev against recorded clips in
  `captures/`.
- **Writes:** entities via `WorldModel.upsert` — YOLO-derived detections
  (`source = yolo`, `EntitySource.YOLO`) and SLAM map entities
  (`source = slam`, `EntitySource.SLAM`): the `mavic_cam` drone pose
  (`EntityType.DRONE`), sparse landmarks (`lm_*`, `EntityType.OBJECT`), and —
  only when a tag position is passed to `LocalMap.integrate`/`to_entities` — an
  `anchor_tag` POI labelled `launch anchor`. The live loop integrates **without**
  a tag position, so the launch-anchor POI currently appears only on the VOD
  (`file_processor`) path.

## Build notes
- Local weights only (no cloud) — see `models/`.
- SLAM gives camera pose + a local map frame anchored to launch point +
  landmarks. No GPS.
- Detection runs at recon-rate (`PERCEPTION_FPS`, default 5 Hz), well below the
  20 Hz MJPEG relay so the relay is never starved. It never sits in a real-time
  control loop.

### Config (env, read by `server.py` when it constructs the pipeline)
- `YOLO_WEIGHTS` — primary detector weights path. Unset → `server.py` falls back
  to the best bundled COCO model under `models/` (prefers `yolov8s.pt` over
  `yolov8n.pt`); with no weights at all, perception degrades to SLAM-only.
  `off` explicitly disables the primary detector (COCO/specialty only).
- `YOLO_CLASSES` — comma-separated open-vocab prompt list. Unset defaults to
  `server.py` `_DEFAULT_VOCAB` (defense-relevant prompts) **only** when the
  weights filename contains `world`; for a stock COCO model it stays `None`.
- `YOLO_IMGSZ` (default `960`), `YOLO_CONF` (default `0.20`).
- `YOLO_COCO_WEIGHTS` / `YOLO_COCO_KEEP` — optional second supervised COCO
  detector and the class set it is filtered to (default keep set applied when
  COCO weights are set; classes in the keep set are stripped from the
  open-vocab prompt list so the two detectors don't overlap).
- `YOLO_SPECIALTY_WEIGHTS` / `YOLO_SPECIALTY_KEEP` / `YOLO_SPECIALTY_CONF` —
  optional third detector (e.g. a weapons-finetuned YOLOv8) with its own class
  allowlist (unset → all classes pass) and its own confidence threshold (unset →
  uses `YOLO_CONF`), so a noisy fine-tuned model can run strict while the others
  stay relaxed for recall.
- `YOLO_DEVICE` / `DEPTH_DEVICE` — inference device overrides (`cpu`/`mps`/
  `cuda:0`); unset → auto-detect (MPS, then CUDA, then the library default).
- `DEPTH_MODEL` (default `depth-anything/Depth-Anything-V2-Small-hf`, `off`
  disables), `DEPTH_SCALE` (default `5.0`).
- `ANCHOR_TAG_SIZE_M` (default `0.20`) — physical AprilTag edge length used for
  metric-scale anchoring.
- `PERCEPTION_FPS` (default `5`) — also drives `file_processor`'s `sample_fps`.

## Data flow
The live loop lives in `pipeline.py` (`PerceptionPipeline`), started once from
`server.py` at startup. Each tick it:

1. Reads a JPEG frame from the video source, decodes to BGR.
2. **SLAM** — feeds a sliding window of frames (`_WINDOW = 8`, ~1.6 s @ 5 Hz) to
   `MonocularVO.process_sequence` to get a local-frame camera trajectory.
   `process_sequence` takes a sequence, so the loop runs on an accumulated
   window rather than incrementally.
3. **AprilTag metric anchor (once)** — buffers two tag observations with camera
   motion between them, then calls `metric_scale_from_tag` and
   `LocalMap.set_anchor(scale)` to make the map metric. Until anchored, the map
   is up-to-scale only.
4. **SLAM entities** — `LocalMap.integrate(world, t)` pushes the `mavic_cam`
   drone pose, sparse landmarks, and (when a tag position is passed) a `launch
   anchor` POI into the world model. The live loop currently integrates without
   a tag position; `LocalMap.to_entities` is the same path `file_processor` uses
   to emit those entities for the VOD sidecar.
5. **YOLO** — runs the configured detector(s) on the same frame.
6. **Depth (optional)** — when a depth model is loaded and YOLO produced boxes,
   estimates a per-pixel depth map for the frame.
7. **Fusion** — `fuse_detections` converts each YOLO box + the current SLAM pose
   (+ optional depth) into a local-frame `Entity`, upserted into the world
   model.

The pipeline also caches the latest normalised YOLO boxes
(`PerceptionPipeline.latest_boxes()`) so the server's broadcast loop can overlay
them on the MJPEG stream. Boxes expire after `_STALENESS_WINDOW_S = 6.0` s so the
dashboard goes clean once the feed drops — sized to outlive one full ensemble YOLO
(+ depth) tick (~2.6 s/frame on M-series), which a 2 s window would have starved.

### Health string (read by `server.py`)
- `ok` — running, weights loaded, SLAM anchored (metric).
- `running` — running but not yet metric (tag not seen yet).
- `degraded` — running but YOLO weights missing / ultralytics absent; SLAM-only.
- `error` — fatal startup error; pipeline not running.

`reset()` clears detection state and flags a SLAM rebuild on the next tick
(without stopping the loop). The server calls it when the operator swaps the
leader source (RTMP ↔ uploaded video), since the old anchor/landmarks are
invalid in the new feed's coordinate frame.

## Modules
- `pipeline.py` — `PerceptionPipeline`: the live asyncio loop wiring SLAM,
  AprilTag anchor, YOLO, depth, and fusion into the world model.
- `yolo.py` — `YoloDetector` + `YoloDetection`. Wraps ultralytics. Loads a stock
  `YOLO` model, or `YOLOWorld` (open-vocab, custom class prompts) when the
  weights filename contains `world`. Missing weights raise `FileNotFoundError`
  so the pipeline can degrade rather than silently no-op. Output boxes are
  image-plane pixel centres + dims.
- `depth.py` — `DepthEstimator`: HuggingFace transformers `depth-estimation`
  pipeline around DepthAnything-V2-Small (default
  `depth-anything/Depth-Anything-V2-Small-hf`). Outputs relative inverse depth
  converted to approximate metres via a heuristic `scale` (default 5.0).
  Optional; absence falls fusion back to the ground-plane path.
- `fusion.py` — `fuse_detections` / `detection_to_entity`: image-plane box +
  SLAM pose → local-frame `Entity` (`source = yolo`). With a depth map **and** an
  anchored pose (`slam_pose.scale_known`), scales the unprojected camera ray by
  per-pixel depth for a real 3D position; otherwise intersects the ray with the
  ground plane (z=0) at reduced confidence (×0.6 while pre-anchor). When the pose
  is missing (`slam_pose is None`), places the entity at the origin with
  confidence ×0.4 rather than dropping it; when the ground ray misses
  (parallel/behind camera) it falls 3 m down the ray at ×0.5. Maps YOLO labels to
  `EntityType` via `_LABEL_TO_TYPE` (`person`/`soldier` → `SOLDIER`; `hazard`/
  `debris`/`obstacle` → `HAZARD`; `door`/`doorway`/`entrance`/`building` → `POI`;
  `car`/`truck`/`vehicle` and any unlisted label → `OBJECT`). Entity IDs bucket
  the **world** position to a ~2 m grid (`yolo_<label>_<bx>_<by>`) so a stationary
  object re-uses its world-model slot across frames and a person only re-enters
  the map when they actually move >1 m — the previous pixel-bucket scheme spawned
  a new dot on every few-pixel jitter. When unanchored (origin fallback) the label
  alone keys the entity (`yolo_<label>`, one slot per class). Entities carry a 3 s
  TTL (`source = yolo`).
- `file_processor.py` — `process_video_file`: the VOD path. Reuses the same
  primitives (`YoloDetector` + the optional COCO ensemble, `DepthEstimator`,
  `fuse_detections`, `MonocularVO`, `LocalMap`) across every Nth frame
  (`sample_stride = round(source_fps / sample_fps)`) of an uploaded video and
  writes a time-indexed `ProcessedVideo` JSON sidecar so the dashboard can scrub
  detections over an HTML5 `<video>` element. Each frame snapshot carries both
  normalised image-plane boxes and the merged YOLO + SLAM (`LocalMap.to_entities`)
  3D entities for the Map tab. `process_video_file` defaults match the live loop
  (`yolo_imgsz` 960, `yolo_conf` 0.20) and accept the optional COCO ensemble
  (no specialty detector on this path). SLAM/AprilTag anchoring here is
  best-effort (logged only on error); it never raises out of the per-frame tick.
- `slam/` — **GPS-less monocular mapping.** Pure-Python `MonocularVO` default +
  optional ORB-SLAM3 backend (`ORBSLAM3Runner`), AprilTag metric-scale anchor,
  and `LocalMap` that bridges the trajectory + landmarks into the world model.
  Public API re-exported from `slam/__init__.py`. See [`slam/README.md`](./slam/README.md)
  and [`../../../docs/SLAM.md`](../../../docs/SLAM.md).

Up to three detectors can run as an ensemble: an open-vocab YOLO-World detector,
a supervised COCO YOLOv8 detector filtered to an opt-in class set
(`yolo_coco_keep`), and an optional specialty detector filtered to
`yolo_specialty_keep` with its own confidence threshold (`yolo_specialty_conf`).
`_run_detectors` merges them, partitioning the label space so the same object
isn't double-counted. Same logic in both the live pipeline and
`file_processor.py`. (The COCO + specialty ensemble is what `run-indoor.sh` /
`run-outdoor.sh` configure.)
