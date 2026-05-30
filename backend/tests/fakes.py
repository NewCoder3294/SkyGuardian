"""Reusable test doubles for integration tests.

These let the perception/world/broadcast seam be exercised deterministically
with NO Ollama, NO GPU, and NO YOLO weights:

- `SyntheticVideoSource` implements the `app.video.FrameSource` protocol
  (start/stop/read_jpeg + is_streaming) and yields a fixed number of distinct
  JPEG frames. Each frame is reproducible noise with a moving white rectangle
  so monocular VO/SLAM has real features and inter-frame motion to track. After
  the frames are exhausted, `read_jpeg()` returns None forever (matching how a
  real file-backed StreamVideoSource behaves at end-of-file).

- `RecordingHub` stands in for `app.ws_hub.Hub`: `broadcast` records every
  message so a test can assert what the server would have sent to clients.
"""
from __future__ import annotations

import threading
from typing import Optional

import cv2
import numpy as np


class SyntheticVideoSource:
    """A deterministic `FrameSource` producing `num_frames` distinct JPEG frames.

    Determinism: a seeded numpy Generator produces identical noise on every run,
    so VO output and frame bytes are reproducible. The white rectangle moves a
    fixed step per frame, giving SLAM genuine optical flow to estimate motion
    from. Once all frames are read, `read_jpeg()` returns None (end-of-stream).
    """

    def __init__(self, num_frames: int = 5, width: int = 320, height: int = 240, seed: int = 0) -> None:
        self._num_frames = int(num_frames)
        self._width = int(width)
        self._height = int(height)
        self._lock = threading.Lock()
        self._index = 0
        self._started = False
        self._frames: list[bytes] = self._build_frames(seed)

    def _build_frames(self, seed: int) -> list[bytes]:
        rng = np.random.default_rng(seed)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        frames: list[bytes] = []
        for i in range(self._num_frames):
            img = rng.integers(0, 255, (self._height, self._width, 3), dtype=np.uint8)
            # Moving white rectangle: deterministic, distinct per frame, gives
            # VO a strong feature to track across the sequence.
            x = 20 + i * 30
            y = self._height // 3
            cv2.rectangle(img, (x, y), (x + 50, y + 80), (255, 255, 255), -1)
            ok, buf = cv2.imencode(".jpg", img, encode_params)
            if not ok:
                raise RuntimeError("cv2.imencode failed building synthetic frame")
            frames.append(buf.tobytes())
        return frames

    # --- FrameSource protocol ----------------------------------------------

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def read_jpeg(self) -> Optional[bytes]:
        with self._lock:
            if self._index >= len(self._frames):
                return None
            frame = self._frames[self._index]
            self._index += 1
            return frame

    @property
    def is_streaming(self) -> bool:
        # Streaming while frames remain to be read and the source is started.
        with self._lock:
            return self._started and self._index < len(self._frames)

    # --- test introspection -------------------------------------------------

    @property
    def frames_read(self) -> int:
        with self._lock:
            return self._index


class RecordingHub:
    """Stand-in for `app.ws_hub.Hub`: records every broadcast message.

    `broadcast` appends to `self.messages` so a test can assert exactly what the
    server would have pushed to connected clients. add/remove are no-ops.
    """

    def __init__(self) -> None:
        self.messages: list = []
        self._clients: set = set()

    async def add(self, client) -> None:
        self._clients.add(client)

    async def remove(self, client) -> None:
        self._clients.discard(client)

    async def broadcast(self, message) -> None:
        self.messages.append(message)

    @property
    def client_count(self) -> int:
        return len(self._clients)
