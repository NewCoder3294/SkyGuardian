"""Optional ORB-SLAM3 backend — ported skeleton from the prior rig, GPS stripped.

Wraps an externally-built ORB-SLAM3 ``mono`` binary via subprocess, implementing
the same SlamBackend interface as MonocularVO so it drops in when a teammate has
the C++ build available. Unlike the prior version: no hardcoded user path, no
lat/lng projection — output is the raw local frame. Falls back loudly if the
binary is absent; the pure-Python VO is the default that always runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

import cv2

from .backend import SlamBackend
from .euroc import parse_euroc_trajectory
from .types import CameraModel, Frame, Trajectory


def orbslam_available(root: Path) -> bool:
    root = Path(root).expanduser()
    vocab = root / "Vocabulary" / "ORBvoc.txt"
    binary = root / "Examples" / "Monocular" / "mono_tum_vi"
    return vocab.is_file() and binary.is_file()


class ORBSLAM3Runner(SlamBackend):
    name = "orbslam3"

    def __init__(self, root: str | os.PathLike | None = None, fps: float = 15.0) -> None:
        env_root = os.environ.get("ORB_SLAM3_ROOT")
        self.root = Path(root or env_root or "").expanduser()
        self.fps = fps

    def available(self) -> bool:
        return bool(self.root) and orbslam_available(self.root)

    def process_sequence(self, frames: Sequence[Frame], camera: CameraModel) -> Trajectory:
        if not self.available():
            raise FileNotFoundError(
                f"ORB-SLAM3 not built at {self.root!s} (need Vocabulary/ORBvoc.txt and "
                "Examples/Monocular/mono_tum_vi). Use the python-vo backend instead."
            )
        work = Path(tempfile.mkdtemp(prefix="orbslam_"))
        try:
            frames_dir = work / "frames"
            frames_dir.mkdir()
            stamps = []
            for i, fr in enumerate(frames):
                ts = int(i * (1e9 / self.fps))
                cv2.imwrite(str(frames_dir / f"{ts}.png"), fr.image)
                stamps.append(str(ts))
            (work / "timestamps.txt").write_text("\n".join(stamps) + "\n")
            self._write_camera_yaml(work / "camera.yaml", camera)

            vocab = self.root / "Vocabulary" / "ORBvoc.txt"
            binary = self.root / "Examples" / "Monocular" / "mono_tum_vi"
            cmd = [str(binary), str(vocab), str(work / "camera.yaml"),
                   str(frames_dir), str(work / "timestamps.txt"), "recon"]
            proc = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True, timeout=3600)
            if proc.returncode != 0:
                raise RuntimeError(f"mono_tum_vi failed ({proc.returncode}): {proc.stderr[-2000:]}")
            traj_file = self.root / "f_recon.txt"
            if not traj_file.is_file():
                traj_file = self.root / "CameraTrajectory.txt"
            poses = parse_euroc_trajectory(traj_file)
            return Trajectory(poses=poses, landmarks=[])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _write_camera_yaml(self, path: Path, camera: CameraModel) -> None:
        path.write_text(
            "%YAML:1.0\n"
            "Camera.type: \"PinHole\"\n"
            f"Camera1.fx: {camera.fx:.4f}\nCamera1.fy: {camera.fy:.4f}\n"
            f"Camera1.cx: {camera.cx:.4f}\nCamera1.cy: {camera.cy:.4f}\n"
            "Camera1.k1: 0.0\nCamera1.k2: 0.0\nCamera1.p1: 0.0\nCamera1.p2: 0.0\n"
            f"Camera.fps: {int(round(self.fps))}\nCamera.RGB: 1\n"
            "ORBextractor.nFeatures: 1500\nORBextractor.scaleFactor: 1.2\n"
            "ORBextractor.nLevels: 8\nORBextractor.iniThFAST: 20\nORBextractor.minThFAST: 7\n"
        )
