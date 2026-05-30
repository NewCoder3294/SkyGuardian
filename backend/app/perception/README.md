# `perception/` — Mavic recon: YOLO + SLAM (Track 2 · Brain)

## Responsibility
Consume the Mavic video stream → run YOLO detection + monocular SLAM pose →
write detected entities (with local-frame position) into the `WorldModel`.

## Interfaces
- **Reads:** Mavic video (server `FrameSource`); dev against recorded clips in
  `captures/`.
- **Writes:** entities via `WorldModel.upsert` — YOLO-derived detections
  (`source = yolo`) and SLAM map entities (`source = slam`): the `mavic_cam`
  drone pose, a `launch anchor` POI once the tag is seen, and sparse landmarks.

## Build notes
- Local weights only (no cloud) — see `models/`.
- SLAM gives camera pose + a local map frame anchored to launch point +
  landmarks. No GPS.
- Detection runs at recon-rate (default 5 Hz), well below the 20 Hz MJPEG
  relay so the relay is never starved. It never sits in a real-time control
  loop.

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
4. **SLAM entities** — `LocalMap.integrate(world, t)` pushes the mavic_cam drone
   pose and landmarks into the world model.
5. **YOLO** — runs the configured detector(s) on the same frame.
6. **Depth (optional)** — when a depth model is loaded and YOLO produced boxes,
   estimates a per-pixel depth map for the frame.
7. **Fusion** — `fuse_detections` converts each YOLO box + the current SLAM pose
   (+ optional depth) into a local-frame `Entity`, upserted into the world
   model.

The pipeline also caches the latest normalised YOLO boxes
(`PerceptionPipeline.latest_boxes()`) so the server's broadcast loop can overlay
them on the MJPEG stream. Boxes expire after `_STALENESS_WINDOW_S = 2.0` s so the
dashboard goes clean the moment the feed drops.

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
  SLAM pose → local-frame `Entity` (`source = yolo`). With a depth map, scales
  the unprojected camera ray by per-pixel depth for a real 3D position;
  otherwise intersects the ray with the ground plane (z=0). When the pose is
  missing/unscaled (`slam_pose is None or not scale_known`), places the entity
  at the origin with confidence ×0.4 rather than dropping it; when the ground
  ray misses (parallel/behind camera) it falls 3 m down the ray at ×0.5. Maps
  YOLO labels to `EntityType` via `_LABEL_TO_TYPE` (unknown labels → `OBJECT`);
  entities carry a 3 s TTL.
- `file_processor.py` — `process_video_file`: the VOD path. Reuses the same
  primitives (`YoloDetector`, `DepthEstimator`, `fuse_detections`,
  `MonocularVO` + AprilTag, `LocalMap`) across every Nth frame of an uploaded
  video and writes a time-indexed `ProcessedVideo` JSON sidecar so the dashboard
  can scrub detections over an HTML5 `<video>` element.
- `slam/` — **GPS-less monocular mapping.** Pure-Python `MonocularVO` default +
  optional ORB-SLAM3 backend (`ORBSLAM3Runner`), AprilTag metric-scale anchor,
  and `LocalMap` that bridges the trajectory + landmarks into the world model.
  Public API re-exported from `slam/__init__.py`. See [`slam/README.md`](./slam/README.md)
  and [`../../../docs/SLAM.md`](../../../docs/SLAM.md).

Both detectors can run as an ensemble: an open-vocab YOLO-World detector plus a
supervised COCO YOLOv8 detector filtered to an opt-in class set
(`yolo_coco_keep`), partitioning the label space so the same object isn't
double-counted. Same logic in both the live pipeline and `file_processor.py`.
