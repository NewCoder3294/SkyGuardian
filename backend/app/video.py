"""Video source abstraction for the Mavic feed (and any other camera).

The perception pipeline reads JPEG bytes from a FrameSource. Source identity
(RTMP URL, local file, USB device index) is configured via env vars at startup
so the rest of the system never knows where pixels came from.

Spec parsed from MAVIC_SOURCE:
  - "url:rtmp://host/path"   → cv2.VideoCapture(url)
  - "url:http://host/stream" → cv2.VideoCapture(url)
  - "file:/path/to/clip.mp4" → cv2.VideoCapture(path)
  - "device:0"               → cv2.VideoCapture(0)
  - unset / empty            → NullSource (always returns None, no frames)

All sources are best-effort and offline: cv2.VideoCapture decodes whatever
ffmpeg/avfoundation/v4l backends are compiled in. They never reach the
network beyond the configured URL.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Protocol


class FrameSource(Protocol):
    """Anything that can produce the latest frame as JPEG bytes on demand.

    `start()` may be a no-op or may spin up a reader thread (for streams whose
    backend buffers frames). `read_jpeg()` must be non-blocking-ish: callers
    pace themselves at `PERCEPTION_FPS` and expect a sub-frame-interval return.
    `None` means no frame is currently available.
    """

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read_jpeg(self) -> Optional[bytes]: ...


class NullSource:
    """No-op source: nothing ever ready. Used when MAVIC_SOURCE is unset."""

    def start(self) -> None: pass
    def stop(self) -> None: pass
    def read_jpeg(self) -> Optional[bytes]: return None

    @property
    def is_streaming(self) -> bool: return False


class StreamVideoSource:
    """cv2.VideoCapture-backed source with a background reader thread.

    The reader keeps the *latest* decoded frame; older frames are dropped. This
    matches what the perception loop wants: it samples at 5 Hz from a stream
    that may run at 20–30 Hz, and we don't want to play catch-up on stale frames.
    """

    def __init__(self, spec: str | int, jpeg_quality: int = 80) -> None:
        # Late import so the module is importable without cv2 in test envs.
        import cv2  # noqa: PLC0415
        self._cv2 = cv2
        self._spec = spec
        self._jpeg_quality = int(jpeg_quality)
        self._cap = None  # type: Optional["cv2.VideoCapture"]
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._cap = self._cv2.VideoCapture(self._spec)
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, name="video-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    @property
    def is_streaming(self) -> bool:
        """True only once at least one frame has actually been decoded — the
        opaque `_cap` object exists even when the RTMP URL can't connect, so
        `_cap is not None` is a false positive. The reader only fills
        `_latest_jpeg` after a successful read+encode."""
        with self._lock:
            return self._latest_jpeg is not None

    def _reader(self) -> None:
        cv2 = self._cv2
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        while not self._stop.is_set():
            cap = self._cap
            if cap is None or not cap.isOpened():
                self._stop.wait(0.25)
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                # End-of-file for files; transient hiccup for streams. Brief pause.
                self._stop.wait(0.05)
                continue
            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue
            with self._lock:
                self._latest_jpeg = buf.tobytes()


def make_source(spec: Optional[str]) -> FrameSource:
    """Build a FrameSource from an env-style spec. Returns NullSource for unset."""
    if not spec:
        return NullSource()
    if ":" not in spec:
        # Bare path or URL — best-effort treat as a stream target.
        return StreamVideoSource(spec)
    kind, _, value = spec.partition(":")
    kind = kind.lower()
    if kind == "url":
        return StreamVideoSource(value)
    if kind == "file":
        path = Path(value).expanduser()
        return StreamVideoSource(str(path))
    if kind == "device":
        try:
            return StreamVideoSource(int(value))
        except ValueError as exc:
            raise ValueError(f"device spec must be an integer index, got {value!r}") from exc
    raise ValueError(f"unknown video source kind {kind!r} in {spec!r}")
