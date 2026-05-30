#!/usr/bin/env python3
"""Run GPS-less monocular mapping on a recorded video clip (offline dev).

Reimplemented clean — NO lat/lng projection. Samples frames from a video, runs
the pure-Python VO (or ORB-SLAM3 if ORB_SLAM3_ROOT is built), and reports the
local-frame trajectory. Optionally anchors metric scale from an AprilTag of known
size visible in the clip.

Usage:
  python scripts/run_slam_video.py path/to/clip.mp4 [--fps 8] [--tag-size 0.20]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.perception.slam import (  # noqa: E402
    CameraModel, Frame, LocalMap, MonocularVO, ORBSLAM3Runner,
    detect_tags, metric_scale_from_tag,
)


def sample_frames(video: Path, fps: float) -> list[Frame]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video}")
    native = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(native / fps)))
    frames: list[Frame] = []
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            frames.append(Frame(image=img, t=len(frames) / fps))
        i += 1
    cap.release()
    return frames


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--tag-size", type=float, default=None, help="AprilTag edge length (m) for metric scale")
    args = ap.parse_args()

    frames = sample_frames(args.video, args.fps)
    print(f"sampled {len(frames)} frames @ {args.fps} fps")
    if len(frames) < 2:
        raise SystemExit("need >= 2 frames")

    h, w = frames[0].image.shape[:2]
    camera = CameraModel.from_resolution(w, h)

    backend = ORBSLAM3Runner()
    if not backend.available():
        print("ORB-SLAM3 not built -> using pure-Python VO")
        backend = MonocularVO()
    traj = backend.process_sequence(frames, camera)
    print(f"backend={backend.name}  poses={len(traj.poses)}  landmarks={len(traj.landmarks)}")

    mapp = LocalMap()
    mapp.ingest(traj)

    if args.tag_size:
        anchored = _try_anchor(frames, traj, camera, args.tag_size, mapp)
        print("metric scale anchored from AprilTag" if anchored else "no tag pair found; map left in VO units")

    path = [p.position for p in traj.poses]
    total = float(np.sum([np.linalg.norm(path[i] - path[i - 1]) for i in range(1, len(path))]))
    unit = "m" if mapp.metric else "VO-units"
    print(f"path length: {total:.2f} {unit}  (GPS-less, local frame, origin at launch)")


def _try_anchor(frames, traj, camera, tag_size, mapp) -> bool:
    seen = []
    for idx, fr in enumerate(frames):
        try:
            tags = detect_tags(fr.image)
        except RuntimeError:
            return False
        if tags and idx < len(traj.poses):
            seen.append((tags[0], traj.poses[idx].position))
        if len(seen) >= 2:
            break
    if len(seen) < 2:
        return False
    (obs_a, vo_a), (obs_b, vo_b) = seen[0], seen[1]
    scale = metric_scale_from_tag(camera.K, tag_size, obs_a, vo_a, obs_b, vo_b)
    mapp.set_anchor(scale)
    return True


if __name__ == "__main__":
    main()
