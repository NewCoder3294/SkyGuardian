# `captures/` — Recorded media for hardware-free dev (git-ignored)

Recorded Mavic clips and Tello frames so perception (Track 2) and the follow
controller (Track 1) can be developed and replayed without live drones.

Currently empty (only this README is tracked) — ⬜ no clips landed yet. Drop
recordings here under the layout below as they're captured.

- `mavic/` — recorded recon video for YOLO + SLAM dev — feeds
  [`backend/app/perception/slam/`](../backend/app/perception/slam/) ([`docs/SLAM.md`](../docs/SLAM.md)).
- `tello/` — recorded Tello frames with an AprilTag in view, for follow tuning
  (`backend/app/follow/`, ⬜ not started).

Keep clips short and representative. Everything here is git-ignored; share
out-of-band.
