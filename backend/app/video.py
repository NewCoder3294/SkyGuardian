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
import os
import socket
import threading
import time
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


async def mjpeg_stream(source: FrameSource, fps: float = 20.0) -> AsyncIterator[bytes]:
    """Yield a multipart MJPEG stream from a frame source. The (possibly blocking)
    frame read + JPEG encode runs off the event loop so the server stays responsive."""
    interval = 1.0 / fps
    while True:
        jpeg = await asyncio.to_thread(source.read_jpeg)
        if jpeg is not None:
            yield (
                b"--" + BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
        await asyncio.sleep(interval)


class DisabledSource:
    """No source configured -> no frames. Honest empty feed (not a mock)."""

    def read_jpeg(self) -> bytes | None:
        return None


class StreamVideoSource:
    """Latest frame from any OpenCV-openable stream (RTSP/HTTP/MJPEG). Used for the
    Mavic, whose video arrives via the existing server stream. `start()` opens the
    capture (blocking) once at startup; read_jpeg is non-blocking after that."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._cap = None

    def start(self) -> None:
        cap = cv2.VideoCapture(self._url)
        if cap.isOpened():
            self._cap = cap

    def read_jpeg(self) -> bytes | None:
        if self._cap is None or not self._cap.isOpened():
            return None
        ok, frame = self._cap.read()
        if not ok:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None


class TelloVideoSource:
    """Live Tello camera. The laptop is the sole Tello controller; this ingests its
    video and the relay re-streams it to the phone.

    Uses the raw Tello SDK over UDP for control (command/streamon + keepalive) and
    OpenCV/ffmpeg to decode the H.264 video stream — deliberately NOT djitellopy,
    which pulls in PyAV and conflicts with OpenCV's bundled ffmpeg dylibs. `start()`
    sends streamon and opens the stream; a background thread keeps the latest frame
    fresh. read_jpeg is non-blocking and returns None until the first frame decodes.
    """

    TELLO_IP = "192.168.10.1"
    CMD_PORT = 8889
    VIDEO_URL = "udp://@0.0.0.0:11111?overrun_nonfatal=1&fifo_size=50000000"

    def __init__(self) -> None:
        self._cap = None
        self._sock = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False

    def _send(self, cmd: str) -> None:
        if self._sock is not None:
            self._sock.sendto(cmd.encode(), (self.TELLO_IP, self.CMD_PORT))

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Bind to the Tello-subnet interface IP when set (per CLAUDE.md routing),
            # not 0.0.0.0. Defaults to "" for back-compat; set TELLO_BIND_IP to harden.
            sock.bind((os.environ.get("TELLO_BIND_IP", ""), self.CMD_PORT))
            self._sock = sock
            self._send("command")
            time.sleep(0.5)
            self._send("streamon")
            time.sleep(2.0)
            self._cap = cv2.VideoCapture(self.VIDEO_URL, cv2.CAP_FFMPEG)
        except Exception:
            sock.close()
            self._sock = None
            raise
        self._running = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._keepalive, daemon=True).start()

    def stop(self) -> None:
        """Release the socket, capture, and stop the worker threads."""
        self._running = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _reader(self) -> None:
        while self._running and self._cap is not None:
            ok, frame = self._cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
                time.sleep(0.005)  # cap the reader; we only need the latest frame
            else:
                time.sleep(0.01)  # no keyframe yet; don't busy-spin

    def _keepalive(self) -> None:
        # The Tello leaves SDK mode (and stops streaming) without periodic commands.
        while self._running:
            time.sleep(5.0)
            self._send("command")

    def read_jpeg(self) -> bytes | None:
        with self._lock:
            frame = self._frame
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None


def make_source(spec: str, label: str, clock: Clock | None = None) -> FrameSource:
    """Select a frame source from a spec string:
      'tello'      -> live Tello via djitellopy (the phone feed)
      'url:<URL>'  -> any OpenCV stream (Mavic server stream / RTSP / HTTP)
      'mock'       -> synthetic frames (explicit opt-in for hardware-free UI dev)
      anything else / unset -> DisabledSource (honest empty feed, no mock)
    """
    if spec == "tello":
        return TelloVideoSource()
    if spec.startswith("url:"):
        return StreamVideoSource(spec[len("url:"):])
    if spec == "mock":
        return MockCameraSource(label, clock=clock)
    return DisabledSource()


MJPEG_MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
