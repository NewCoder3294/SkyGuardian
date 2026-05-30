# `perception/` — Mavic recon: YOLO + SLAM (Track 2 · Brain)

## Responsibility
Consume the Mavic video stream → run YOLO detection + monocular SLAM pose →
write detected entities (with local-frame position) into the `WorldModel`.

## Interfaces
- **Reads:** Mavic video (server stream); dev against recorded clips in `captures/`.
- **Writes:** `poi` / `hazard` / `object` entities via `WorldModel.upsert`
  (source = `yolo` or `slam`).

## Build notes
- Local weights only (no cloud) — see `models/`.
- SLAM gives camera pose + a local map frame anchored to launch point + landmarks. No GPS.
- Keep detection a few FPS (recon-rate); it never sits in a real-time control loop.

## Modules
- ✅ `slam/` — **GPS-less monocular mapping.** Pure-Python VO default +
  optional ORB-SLAM3 backend, AprilTag metric scale anchor, local-frame map that
  feeds the world model. See [`slam/README.md`](./slam/README.md) and
  [`../../../docs/SLAM.md`](../../../docs/SLAM.md).
- ⬜ `yolo.py` — *(planned)* ultralytics inference → boxes/classes.
- ⬜ `fusion.py` — *(planned)* YOLO box + SLAM pose → entity position in local frame → upsert.

The package root currently holds only `__init__.py` (empty) — detection/fusion is
⬜ not started; only the `slam/` subpackage is built.
