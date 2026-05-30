"""Synthetic pinhole projection helpers for deterministic SLAM geometry tests.

No images, no hardware: we place known 3D points, project them through cameras at
known poses, and check the estimators recover the known geometry.
"""
from __future__ import annotations

import numpy as np


def project(K: np.ndarray, R_wc: np.ndarray, C: np.ndarray, Xw: np.ndarray) -> np.ndarray:
    """Project world points Xw (N,3) into pixels for a camera at centre C with
    camera->world rotation R_wc. Returns (N,2)."""
    Xc = (R_wc.T @ (Xw - C).T).T  # world -> camera coords
    proj = (K @ Xc.T).T
    return proj[:, :2] / proj[:, 2:3]


def in_front(R_wc: np.ndarray, C: np.ndarray, Xw: np.ndarray) -> np.ndarray:
    """Camera-frame depth (z) of each world point; positive == in front."""
    Xc = (R_wc.T @ (Xw - C).T).T
    return Xc[:, 2]


def point_cloud(rng: np.random.Generator, n: int = 60) -> np.ndarray:
    """A spread of points in front of a camera looking down +z."""
    xs = rng.uniform(-3.0, 3.0, n)
    ys = rng.uniform(-2.0, 2.0, n)
    zs = rng.uniform(5.0, 12.0, n)
    return np.stack([xs, ys, zs], axis=1)
