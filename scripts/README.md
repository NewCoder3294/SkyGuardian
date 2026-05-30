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
  Running with no args (or an unknown command) prints the module docstring. Run
  from `scripts/`. JWT lifetime is 20 min (`exp = iat + 1200`). Deps: `pyjwt`,
  `requests`.

- ✅ **`run_slam_video.py`** — offline GPS-less monocular mapping on a recorded
  clip. Samples frames at `--fps` (default 8) by decimating the video's native
  rate, builds a `CameraModel` from the frame resolution, then runs the backend
  SLAM stack: `ORBSLAM3Runner` if its binary `available()`, else the pure-Python
  `MonocularVO`. Feeds the trajectory into a `LocalMap` and prints the backend
  name, pose/landmark counts, and total path length. Optional `--tag-size`
  (AprilTag edge length, m) anchors metric scale: it looks for the first two
  frames containing a tag, computes the scale via `metric_scale_from_tag`, and
  calls `LocalMap.set_anchor`; if fewer than two tag observations are found the
  map stays in VO units. Output unit is `m` once anchored, else `VO-units`. No
  lat/lng projection — local frame, origin at launch. Inserts `backend/` on
  `sys.path` and imports
  [`backend/app/perception/slam`](../backend/app/perception/slam/) directly.
  Usage: `python scripts/run_slam_video.py path/to/clip.mp4 [--fps 8] [--tag-size 0.20]`.
  See [`docs/SLAM.md`](../docs/SLAM.md). Deps: `opencv-python` (`cv2`), `numpy`
  (+ the backend SLAM module).

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
