"""Video relay: the laptop owns the drone video sources and re-streams them to
clients as MJPEG over HTTP. The phone never connects to the Tello directly — it
reads the laptop's relay (honors the single-controller rule). The dashboard reads
the Mavic relay the same way.

Frame sources are pluggable: a MockCameraSource (synthetic, hardware-free dev) and,
later, real Tello (djitellopy) / Mavic (server stream) sources behind the same
FrameSource interface. Output is JPEG frames; the relay wraps them as multipart
MJPEG so any browser/phone can render the stream.
"""
from __future__ import annotations

import asyncio
import math
from typing import AsyncIterator, Protocol

import cv2
import numpy as np

from .clock import Clock, RealClock

BOUNDARY = "frame"


class FrameSource(Protocol):
    def read_jpeg(self) -> bytes | None:
        """Return the latest frame as JPEG bytes, or None if unavailable."""
        ...


class MockCameraSource:
    """Synthetic FPV-style frame so the feed pipeline works with no drone.
    Renders a horizon, a drifting target box, crosshair, and a label/timestamp."""

    def __init__(self, label: str, clock: Clock | None = None, size: tuple[int, int] = (640, 480)) -> None:
        self._label = label
        self._clock = clock or RealClock()
        self._w, self._h = size

    def read_jpeg(self) -> bytes | None:
        t = self._clock.now()
        img = np.full((self._h, self._w, 3), 22, np.uint8)  # near-black
        # horizon band
        cv2.rectangle(img, (0, self._h // 2), (self._w, self._h), (30, 38, 30), -1)
        # drifting target box
        cx = int(self._w / 2 + math.cos(t * 0.7) * self._w * 0.3)
        cy = int(self._h / 2 + math.sin(t * 1.1) * self._h * 0.18)
        cv2.rectangle(img, (cx - 26, cy - 26), (cx + 26, cy + 26), (80, 200, 120), 2)
        # crosshair
        c = (self._w // 2, self._h // 2)
        cv2.line(img, (c[0] - 18, c[1]), (c[0] + 18, c[1]), (180, 180, 180), 1)
        cv2.line(img, (c[0], c[1] - 18), (c[0], c[1] + 18), (180, 180, 180), 1)
        # labels
        cv2.putText(img, f"{self._label} - MOCK", (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 220, 200), 1)
        cv2.putText(img, f"t={t:8.1f}", (12, self._h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None


async def mjpeg_stream(source: FrameSource, fps: float = 12.0) -> AsyncIterator[bytes]:
    """Yield a multipart MJPEG stream from a frame source."""
    interval = 1.0 / fps
    while True:
        jpeg = source.read_jpeg()
        if jpeg is not None:
            yield (
                b"--" + BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
        await asyncio.sleep(interval)


MJPEG_MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
