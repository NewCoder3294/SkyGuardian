# `tello/` — Tello transport layer (Track 1 · Robotics) — ⬜ not started

Low-level Tello control + video, isolated from the follow policy so the
controller in [`../follow/`](../follow/README.md) stays testable without
hardware. **Status:** stub (`__init__.py` only). See
[`../../../CLAUDE.md`](../../../CLAUDE.md) and
[`../../../docs/VIDEO.md`](../../../docs/VIDEO.md).

## Responsibility
- Connect to the Tello AP; bind the control UDP socket to the Tello interface IP.
- Send `command`/`rc`/`takeoff`/`land` primitives; keep SDK mode alive (the Tello
  drops out of SDK mode without periodic commands).
- Expose video frames with a freshness/age guard (drop stale frames).
- Surface connection state (`connected` / `lost`) for `health` reporting.

## Interfaces
- **Reads:** UDP from the Tello (state telemetry, H.264 video).
- **Writes:** control commands to the Tello; frames + connection state to its
  caller.
- Consumed only by [`../follow/`](../follow/README.md). The laptop is the **sole**
  Tello controller — never imported by clients or perception, and clients never
  command the Tello directly.

## Build notes
- The live Tello path already exists outside this package, in
  [`../video.py`](../video.py) (`TelloVideoSource`): raw Tello SDK over UDP
  (`command`/`streamon` + keepalive) with OpenCV/ffmpeg H.264 decode —
  deliberately **not** `djitellopy` for the video path. When this package is
  built, the control primitives here should follow that same raw-UDP approach;
  `djitellopy` remains an option for the higher-level control/state wrapper.
- Tello AP IP is `192.168.10.1`.

## Planned modules
- ⬜ `client.py` — connect, `command`/`rc`, `takeoff`/`land`, state, keepalive.
- ⬜ `video.py` — frame grab with freshness/age guard (or reuse `TelloVideoSource`).
