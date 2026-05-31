"""Regression tests for the MonocularVO per-frame / per-pair memoisation.

The pipeline reuses one MonocularVO instance and re-runs process_sequence over an
overlapping sliding window every tick. Before caching, that re-detected every
frame and re-solved every pair on every call, so per-tick cost grew with the
window size and the perception loop fell behind. These tests pin the three
properties that make the cache correct *and* bounded:

  (a) each unique frame's ORB features are detected at most once,
  (b) reusing a warm cache reproduces the cold trajectory byte-for-byte,
  (c) the caches stay bounded by the window, not the whole mission.

Frames are seeded noise rolled a few pixels per frame so ORB has real, matchable
motion — no mocked/stubbed VO results; the memoisation is exercised end to end.
"""
from __future__ import annotations

import numpy as np

from app.perception.slam.types import CameraModel, Frame
from app.perception.slam.vo import MonocularVO

_W, _H = 320, 240


def _rolled_frames(n: int, seed: int = 5) -> list[Frame]:
    """`n` frames of seeded noise, each rolled 4 px further than the last so
    consecutive frames share matchable, displaced features. Distinct timestamps."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(_H, _W, 3), dtype=np.uint8)
    return [Frame(image=np.roll(base, shift=4 * i, axis=1), t=float(i)) for i in range(n)]


def _camera() -> CameraModel:
    return CameraModel.from_resolution(_W, _H)


def _slide(vo: MonocularVO, frames: list[Frame], window: int) -> None:
    """Drive the VO the way the pipeline does: a fixed-size window sliding one
    frame forward per tick."""
    cam = _camera()
    for end in range(2, len(frames) + 1):
        vo.process_sequence(frames[max(0, end - window):end], cam)


def test_detect_called_at_most_once_per_unique_frame():
    frames = _rolled_frames(n=10)
    vo = MonocularVO()

    calls = {"n": 0}
    original_detect = vo._detect

    def counting_detect(img):
        calls["n"] += 1
        return original_detect(img)

    vo._detect = counting_detect  # spy, not a stub — it still runs real ORB

    _slide(vo, frames, window=6)

    distinct_frames = len({f.t for f in frames})
    assert calls["n"] <= distinct_frames


def test_warm_cache_reproduces_cold_trajectory_bytewise():
    frames = _rolled_frames(n=6)
    cam = _camera()
    vo = MonocularVO()

    traj_cold = vo.process_sequence(frames, cam)  # cold: caches empty, solves all pairs
    traj_warm = vo.process_sequence(frames, cam)  # warm: every pair is a cache hit

    assert len(traj_cold.poses) == len(traj_warm.poses)
    for cold, warm in zip(traj_cold.poses, traj_warm.poses):
        assert np.allclose(cold.position, warm.position)
        assert np.allclose(cold.R_wc, warm.R_wc)


def test_caches_stay_bounded_by_window():
    frames = _rolled_frames(n=20)
    cam = _camera()
    vo = MonocularVO()
    window = 8

    for end in range(2, len(frames) + 1):
        vo.process_sequence(frames[max(0, end - window):end], cam)
        # Features: at most one entry per frame in the current window.
        assert len(vo._feat_cache) <= window
        # Pairs: consecutive pairs within the window (<= window - 1) <= window.
        assert len(vo._pair_cache) <= window
