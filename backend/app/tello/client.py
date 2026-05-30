"""Tello control client — the only thing in the system that talks to the Tello.

Wraps djitellopy with a connect/keepalive loop. The class is safe to construct
without a Tello on the network: `connect()` runs in a background thread and
flips `state` to CONNECTED only when the SDK handshake succeeds. Health is
exposed as a single string so `server.py` can broadcast it without leaking SDK
internals.

Lifecycle:
  - `start()` spins up the keepalive thread; idempotent.
  - `stop()` lands (if airborne), disconnects, joins the thread.
  - `send_rc(lr, fb, ud, yaw)` is the only flight surface used by follow control.
  - `takeoff()` / `land()` are exposed for mission stage transitions.
"""
from __future__ import annotations

import enum
import threading
import time
from typing import Optional


class TelloState(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    LOST = "lost"
    ERROR = "error"


class TelloClient:
    """Single-owner Tello connection. Construct once at startup, share by reference.

    All flight commands go through this client. The follow controller is the
    only legitimate caller for `send_rc`; mission transitions call takeoff/land.
    """

    # Tello's RC range is -100..100; we clamp inputs before sending.
    _RC_MIN = -100
    _RC_MAX = 100

    def __init__(self, retry_seconds: float = 3.0) -> None:
        self._retry = float(retry_seconds)
        self._state = TelloState.DISCONNECTED
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # djitellopy.Tello is created in the worker thread once import succeeds.
        self._tello = None
        self._streaming = False

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._supervisor, name="tello-supervisor", daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        tello = self._tello
        if tello is not None:
            with contextlib_suppress(Exception):
                if self._streaming:
                    tello.streamoff()
                    self._streaming = False
            with contextlib_suppress(Exception):
                if getattr(tello, "is_flying", False):
                    tello.land()
            with contextlib_suppress(Exception):
                tello.end()
        if thread is not None:
            thread.join(timeout=2.0)
        self._state = TelloState.DISCONNECTED

    # --- query -------------------------------------------------------------

    @property
    def state(self) -> TelloState:
        return self._state

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def is_connected(self) -> bool:
        return self._state is TelloState.CONNECTED

    @property
    def raw(self):
        """Underlying djitellopy.Tello for callers that need video frames or
        telemetry beyond what this wrapper exposes. None when disconnected."""
        return self._tello

    # --- commands ----------------------------------------------------------

    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> bool:
        """Send a single RC command (left/right, forward/back, up/down, yaw).
        Returns True if forwarded to the SDK, False if the link is down or the
        send raised. Never raises."""
        if not self.is_connected or self._tello is None:
            return False
        lr = _clamp(lr, self._RC_MIN, self._RC_MAX)
        fb = _clamp(fb, self._RC_MIN, self._RC_MAX)
        ud = _clamp(ud, self._RC_MIN, self._RC_MAX)
        yaw = _clamp(yaw, self._RC_MIN, self._RC_MAX)
        try:
            self._tello.send_rc_control(lr, fb, ud, yaw)
            return True
        except Exception as exc:
            self._last_error = f"rc: {exc}"
            return False

    def hover(self) -> None:
        self.send_rc(0, 0, 0, 0)

    def takeoff(self) -> bool:
        if not self.is_connected or self._tello is None:
            return False
        try:
            self._tello.takeoff()
            return True
        except Exception as exc:
            self._last_error = f"takeoff: {exc}"
            return False

    def land(self) -> bool:
        if not self.is_connected or self._tello is None:
            return False
        try:
            self._tello.land()
            return True
        except Exception as exc:
            self._last_error = f"land: {exc}"
            return False

    def battery_percent(self) -> Optional[int]:
        if not self.is_connected or self._tello is None:
            return None
        try:
            return int(self._tello.get_battery())
        except Exception:
            return None

    def enable_stream(self) -> bool:
        """Turn on the Tello video stream. Idempotent; safe to call repeatedly."""
        if not self.is_connected or self._tello is None or self._streaming:
            return self._streaming
        try:
            self._tello.streamon()
            self._streaming = True
            return True
        except Exception as exc:
            self._last_error = f"streamon: {exc}"
            return False

    # --- internals ---------------------------------------------------------

    def _supervisor(self) -> None:
        """Connect, then poll state to detect dropouts. Reconnects on failure."""
        try:
            from djitellopy import Tello  # noqa: PLC0415
        except ImportError as exc:
            self._last_error = f"djitellopy import: {exc}"
            self._state = TelloState.ERROR
            return

        while not self._stop.is_set():
            if self._state is not TelloState.CONNECTED:
                self._state = TelloState.CONNECTING
                tello = Tello()
                try:
                    tello.connect()
                    self._tello = tello
                    self._state = TelloState.CONNECTED
                    self._last_error = None
                except Exception as exc:
                    self._last_error = f"connect: {exc}"
                    self._state = TelloState.DISCONNECTED
                    self._tello = None
                    self._stop.wait(self._retry)
                    continue

            # Connected — poll battery as a cheap heartbeat. Failure = link lost.
            try:
                _ = self._tello.get_battery()
            except Exception as exc:
                self._last_error = f"heartbeat: {exc}"
                self._state = TelloState.LOST
                self._tello = None
                self._streaming = False
                self._stop.wait(self._retry)
                continue

            self._stop.wait(1.0)


# Module-level helpers -------------------------------------------------------

def _clamp(value: int, lo: int, hi: int) -> int:
    if value < lo: return lo
    if value > hi: return hi
    return value


class contextlib_suppress:
    """Tiny no-deps `contextlib.suppress` to avoid an import in this hot path."""
    def __init__(self, *exceptions): self._exc = exceptions
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, self._exc)
