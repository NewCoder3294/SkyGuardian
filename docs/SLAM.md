# GPS-less Monocular Mapping

How the recon Mavic feed becomes a metric local map with **no GPS, no internet,
no cloud** — and how it stays honest about what a single camera can and cannot know.

Code: `backend/app/perception/slam/` — `vo.py`, `anchor.py`, `backend.py`,
`local_map.py`, `types.py`, `euroc.py`, `orbslam3_runner.py`. Public API is
re-exported from the package `__init__`.

## The hard problem: monocular scale

The Mavic feed is **monocular** (one camera, piloted, no IMU/odometry reaches us).
A single moving camera recovers structure and motion **only up to an unknown scale
factor** — the map's *shape* is correct, but its absolute *size* floats. With no
GPS, no stereo, and no IMU, "4.2 metres" is unknowable from pixels alone. Every
honest monocular system needs an external metric reference.

## Our answer: the AprilTag metric anchor

We already carry AprilTags (the soldier-follow tag). A tag of **known physical
size**, placed at the launch area, supplies the missing reference (`anchor.py`):

- `tag_camera_pose` solves the camera centre relative to the tag (metres) via
  `cv2.solvePnP` with `SOLVEPNP_IPPE_SQUARE` and the known edge length.
- `metric_scale_from_tag` observes the tag from two frames whose VO positions we
  know. The tag gives a **metric baseline** between the two camera centres; VO
  gives the **same baseline in its own units**; `scale = metric / vo`. It raises
  `ValueError` if the VO baseline is ~0 (no camera motion between observations).

The launch point becomes the local-frame **origin (0,0,0)**. No lat/lng anywhere.

Tag detection (`detect_tags`) uses `pupil-apriltags` (`tag36h11`), imported lazily
so the geometry stays importable/testable without the native library. The four
corners are reordered to TL, TR, BR, BL to match `tag_object_points`.

## Frame convention (`types.py`)

Right-handed, metres, anchored at the launch point. A camera-frame point `Xc`
maps to the local world frame as `Xw = R_wc @ Xc + C`, where `R_wc` is the
camera→world rotation and `C` is the camera centre. `CameraModel` is a pinhole
model (no distortion); `CameraModel.from_resolution(w, h)` supplies default
intrinsics (`f = 0.78 * max(w, h)`, principal point at image centre) when no
calibration is available. A `Pose` carries `scale_known` (False while still in VO
units) and a `scaled(scale, origin)` helper that re-expresses it in metres.

## Pipeline

```
Mavic frames ──▶ SlamBackend.process_sequence ──▶ Trajectory (VO units)
                   │                                      │
                   ├─ MonocularVO (default, pure Python)  │
                   └─ ORBSLAM3Runner (optional, subprocess)│
AprilTag (known size) ─▶ metric_scale_from_tag ──▶ scale ─┤
                                                          ▼
                                              LocalMap (metres, origin=launch)
                                                          │
                                                          ▼
                                          WorldModel.upsert  (mavic_cam=drone,
                                          anchor_tag=poi, lm_*=object)
```

## Backends (swappable behind `SlamBackend`)

`backend.py` defines the seam: `process_sequence(frames, camera) -> Trajectory`,
output always in arbitrary VO units until a metric anchor is applied downstream.

- **MonocularVO** (`vo.py`, `name = "python-vo"`) — pure Python/OpenCV, always
  runs, no native build. Per step: ORB features (1500 by default) →
  brute-force Hamming match (cross-check, sorted by distance) → essential matrix
  (`cv2.findEssentialMat`, RANSAC, `prob=0.999`, `threshold=1.0`) →
  `cv2.recoverPose` for the relative pose (returns a **unit-norm** translation
  direction) → triangulation of the inliers. Inter-frame scale is propagated by
  comparing inter-point distances of overlapping triangulated landmarks across
  consecutive steps (`relative_scale`, the **median** over all point-pair distance
  ratios `d_prev / d_curr`); the running `step_scale` is multiplied by that factor
  each step and fed to `integrate_step` as the step translation magnitude. The
  geometry core (`estimate_relative_pose`, `triangulate`, `relative_scale`,
  `integrate_step`) is plain numpy/OpenCV and is unit-tested with synthetic 3D→2D
  projections — no images needed.

  Two honesty gates keep a *hovering* drone from drifting on the map:
  - **Tracking loss**: fewer than `_MIN_MATCHES` (12) matches, or a failed
    essential-matrix estimate → hold the previous pose, append it unchanged, and
    reset the scale-propagation overlap (no fabricated motion).
  - **Zero-motion gate**: median feature displacement below `_ZERO_MOTION_PX`
    (1.5 px) → hold pose, but keep the prior reconstruction so the next *real*
    motion step still scales correctly.

  Up to ~20 triangulated points per step (`curr_pts3[:: max(1, len//20)]`) are
  recorded as low-confidence (0.4) world-frame landmarks for the map view, mapped
  into the world frame via the *previous* pose (`R_wc_prev_dot`).

- **ORBSLAM3Runner** (`orbslam3_runner.py`, `name = "orbslam3"`) — optional.
  Wraps an externally-built ORB-SLAM3 binary via subprocess (set `ORB_SLAM3_ROOT`,
  or pass `root=`). It writes sampled frames as PNGs plus a timestamps file and a
  generated `camera.yaml`, then runs `Examples/Monocular/mono_tum_vi` against
  `Vocabulary/ORBvoc.txt`. `available()` / `orbslam_available()` check for both
  files before running and the call raises `FileNotFoundError` if absent. The
  resulting trajectory (`f_recon.txt`, falling back to `CameraTrajectory.txt`) is
  parsed by `euroc.py`. Bundle-adjusted + loop closure. Ported clean from the
  prior rig — **no hardcoded path, no lat/lng projection**.

`euroc.py` parses `timestamp tx ty tz qx qy qz qw` lines into local-frame poses
(`scale_known=False`). There is deliberately **no geo / lat-lng projection** — raw
local frame only.

## LocalMap → world model (`local_map.py`)

`LocalMap.ingest(trajectory)` stores poses + landmarks. `set_anchor(scale, origin)`
fixes the VO-unit→metre scale and the launch origin (`scale <= 0` raises). Two
state flags: `metric` (a scale has been applied — positions are real metres) and
`anchored`. Before a scale is set, `_to_metric` falls back to `scale = 1.0`, so the
map renders in VO units rather than failing.

`to_entities(t, tag_position=)` / `integrate(world_model, t, tag_position=)` upsert
world-model entities (`source=EntitySource.SLAM`):

- `mavic_cam` — the latest Mavic camera centre as a `DRONE` entity, label
  `"mavic"`, confidence 1.0 when metric else 0.5, `ttl_s=3.0`.
- `anchor_tag` — the launch tag as a `POI`, label `"launch anchor"`, `ttl_s=10.0`
  (so it disappears from the dashboard once SLAM stops refreshing it).
- `lm_{i}` — sparse landmarks as low-confidence `OBJECT` entities, `ttl_s=10.0`.

## Honest limitations

- Two-view VO **drifts** and has no loop closure — use the ORB-SLAM3 backend for
  longer/accurate runs.
- Absolute scale needs the tag visible in ≥2 frames with camera motion between
  them; without it the map is geometrically correct but scale-free (VO units).
- **Gravity alignment** (true up) needs an IMU or a ground-plane fit — a future
  refinement; the current local frame is gauge-consistent but not gravity-aligned.
- For survey-grade orthophotos use photogrammetry (COLMAP/ODM), not VO.

## Run it (offline, on a recorded clip)

```bash
cd backend && source .venv/bin/activate
python ../scripts/run_slam_video.py ../captures/mavic/clip.mp4 --fps 8 --tag-size 0.20
```

`run_slam_video.py` samples frames from the clip, prefers `ORBSLAM3Runner` when
`available()` else falls back to `MonocularVO`, and prints the local-frame path
length. `--tag-size` is optional (default off); when given, it anchors metric
scale from the first two frames in which the tag is detected, otherwise the map
is left in VO units.

Tests: `cd backend && .venv/bin/python -m pytest tests/slam -q`
(16 tests — VO geometry, VO caching, anchor, local map, pipeline smoke; helpers in
`tests/slam/synth.py`).
