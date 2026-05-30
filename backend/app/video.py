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
import time
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


class SwitchableSource:
    """Hot-swappable FrameSource. The perception pipeline + MJPEG endpoints
    hold a reference to a single SwitchableSource; we mutate which inner
    source it delegates to without rewiring those consumers.

    Use cases: operator clicks "Upload video" → the laptop's RTMP receiver
    pipe is replaced by a file-backed StreamVideoSource; clicking "RTMP"
    restores the env-configured source. The active source's lifecycle (start/
    stop) is managed here so consumers never have to know about the swap.
    """

    def __init__(self, initial: "FrameSource", initial_kind: str = "rtmp", initial_label: str = "") -> None:
        self._inner: "FrameSource" = initial
        self._kind = initial_kind
        self._label = initial_label
        self._lock = threading.Lock()
        self._started = False

    # --- read path ----------------------------------------------------------

    def read_jpeg(self) -> Optional[bytes]:
        with self._lock:
            inner = self._inner
        return inner.read_jpeg()

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            inner = self._inner
        return bool(getattr(inner, "is_streaming", False))

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            inner = self._inner
            self._started = True
        try:
            inner.start()
        except Exception:
            pass

    def stop(self) -> None:
        with self._lock:
            inner = self._inner
            self._started = False
        try:
            inner.stop()
        except Exception:
            pass

    # --- swap ---------------------------------------------------------------

    def replace(self, new: "FrameSource", kind: str, label: str = "") -> None:
        """Swap the inner source atomically. Best-effort stop the old source
        AFTER the swap so reads briefly fall through to the new one; the new
        source is started if the wrapper was already started."""
        with self._lock:
            old = self._inner
            started = self._started
            self._inner = new
            self._kind = kind
            self._label = label
        if started:
            try:
                new.start()
            except Exception:
                pass
        try:
            old.stop()
        except Exception:
            pass

    @property
    def kind(self) -> str:
        with self._lock:
            return self._kind

    @property
    def label(self) -> str:
        with self._lock:
            return self._label


class StreamVideoSource:
    """cv2.VideoCapture-backed source with a background reader thread.

    The reader keeps the *latest* decoded frame; older frames are dropped. This
    matches what the perception loop wants: it samples at 5 Hz from a stream
    that may run at 20–30 Hz, and we don't want to play catch-up on stale frames.
    """

    # If the reader hasn't decoded a fresh frame in this window, treat the
    # source as dead. Without this, an RTMP publisher that disconnects leaves
    # the last decoded JPEG cached forever — leader.jpg keeps serving it,
    # `is_streaming` reports True, but perception sees the same frame on every
    # tick and the dashboard can't tell the feed has dropped. Tuned to outlive
    # one perception interval at 5 Hz (200 ms) plus a couple of RTMP hiccups.
    _FRESH_WINDOW_S = 3.0

    def __init__(self, spec: str | int, jpeg_quality: int = 80) -> None:
        # Late import so the module is importable without cv2 in test envs.
        import cv2  # noqa: PLC0415
        self._cv2 = cv2
        self._spec = spec
        self._jpeg_quality = int(jpeg_quality)
        self._cap = None  # type: Optional["cv2.VideoCapture"]
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_t: float = 0.0  # monotonic timestamp of last successful decode
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
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
            if self._latest_jpeg is None:
                return None
            if time.monotonic() - self._latest_t > self._FRESH_WINDOW_S:
                return None
            return self._latest_jpeg

    @property
    def is_streaming(self) -> bool:
        """True only when a fresh frame has been decoded within the freshness
        window. The opaque `_cap` exists even when the RTMP URL can't connect,
        so `_cap is not None` is a false positive; and once a publisher drops,
        `_latest_jpeg` would otherwise stay populated forever, lying about a
        live stream. Pairing freshness with the latest-frame cache lets the
        dashboard correctly fall back to its 'feed offline' state."""
        with self._lock:
            if self._latest_jpeg is None:
                return False
            return time.monotonic() - self._latest_t <= self._FRESH_WINDOW_S

    def _reader(self) -> None:
        cv2 = self._cv2
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        empty_reads = 0
        try:
            while not self._stop.is_set():
                cap = self._cap
                if cap is None:
                    # OpenCV/FFmpeg can block for many seconds opening an RTMP URL
                    # with no publisher. Do it in this daemon reader thread so app
                    # startup and source-switch HTTP requests stay responsive.
                    cap = cv2.VideoCapture(self._spec)
                    if self._stop.is_set():
                        cap.release()
                        break
                    self._cap = cap
                    empty_reads = 0

                if not cap.isOpened():
                    cap.release()
                    self._cap = None
                    self._stop.wait(2.0)
                    continue

                ok, frame = cap.read()
                if not ok or frame is None:
                    # End-of-file for files; transient hiccup for streams. Reopen
                    # periodically so a relay that starts publishing later is found.
                    empty_reads += 1
                    if empty_reads >= 20:
                        cap.release()
                        self._cap = None
                        empty_reads = 0
                        self._stop.wait(0.5)
                    else:
                        self._stop.wait(0.05)
                    continue

                empty_reads = 0
                ok, buf = cv2.imencode(".jpg", frame, encode_params)
                if not ok:
                    continue
                with self._lock:
                    self._latest_jpeg = buf.tobytes()
                    self._latest_t = time.monotonic()
        finally:
            cap = self._cap
            self._cap = None
            if cap is not None:
                cap.release()


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
