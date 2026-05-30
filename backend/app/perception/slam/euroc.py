"""Parse ORB-SLAM3 / EuRoC trajectory files into local-frame poses.

Reimplemented clean from the prior approach. Crucially, there is NO geo / lat-lng
projection here — output is the raw local frame (metres in VO units), GPS-free.
Format per line: ``timestamp tx ty tz qx qy qz qw``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .types import Pose


def _quat_to_R(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    n = (qx * qx + qy * qy + qz * qz + qw * qw) ** 0.5 + 1e-12
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ], dtype=np.float64)


def parse_euroc_trajectory(path: Path) -> list[Pose]:
    poses: list[Pose] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        t = float(parts[0])
        tx, ty, tz = (float(parts[1]), float(parts[2]), float(parts[3]))
        qx, qy, qz, qw = (float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7]))
        poses.append(Pose(
            t=t,
            R_wc=_quat_to_R(qx, qy, qz, qw),
            position=np.array([tx, ty, tz], dtype=np.float64),
            scale_known=False,
        ))
    return poses
