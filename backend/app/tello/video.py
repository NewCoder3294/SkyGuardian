"""Tello video as a FrameSource — adapter from djitellopy's BackgroundFrameRead
into the same protocol the Mavic source uses (read_jpeg returning bytes | None).

This lets the perception pipeline + the follow controller consume Tello frames
without knowing they came from the Tello. Frames are encoded to JPEG on demand
so the rest of the system stays uniform.
"""
from __future__ import annotations

import threading
from typing import Optional

from .client import TelloClient


class TelloVideoSource:
    """FrameSource backed by the Tello SDK's frame reader.

    Calls `streamon` on `start()`; releases the reader on `stop()`. `read_jpeg()`
    is non-blocking — returns the latest decoded JPEG or None if the link is down
    or no frame has arrived yet.
    """

    def __init__(self, client: TelloClient, jpeg_quality: int = 80) -> None:
        self._client = client
        self._jpeg_quality = int(jpeg_quality)
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # cv2 imported lazily to keep this module importable in test envs.
        self._cv2 = None
        self._frame_reader = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            import cv2  # noqa: PLC0415
            self._cv2 = cv2
        except ImportError:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, name="tello-video", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._frame_reader = None

    def read_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def _reader(self) -> None:
        cv2 = self._cv2
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        while not self._stop.is_set():
            if not self._client.is_connected:
                self._frame_reader = None
                self._stop.wait(0.5)
                continue
            tello = self._client.raw
            if tello is None:
                self._stop.wait(0.25)
                continue
            if self._frame_reader is None:
                self._client.enable_stream()
                try:
                    self._frame_reader = tello.get_frame_read()
                except Exception:
                    self._stop.wait(0.5)
                    continue
            frame = self._frame_reader.frame
            if frame is None:
                self._stop.wait(0.05)
                continue
            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue
            with self._lock:
                self._latest_jpeg = buf.tobytes()
            # ~30 fps cap to avoid pegging the CPU; consumers throttle further.
            self._stop.wait(0.033)
