# `tello/` — Tello transport layer (Track 1 · Robotics)

Low-level Tello control + video, isolated from the follow policy so the
controller in [`../follow/`](../follow/README.md) stays testable without
hardware. See [`../../../CLAUDE.md`](../../../CLAUDE.md) and
[`../../../docs/VIDEO.md`](../../../docs/VIDEO.md).

This package is the **only** *backend* code that talks to the Tello: it is the
laptop-side flight path, never imported by the dashboard or perception. Note the
current architecture (see [`../../../CLAUDE.md`](../../../CLAUDE.md)) — the
**phone** is the primary Tello controller (on-device follow + voice, commanding
the Tello directly over its AP). This `TelloClient` is an **alternate** backend
controller and must stay disarmed while the phone is flying; only one controller
is armed against the Tello at a time (an operating rule — there is no code
interlock yet). Both control and video here are `djitellopy`-backed.

## Responsibility
- Connect to the Tello AP and keep the SDK link alive across dropouts.
- Send `rc`/`takeoff`/`land` primitives; the supervisor thread also polls the
  Tello (`get_battery` once per second) as a cheap heartbeat to detect dropouts.
- Expose connection state as a single enum for `health` reporting.
- Expose video frames through a `FrameSource`-compatible adapter so the
  perception pipeline and follow controller consume Tello frames uniformly.

## Interfaces
- **Reads:** UDP from the Tello (state telemetry, H.264 video) via djitellopy.
- **Writes:** RC/takeoff/land commands to the Tello; latest JPEG frame +
  connection state to its callers.
- `TelloClient` is constructed once at startup and shared by reference; on the
  backend the [`FollowController`](../follow/README.md) is the only legitimate
  caller of `send_rc`, and mission/state transitions call `takeoff`/`land`.

## Modules

### `client.py` — `TelloClient`
Single-owner Tello connection wrapping `djitellopy.Tello`. Safe to construct
without a Tello on the network: connection runs in a background supervisor
thread and `state` only flips to `CONNECTED` once the SDK handshake succeeds.

Lifecycle:
- `start()` spins up the `tello-supervisor` keepalive thread; idempotent.
- `stop()` turns the stream off, lands if airborne, calls `tello.end()`, joins
  the thread (2s timeout), and resets state to `DISCONNECTED`.

State is the `TelloState` enum: `DISCONNECTED`, `CONNECTING`, `CONNECTED`,
`LOST`, `ERROR`. Exposed read-only via the `state`, `last_error`,
`is_connected`, and `raw` properties (`raw` is the underlying
`djitellopy.Tello`, or `None` when disconnected — used by `video.py`).

Commands (all are no-ops returning `False`/`None` when the link is down, and
never raise — failures are recorded in `last_error`):
- `send_rc(lr, fb, ud, yaw)` — the only flight surface used by follow control.
  Inputs are clamped to the Tello RC range `-100..100` before sending. Returns
  `True` if forwarded to the SDK.
- `hover()` — convenience for `send_rc(0, 0, 0, 0)`.
- `takeoff()` / `land()` — for mission stage transitions.
- `battery_percent()` — returns `int` or `None`.
- `enable_stream()` — `streamon`; idempotent, tracks a `_streaming` flag and
  returns the current flag value (no-op returning `_streaming` when already
  streaming or the link is down).

Supervisor loop (`_supervisor`): imports `djitellopy` lazily (sets `ERROR` and
exits if unavailable), connects (retrying every `retry_seconds`, default 3.0,
on failure), then once connected polls `get_battery()` once per second as a
cheap heartbeat. A heartbeat exception flips state to `LOST`, drops the handle,
clears the `_streaming` flag (so the stream is re-enabled on reconnect), and the
loop reconnects.

### `video.py` — `TelloVideoSource`
Adapts djitellopy's `BackgroundFrameRead` into the same `FrameSource` protocol
the Mavic source uses: `read_jpeg() -> bytes | None`. So the rest of the system
consumes Tello frames without knowing their origin.

- `start()` imports `cv2` lazily (returns silently if unavailable, keeping the
  module importable in test envs) and spins up the `tello-video` reader thread;
  idempotent.
- `stop()` signals the thread, joins it (2s timeout), and clears the frame
  reader.
- `read_jpeg()` is non-blocking — returns the latest decoded JPEG or `None` if
  the link is down or no frame has arrived yet.
- Reader thread (`_reader`): waits until the client is connected, calls
  `enable_stream()` + `get_frame_read()`, then encodes each frame to JPEG
  (quality configurable via `jpeg_quality`, default 80) at a ~30 fps cap.
  Drops to `None` and backs off when the link goes down.

## Notes
- Tello AP IP is `192.168.10.1`. Bind the control UDP socket to the Tello WiFi
  interface IP (handled by djitellopy / the host network setup).
- No live-hardware tests for this package; correctness depends on the
  `djitellopy` contract. The follow controller is tested independently against
  a fake client — see [`../follow/`](../follow/README.md) and
  [`../../tests/`](../../tests/).
