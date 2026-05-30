# `scripts/` — Operational helpers

Small standalone CLI scripts for provisioning, offline perception dev, and
bring-up. No app runtime depends on these; they are dev/ops convenience only.

## Owns

- ✅ **`asc.py`** — App Store Connect API helper (provisioning + TestFlight path).
  Registers bundle IDs and creates app records via the ASC REST API so the iOS
  app can be provisioned without the web UI. Auth is ES256-JWT from env only (no
  secrets in the repo): `ASC_ISSUER_ID`, `ASC_KEY_ID`, `ASC_KEY_PATH` (the
  `AuthKey_<KEY_ID>.p8`). Commands: `whoami` (auth check), `list-bundles`,
  `register-bundle <id> <name>`, `create-app <bundleId> <name> <sku> [locale]`.
  Run from `scripts/`. Pairs with the archive/upload lane referenced in the root
  [`README.md`](../README.md#build--ship-the-ios-app). Deps: `pyjwt`, `requests`.

- ✅ **`run_slam_video.py`** — offline GPS-less monocular mapping on a recorded
  clip. Samples frames from a video, runs the backend SLAM stack
  (`ORBSLAM3Runner` if `ORB_SLAM3_ROOT` is built, else the pure-Python
  `MonocularVO`), and reports the local-frame trajectory + path length. Optional
  `--tag-size` anchors metric scale from an AprilTag of known edge length seen in
  the clip; otherwise the map stays in VO units. No lat/lng projection — local
  frame, origin at launch. Imports
  [`backend/app/perception/slam`](../backend/app/perception/slam/) directly.
  Usage: `python scripts/run_slam_video.py path/to/clip.mp4 [--fps 8] [--tag-size 0.20]`.
  See [`docs/SLAM.md`](../docs/SLAM.md). Deps: `opencv-python`, `numpy` (+ the
  backend SLAM module).

## Build notes

- `asc.py` runs standalone; `run_slam_video.py` inserts `backend/` on `sys.path`
  and needs the backend venv (`opencv-python`, `numpy`) — run it with the backend
  `.venv` active.
- Clips and weights live in git-ignored `captures/` and `models/`.

## Planned

- ⬜ `send_intent.py` — scripted WS intent sender to drive the state machine
  without the UI.
- ⬜ `check_routing.sh` — `route get` per interface to verify the dual-WiFi
  networking (Tello AP vs. phone network). See
  [`CLAUDE.md`](../CLAUDE.md) "Networking".
- ⬜ `record_mavic.py` — capture a Mavic clip into `captures/mavic/` for
  perception dev.
