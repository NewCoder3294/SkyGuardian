# `tello/` — Tello transport layer (Track 1 · Robotics)

Low-level Tello control + video, isolated from the follow policy so the
controller logic in `follow/` stays testable without hardware.

## Responsibility
- Connect to the Tello AP, bind the UDP socket to the Tello interface IP.
- Send rc/command primitives; expose the video frames.
- Surface connection state (`connected` / `lost`) for `health` reporting.

## Interface
- Consumed only by `follow/`. Never imported by clients or perception.

## Planned modules
- `client.py` — djitellopy wrapper (connect, command, rc, takeoff/land, state).
- `video.py` — frame grab with freshness/age guard (drop stale frames).
