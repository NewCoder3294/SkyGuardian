# `scripts/` — Operational helpers

Small standalone CLI scripts for provisioning, offline map prep, offline
perception dev, bring-up, and the post-mission capture data flywheel (clean →
package → export). No app runtime depends on these; they are dev/ops convenience
only.

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

### Capture data flywheel (clean → package → export)

Three thin CLI wrappers over `backend/app/capture/`, run in order on a recorded
mission directory under `captures/<mission_id>/`. Each inserts `backend/` on
`sys.path` and calls the matching `app.capture.*` module (the wrapper holds no
logic of its own). Mission subdirectories under `captures/` are git-ignored.

- ✅ **`clean_captures.py`** — clean phase. Filters a mission's raw capture into a
  curated observation set (drops corrupt/blank frames, near-duplicate frames via
  perceptual hash, and low-confidence boxes; quarantines unparseable records),
  writing `cleaned/observations.jsonl` + an auditable `cleaning_report.json`. Calls
  `app.capture.cleaning.clean_mission`. Args: `--mission` (required, the id under
  `--root`), `--root` (default `captures`), `--dup-threshold` (default `5`),
  `--conf-floor` (default `0.1`), `--blank-std` (grayscale std below which a frame
  is treated as blank, default `5.0`). Prints `[clean] <report-json>`. Deps:
  `opencv-python` (`cv2`), `numpy` (backend venv).

- ✅ **`package_dataset.py`** — package phase. Turns the cleaned observations (+
  events) into a YOLO dataset + Gemma example set + a Foundry-ready
  `manifest.json`. The train/val split is a deterministic hash of the frame path
  (reproducible, no RNG). Calls `app.capture.packaging.package_dataset`. Args:
  `--mission` (required), `--root` (default `captures`), `--out` (required, the
  output dataset dir), `--val-frac` (default `0.2`), `--created-t` (timestamp
  stamped into the manifest; injected, default `0`). Prints `[package]
  <manifest-json>`. Deps: stdlib + the backend `app.capture` module (backend venv).

- ✅ **`export_to_foundry.py`** — export phase (post-mission, **ONLINE**). Pushes a
  packaged dataset dir (the one with `manifest.json`) into Palantir Foundry. Calls
  `app.capture.foundry_export.export_dataset` with a `FoundryConfig.from_env()` +
  `FoundryClient`. Requires internet + Foundry credentials from env:
  `FOUNDRY_HOST`, `FOUNDRY_TOKEN`, `FOUNDRY_ONTOLOGY_RID`, `FOUNDRY_DATASET_RID`
  (optional overrides: `FOUNDRY_ACTION_MISSION`, `FOUNDRY_ACTION_CLASS`,
  `FOUNDRY_ACTION_MISSION_EDIT`, `FOUNDRY_ACTION_CLASS_EDIT`, `FOUNDRY_TIMEOUT_S`,
  `FOUNDRY_MAX_RETRIES`). Args: `--dataset` (required), `--dry-run` (validate
  config + payloads and write the report with **no** network call — the client is
  replaced by a stub that asserts on any call). A missing/invalid config exits `2`.
  Prints `[foundry] <subset-of-report-json>`. The `CaptureMission` + `DetectionClass`
  object types and their create-/edit- actions must already exist in the ontology.

## Build notes

- `asc.py` runs standalone but needs `pyjwt` + `requests`.
- `fetch_buildings.py` inserts `backend/` on `sys.path` (the fetch/projection/write
  logic lives in `backend/app/map_area.py`, shared with the dashboard's
  `POST /map/area`), so run it with the backend `.venv` active.
- `run_slam_video.py`, `clean_captures.py`, and `package_dataset.py` all insert
  `backend/` on `sys.path` and need the backend venv (`run_slam_video.py` +
  `clean_captures.py` use `opencv-python` / `numpy`; `package_dataset.py` is
  otherwise stdlib) — run them with the backend `.venv` active.
- Network is needed at two points only: `fetch_buildings.py` (Overpass; run it
  ahead of any offline deployment so `.context/buildings.json` is cached locally),
  `export_to_foundry.py` (Foundry; post-mission, ONLINE — or `--dry-run` to skip
  the network), plus `asc.py` (App Store Connect). Everything else is local.
- Clips and weights live in git-ignored `captures/` and `models/`; the capture
  flywheel scripts read/write mission subdirectories under `captures/`, which are
  also git-ignored.

## Planned

- ⬜ `send_intent.py` — scripted WS intent sender to drive the state machine
  without the UI.
- ⬜ `check_routing.sh` — `route get` per interface to verify the dual-WiFi
  networking (Tello AP vs. phone network). See
  [`CLAUDE.md`](../CLAUDE.md) "Networking".
- ⬜ `record_mavic.py` — a standalone CLI to capture a Mavic clip into
  `captures/mavic/` for perception dev. (In-mission recording itself already
  exists in the backend as `app.capture.recorder.CaptureRecorder`; this would be
  the loose dev wrapper around it.)
