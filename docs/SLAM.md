# GPS-less Monocular Mapping

How the recon Mavic feed becomes a metric local map with **no GPS, no internet,
no cloud** — and how it stays honest about what a single camera can and cannot know.

## The hard problem: monocular scale

The Mavic feed is **monocular** (one camera, piloted, no IMU/odometry reaches us).
A single moving camera recovers structure and motion **only up to an unknown scale
factor** — the map's *shape* is correct, but its absolute *size* floats. With no
GPS, no stereo, and no IMU, "4.2 metres" is unknowable from pixels alone. Every
honest monocular system needs an external metric reference.

## Our answer: the AprilTag metric anchor

We already carry AprilTags (the soldier-follow tag). A tag of **known physical
size**, placed at the launch area, supplies the missing reference:

- Observed from two frames whose VO positions we know, the tag gives a **metric
  baseline** between the two camera centres (via `solvePnP` with the known edge length).
- VO gives the **same baseline in its own units**.
- `scale = metric_baseline / vo_baseline` — the VO-unit → metre factor for the whole map.

The launch point becomes the local-frame **origin (0,0,0)**. No lat/lng anywhere.

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
                                          anchor_tag=poi, landmarks=object)
```

## Backends (swappable behind `SlamBackend`)

- **MonocularVO** — pure Python/OpenCV. ORB features → essential matrix → relative
  pose; triangulation propagates inter-frame scale. Always runs, no native build.
  Geometry core is unit-tested with synthetic 3D→2D projections (no images needed).
- **ORBSLAM3Runner** — optional. Wraps an externally-built ORB-SLAM3 `mono` binary
  via subprocess (set `ORB_SLAM3_ROOT`). Bundle-adjusted + loop closure. Ported
  clean from the prior rig — **no hardcoded path, no lat/lng projection**. Falls
  back loudly if the binary is absent.

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

Tests: `pytest tests/slam -q` (13 tests — geometry, anchor, map, pipeline).
