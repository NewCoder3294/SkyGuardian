# `slam/` — GPS-less monocular mapping (Track 2 · Brain) ✅ built, tested

## Responsibility
Turn the piloted Mavic's **monocular** video into a metric **local-frame** map —
camera trajectory + sparse landmarks anchored at the launch point — and bridge it
into the `WorldModel`. **No GPS, no lat/lng, no cloud.** Monocular recovers shape
up to an unknown scale; an AprilTag of known size supplies the metre reference.
Full theory in [`../../../../docs/SLAM.md`](../../../../docs/SLAM.md).

## Owns
- `SlamBackend` seam (`backend.py`) — `process_sequence(frames, camera) → Trajectory`
  in arbitrary VO units (`scale_known=False`) until a metric anchor is applied.
- `MonocularVO` (`vo.py`) — default backend, pure numpy/OpenCV. ORB match →
  essential matrix → `recoverPose` → triangulate → scale-propagated trajectory.
- AprilTag metric anchor (`anchor.py`) — `solvePnP` on a known-size tag → VO-unit→metre scale + origin.
- `LocalMap` (`local_map.py`) — metric re-frame + `WorldModel` entity emission.
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
   local-frame **origin (0,0,0)**, then upserts entities into the world model.

Frame convention: right-handed, metres, `Xw = R_wc @ Xc + C` (camera-centre `C` in
the local frame). Tracking loss holds the last pose rather than fabricating motion.

## Interfaces
- **Reads:** ordered `Frame` sequence (Mavic stream / `captures/` clips) + a
  `CameraModel` (pinhole `K`; `from_resolution` gives default intrinsics when
  uncalibrated); `TagObservation`s for the anchor.
- **Writes:** `WorldModel.upsert` via `LocalMap.integrate` — `mavic_cam` (`drone`),
  `anchor_tag` (`poi` launch marker), sparse landmarks (`object`), all
  `source=slam`. Confidence drops to 0.5 while the map is pre-metric.

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
- ⬜ Wire into `../fusion.py` so YOLO boxes get local-frame positions from SLAM pose.
