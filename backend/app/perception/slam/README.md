# `slam/` — GPS-less monocular mapping (Track 2 · Brain) ✅ built, tested

## Responsibility
Turn the piloted Mavic's **monocular** video into a metric **local-frame** map —
camera trajectory + sparse landmarks anchored at the launch point — and bridge it
into the `WorldModel`. **No GPS, no lat/lng, no cloud.** Monocular recovers shape
up to an unknown scale; an AprilTag of known size supplies the metre reference.
Full theory in [`../../../../docs/SLAM.md`](../../../../docs/SLAM.md).

## Owns
- `SlamBackend` seam (`backend.py`) — `process_sequence(frames, camera) → Trajectory`
  in arbitrary VO units (`Pose.scale_known=False`) until a metric anchor is applied.
- `MonocularVO` (`vo.py`) — default backend, pure numpy/OpenCV. ORB match →
  essential matrix → `recoverPose` → triangulate → scale-propagated trajectory,
  with a zero-motion gate so a hovering drone doesn't fake drift.
- AprilTag metric anchor (`anchor.py`) — `solvePnP` on a known-size tag → VO-unit→metre scale + origin.
- `LocalMap` (`local_map.py`) — `ingest` a trajectory, `set_anchor` the metric
  scale/origin, then `integrate` entities into the `WorldModel`.
- Core types (`types.py`), EuRoC/TUM trajectory parser (`euroc.py`), optional
  ORB-SLAM3 subprocess backend (`orbslam3_runner.py`).

## The approach: monocular VO local frame + AprilTag metric anchor
A single moving camera recovers structure and motion **only up to scale** — the
map's *shape* is right, its absolute *size* floats. With no GPS, stereo, or IMU,
metres are unknowable from pixels alone. So:
1. `MonocularVO` builds a `Trajectory` in arbitrary VO units (frame 0 = VO origin),
   propagating inter-frame scale by triangulation overlap.
2. A known-size AprilTag (the same soldier-follow tag) observed from two frames
   gives a **metric baseline** between camera centres via PnP; VO gives the same
   baseline in its units. `scale = metric / vo` (`metric_scale_from_tag`).
3. `LocalMap.set_anchor(scale, origin)` fixes metres and makes the launch point the
   local-frame **origin (0,0,0)**; `LocalMap.integrate` then upserts entities into the
   world model.

Frame convention: right-handed, metres, `Xw = R_wc @ Xc + C` (camera-centre `C` in
the local frame). Tracking loss (`< 12` matches, degenerate geometry) holds the
last pose rather than fabricating motion; a near-stationary step (median feature
displacement `< 1.5 px`) is also held, so a hovering drone stays put on the map.

## Pose / local-map data flow
```
Frame[] + CameraModel
   └─ SlamBackend.process_sequence ─► Trajectory   (poses + landmarks, VO units)
        MonocularVO (default)  |  ORBSLAM3Runner (optional)
   LocalMap.ingest(traj)
   LocalMap.set_anchor(scale, origin)              (scale from metric_scale_from_tag)
        scale = metric baseline (PnP) / VO baseline
   LocalMap.integrate(world_model, t, tag_position)
        └─ to_entities ─► WorldModel.upsert         (mavic_cam, anchor_tag, lm_i)
```
A `Pose` carries `R_wc` + `position` in VO units while `scale_known=False`;
`LocalMap._to_metric` applies `(position − origin) * scale` per read (it does not
mutate the stored poses). `camera_position()` returns the latest metric centre.

## Interfaces
- **Reads:** ordered `Frame` sequence (Mavic stream / `captures/` clips) + a
  `CameraModel` (pinhole `K`; `from_resolution(w, h)` gives default intrinsics —
  `focal_factor 0.78 * max(dim)` — when uncalibrated); `TagObservation`s for the anchor.
- **Writes:** `WorldModel.upsert` via `LocalMap.integrate` — `mavic_cam` (`drone`,
  label `mavic`, ttl 3s), `anchor_tag` (`poi` launch marker, ttl 10s, emitted only
  when a `tag_position` is passed), sparse landmarks `lm_{i}` (`object`, ttl 10s),
  all `source=slam`. Mavic confidence is `1.0` once metric, `0.5` while pre-metric.

## Build notes
- `MonocularVO` always runs (pure Python/OpenCV); the geometry core
  (`estimate_relative_pose`, `triangulate`, `relative_scale`, `integrate_step`) is
  image-free and unit-tested with synthetic 3D→2D correspondences.
- `pupil-apriltags` (`detect_tags`) and `ORBSLAM3Runner` are imported/probed
  lazily — modules import and test without the native libs / C++ build present.
- `ORBSLAM3Runner` drops in behind the same seam when a teammate has the binary
  (`ORB_SLAM3_ROOT`, checks `Vocabulary/ORBvoc.txt` + `Examples/Monocular/mono_tum_vi`);
  falls back loudly otherwise. Reimplemented clean from the prior rig — no hardcoded
  paths, no lat/lng projection.
- Tests: `backend/tests/slam/` — anchor, VO geometry, VO pipeline smoke, local map
  (13 tests; synthetic fixtures in `synth.py`, deterministic, no images required).

## Modules
- `types.py` ✅ — `CameraModel`, `Frame`, `Pose`, `Landmark`, `Trajectory`; frame convention.
- `backend.py` ✅ — abstract `SlamBackend` seam.
- `vo.py` ✅ — `MonocularVO` + the testable geometry core.
- `anchor.py` ✅ — AprilTag PnP, metric-scale recovery, lazy tag detector.
- `local_map.py` ✅ — metric re-frame + `WorldModel` entity bridge.
- `euroc.py` ✅ — EuRoC/TUM `ts tx ty tz qx qy qz qw` trajectory parser (GPS-free).
- `orbslam3_runner.py` ✅ — optional ORB-SLAM3 subprocess backend (needs external build).

## Planned
- ⬜ Live anchor resolution loop (auto-detect tag from the stream, call `set_anchor`).
- ⬜ Bundle adjustment / loop closure (today's two-view VO drifts — swap in ORB-SLAM3
  for accuracy behind the same seam).

## Done since first draft
- ✅ Wired into `../fusion.py`: `detection_to_entity` / `fuse_detections` take a `Pose`
  and place YOLO boxes in the local frame — unproject the box centre to a camera ray,
  rotate by `Pose.R_wc`, intersect the ground plane (or scale by a depth map). Falls back
  to the world origin with reduced confidence when `slam_pose` is `None` or not yet metric
  (`scale_known=False`).
