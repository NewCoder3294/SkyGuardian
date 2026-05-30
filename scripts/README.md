# `scripts/` — Operational helpers

Small standalone CLI scripts for provisioning, offline map prep, offline
perception dev, and bring-up. No app runtime depends on these; they are dev/ops
convenience only.

## Owns

- ✅ **`asc.py`** — App Store Connect API helper (provisioning + TestFlight path).
  Registers bundle IDs and creates app records via the ASC REST API
  (`https://api.appstoreconnect.apple.com/v1`) so the iOS app can be provisioned
  without the web UI. Auth is ES256-JWT from env only (no secrets in the repo):
  `ASC_ISSUER_ID`, `ASC_KEY_ID`, `ASC_KEY_PATH` (the `AuthKey_<KEY_ID>.p8`).
  Commands: `whoami` (auth check — lists apps), `list-bundles`,
  `register-bundle <id> <name>`, `create-app <bundleId> <name> <sku> [locale]`
  (`locale` defaults to `en-US`). Running with no args prints the module
  docstring; an unknown command exits with an error. Run from `scripts/`. JWT
  lifetime is 20 min (`exp = iat + 1200`). Deps: `pyjwt`, `requests`.

- ✅ **`fetch_buildings.py`** — one-time OSM-buildings downloader for the offline
  map layer. Run this **once before going offline** (it is the only script that
  needs the internet): it POSTs an Overpass query for every `building` footprint
  within `--radius` metres of an operator-supplied lat/lng origin, projects each
  polygon into the SkyGuardian local frame (metres, x=east, y=north, via an
  equirectangular approximation against the origin — no GPS at runtime), pulls a
  per-building `height_m` from OSM tags (falling back to `levels × 3.2`, then a
  6 m default), and writes a self-contained JSON the backend then serves
  read-only at `/map/buildings`. Multiple Overpass mirrors are tried in order
  (`overpass-api.de`, then `lz4.`/`z.` mirrors). Output JSON shape:
  `{ origin, radius_m, count, buildings: [{ id, name, height_m, polygon }] }`.
  Args: `--lat` (required), `--lng` (required), `--radius` (default `400`),
  `--out` (default `.context/buildings.json`). Usage:
  ```
  python3 scripts/fetch_buildings.py --lat 37.7749 --lng -122.4194 \
      --radius 400 --out .context/buildings.json
  ```
  Deps: stdlib only (`urllib`, `json`, `math`) — no backend venv needed.

- ✅ **`run_slam_video.py`** — offline GPS-less monocular mapping on a recorded
  clip. Samples frames at `--fps` (default 8) by decimating the video's native
  rate, builds a `CameraModel` from the frame resolution, then runs the backend
  SLAM stack: `ORBSLAM3Runner` if its binary `available()` (built when
  `ORB_SLAM3_ROOT` is set), else the pure-Python `MonocularVO`. Ingests the
  trajectory into a `LocalMap` and prints the backend name, pose/landmark
  counts, and total path length. Optional `--tag-size` (AprilTag edge length, m)
  anchors metric scale: it scans for the first two frames containing a tag,
  computes the scale via `metric_scale_from_tag`, and calls `LocalMap.set_anchor`;
  if fewer than two tag observations are found the map stays in VO units. Output
  unit is `m` once anchored, else `VO-units`. No lat/lng projection — local
  frame, origin at launch. Inserts `backend/` on `sys.path` and imports
  [`backend/app/perception/slam`](../backend/app/perception/slam/) directly.
  Usage: `python scripts/run_slam_video.py path/to/clip.mp4 [--fps 8] [--tag-size 0.20]`.
  See [`docs/SLAM.md`](../docs/SLAM.md). Deps: `opencv-python` (`cv2`), `numpy`
  (+ the backend SLAM module).

## Build notes

- `asc.py` and `fetch_buildings.py` run standalone (system Python is fine;
  `asc.py` needs `pyjwt` + `requests`, `fetch_buildings.py` is stdlib-only).
- `run_slam_video.py` inserts `backend/` on `sys.path` and needs the backend
  venv (`opencv-python`, `numpy`) — run it with the backend `.venv` active.
- `fetch_buildings.py` is the one script that requires network; run it ahead of
  any offline deployment so `.context/buildings.json` is cached locally.
- Clips and weights live in git-ignored `captures/` and `models/`.

## Planned

- ⬜ `send_intent.py` — scripted WS intent sender to drive the state machine
  without the UI.
- ⬜ `check_routing.sh` — `route get` per interface to verify the dual-WiFi
  networking (Tello AP vs. phone network). See
  [`CLAUDE.md`](../CLAUDE.md) "Networking".
- ⬜ `record_mavic.py` — capture a Mavic clip into `captures/mavic/` for
  perception dev.
